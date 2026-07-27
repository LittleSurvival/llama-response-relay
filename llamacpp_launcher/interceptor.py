from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import math
import threading
import time
from typing import Any, Callable

from aiohttp import ClientError, ClientSession, ClientTimeout, web

from .models import Glossary, ValidationError
from .replacement import CompiledGlossary, IncrementalReplacer
from .telemetry import RequestSummary


COMPLETION_PATHS = {"/v1/chat/completions", "/v1/completions"}
SUPPORTED_PATHS = COMPLETION_PATHS | {"/v1/models"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
TRANSFORMED_RESPONSE_HEADERS = HOP_BY_HOP_HEADERS | {"content-encoding"}
DEFAULT_CORS_HEADERS = "Authorization, Content-Type, Accept, X-Requested-With"
SummaryCallback = Callable[[RequestSummary], None]


def _cors_headers(request: web.Request) -> dict[str, str]:
    requested_headers = request.headers.get(
        "Access-Control-Request-Headers", ""
    ).strip()
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": requested_headers or DEFAULT_CORS_HEADERS,
        "Access-Control-Expose-Headers": "Content-Type",
        "Access-Control-Max-Age": "86400",
        "Vary": "Access-Control-Request-Headers",
    }


@web.middleware
async def _cors_middleware(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=_cors_headers(request))
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = web.Response(
            status=exc.status,
            reason=exc.reason,
            text=exc.text,
            headers=exc.headers,
        )
    response.headers.update(_cors_headers(request))
    return response


def upstream_base_url(host: str, port: int) -> str:
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in connect_host and not connect_host.startswith("["):
        connect_host = f"[{connect_host}]"
    return f"http://{connect_host}:{port}"


def transform_completion_json(
    payload: dict[str, Any],
    path: str,
    glossary: CompiledGlossary,
) -> dict[str, Any]:
    transformed = deepcopy(payload)
    choices = transformed.get("choices")
    if not isinstance(choices, list):
        return transformed
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        if path == "/v1/chat/completions":
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                message["content"] = glossary.replace(message["content"])
        elif isinstance(choice.get("text"), str):
            choice["text"] = glossary.replace(choice["text"])
    return transformed


class SseCompletionTransformer:
    def __init__(self, path: str, glossary: CompiledGlossary) -> None:
        self.path = path
        self.glossary = glossary
        self.matchers: dict[int, IncrementalReplacer] = {}
        self.last_metadata: dict[str, Any] = {}

    def transform_data(self, data: str) -> list[str]:
        if data.strip() == "[DONE]":
            return [*self.flush_events(), "[DONE]"]
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return [data]
        if not isinstance(payload, dict):
            return [data]
        choices = payload.get("choices")
        if not isinstance(choices, list):
            return [data]
        self.last_metadata = {key: deepcopy(value) for key, value in payload.items() if key != "choices"}
        for position, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            index = choice.get("index", position)
            if not isinstance(index, int):
                index = position
            matcher = self.matchers.setdefault(index, IncrementalReplacer(self.glossary))
            if self.path == "/v1/chat/completions":
                container = choice.get("delta")
                field = "content"
            else:
                container = choice
                field = "text"
            if isinstance(container, dict) and isinstance(container.get(field), str):
                container[field] = matcher.feed(container[field])
            if choice.get("finish_reason") is not None:
                tail = matcher.flush()
                if tail:
                    if not isinstance(container, dict):
                        if self.path == "/v1/chat/completions":
                            choice["delta"] = {}
                            container = choice["delta"]
                        else:
                            container = choice
                    current = container.get(field)
                    container[field] = (current if isinstance(current, str) else "") + tail
        return [json.dumps(payload, ensure_ascii=False, separators=(",", ":"))]

    def flush_events(self) -> list[str]:
        events: list[str] = []
        for index, matcher in self.matchers.items():
            tail = matcher.flush()
            if not tail:
                continue
            event = deepcopy(self.last_metadata)
            if self.path == "/v1/chat/completions":
                choice: dict[str, Any] = {
                    "index": index,
                    "delta": {"content": tail},
                    "finish_reason": None,
                }
            else:
                choice = {"index": index, "text": tail, "finish_reason": None}
            event["choices"] = [choice]
            events.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        return events


class InterceptorServer:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._session: ClientSession | None = None
        self._started = threading.Event()
        self._startup_error: BaseException | None = None
        self._upstream_base = ""
        self._compiled = CompiledGlossary.from_glossary(None)
        self._host = ""
        self._port = 0
        self._request_summary_callback: SummaryCallback | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive() and self._startup_error is None

    @property
    def endpoint(self) -> str:
        with self._lock:
            return f"http://{self._host}:{self._port}" if self._host else ""

    def set_request_summary_callback(
        self, callback: SummaryCallback | None
    ) -> None:
        with self._lock:
            self._request_summary_callback = callback

    def start(
        self,
        host: str,
        port: int,
        upstream_base: str,
        glossary: Glossary | None,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not host.strip():
            raise ValidationError("LRR host is required.")
        if not 1 <= int(port) <= 65535:
            raise ValidationError("LRR port must be between 1 and 65535.")
        if timeout_seconds <= 0:
            raise ValidationError("LRR startup timeout must be positive.")
        with self._lock:
            if self.is_running:
                raise ValidationError("LRR interceptor is already running.")
            self._host = host.strip()
            self._port = int(port)
            self._upstream_base = upstream_base.rstrip("/")
            self._compiled = CompiledGlossary.from_glossary(glossary)
            self._started = threading.Event()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._thread_main,
                name="lrr-interceptor",
                daemon=True,
            )
            self._thread.start()
        if not self._started.wait(timeout_seconds):
            self.stop(timeout_seconds=timeout_seconds)
            raise ValidationError("LRR interceptor startup timed out.")
        if self._startup_error is not None:
            error = self._startup_error
            thread = self._thread
            if thread is not None:
                thread.join(timeout_seconds)
            with self._lock:
                self._thread = None
                self._loop = None
                self._runner = None
                self._session = None
                self._host = ""
                self._port = 0
            raise ValidationError(f"Could not start LRR interceptor: {error}") from error

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        with self._lock:
            loop = self._loop
            thread = self._thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_seconds)
            if thread.is_alive():
                raise ValidationError("LRR interceptor did not stop in time.")
        with self._lock:
            self._thread = None
            self._loop = None
            self._runner = None
            self._session = None
            self._host = ""
            self._port = 0

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        with self._lock:
            self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_async())
        except BaseException as exc:
            self._startup_error = exc
            self._started.set()
        else:
            self._started.set()
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(self._cancel_pending_tasks())
                loop.run_until_complete(self._cleanup_async())
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    async def _cancel_pending_tasks(self) -> None:
        current = asyncio.current_task()
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not current and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _start_async(self) -> None:
        app = web.Application(middlewares=[_cors_middleware])
        app.router.add_post("/v1/chat/completions", self._handle)
        app.router.add_post("/v1/completions", self._handle)
        app.router.add_get("/v1/models", self._handle)
        self._session = ClientSession(timeout=ClientTimeout(total=None, sock_connect=10))
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()

    async def _cleanup_async(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        started = time.monotonic()
        if request.path not in SUPPORTED_PATHS:
            raise web.HTTPNotFound()
        if self._session is None:
            return web.json_response({"error": "LRR is not ready."}, status=503)
        upstream_url = self._upstream_base + request.rel_url.path_qs
        body = await request.read()
        headers = _filtered_headers(request.headers, HOP_BY_HOP_HEADERS)
        try:
            upstream = await self._session.request(
                request.method,
                upstream_url,
                data=body,
                headers=headers,
            )
        except (ClientError, asyncio.TimeoutError, OSError) as exc:
            self._emit_request_summary(request.path, 502, started)
            return web.json_response(
                {"error": f"Could not reach llama.cpp: {exc}"}, status=502
            )
        async with upstream:
            response_headers = _filtered_headers(
                upstream.headers, TRANSFORMED_RESPONSE_HEADERS
            )
            if upstream.status < 200 or upstream.status >= 300:
                raw = await upstream.read()
                self._emit_request_summary(
                    request.path,
                    upstream.status,
                    started,
                    _json_object(raw),
                )
                return web.Response(
                    body=raw,
                    status=upstream.status,
                    headers=response_headers,
                )
            if request.path == "/v1/models":
                return web.Response(
                    body=await upstream.read(),
                    status=upstream.status,
                    headers=response_headers,
                )
            content_type = upstream.headers.get("Content-Type", "").casefold()
            if "text/event-stream" in content_type:
                return await self._stream_sse(
                    request, upstream, response_headers, started
                )
            raw = await upstream.read()
            if "application/json" not in content_type:
                self._emit_request_summary(request.path, upstream.status, started)
                return web.Response(
                    body=raw, status=upstream.status, headers=response_headers
                )
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._emit_request_summary(request.path, upstream.status, started)
                return web.Response(
                    body=raw, status=upstream.status, headers=response_headers
                )
            if not isinstance(payload, dict):
                self._emit_request_summary(request.path, upstream.status, started)
                return web.Response(
                    body=raw, status=upstream.status, headers=response_headers
                )
            transformed = transform_completion_json(
                payload, request.path, self._compiled
            )
            encoded = json.dumps(
                transformed, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            response_headers["Content-Type"] = "application/json; charset=utf-8"
            self._emit_request_summary(
                request.path, upstream.status, started, payload
            )
            return web.Response(
                body=encoded, status=upstream.status, headers=response_headers
            )

    async def _stream_sse(
        self,
        request: web.Request,
        upstream: Any,
        headers: dict[str, str],
        started: float,
    ) -> web.StreamResponse:
        headers["Content-Type"] = "text/event-stream; charset=utf-8"
        headers.update(_cors_headers(request))
        response = web.StreamResponse(status=upstream.status, headers=headers)
        await response.prepare(request)
        transformer = SseCompletionTransformer(request.path, self._compiled)
        saw_done = False
        first_byte_at: float | None = None
        summary_payload: dict[str, Any] = {}
        try:
            async for raw_line in upstream.content:
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    first_byte_at = first_byte_at or time.monotonic()
                    await response.write(raw_line)
                    continue
                stripped = line.rstrip("\r\n")
                if not stripped.startswith("data:"):
                    first_byte_at = first_byte_at or time.monotonic()
                    await response.write(raw_line)
                    continue
                data = stripped[5:].lstrip()
                _merge_summary_metadata(summary_payload, data)
                outputs = transformer.transform_data(data)
                if data.strip() == "[DONE]":
                    saw_done = True
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                for output in outputs:
                    first_byte_at = first_byte_at or time.monotonic()
                    await response.write(
                        f"data: {output}{newline}".encode("utf-8")
                    )
                    if output != "[DONE]" and len(outputs) > 1:
                        await response.write(newline.encode("ascii"))
            if not saw_done:
                for output in transformer.flush_events():
                    first_byte_at = first_byte_at or time.monotonic()
                    await response.write(f"data: {output}\n\n".encode("utf-8"))
            await response.write_eof()
        finally:
            self._emit_request_summary(
                request.path,
                upstream.status,
                started,
                summary_payload,
                first_byte_at,
            )
        return response

    def _emit_request_summary(
        self,
        endpoint: str,
        status: int,
        started: float,
        payload: dict[str, Any] | None = None,
        first_byte_at: float | None = None,
    ) -> None:
        if endpoint not in COMPLETION_PATHS:
            return
        with self._lock:
            callback = self._request_summary_callback
        if callback is None:
            return
        finished = time.monotonic()
        try:
            callback(
                _build_request_summary(
                    endpoint,
                    status,
                    payload or {},
                    started,
                    finished,
                    first_byte_at,
                )
            )
        except Exception:
            # Telemetry must never change proxy behavior.
            return


def _filtered_headers(headers: Any, excluded: set[str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.casefold() not in excluded
    }


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _merge_summary_metadata(target: dict[str, Any], data: str) -> None:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    for key in ("usage", "timings"):
        value = payload.get(key)
        if isinstance(value, dict):
            target[key] = deepcopy(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _build_request_summary(
    endpoint: str,
    status: int,
    payload: dict[str, Any],
    started: float,
    finished: float,
    first_byte_at: float | None,
) -> RequestSummary:
    usage = payload.get("usage")
    timings = payload.get("timings")
    usage = usage if isinstance(usage, dict) else {}
    timings = timings if isinstance(timings, dict) else {}

    input_tokens = _integer(usage.get("prompt_tokens"))
    generated_tokens = _integer(usage.get("completion_tokens"))
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    cached_tokens = _integer(details.get("cached_tokens"))

    cache_n = _integer(timings.get("cache_n"))
    prompt_n = _integer(timings.get("prompt_n"))
    predicted_n = _integer(timings.get("predicted_n"))
    if input_tokens is None and (cache_n is not None or prompt_n is not None):
        input_tokens = (cache_n or 0) + (prompt_n or 0)
    if generated_tokens is None:
        generated_tokens = predicted_n
    if cached_tokens is None:
        cached_tokens = cache_n

    return RequestSummary(
        endpoint=endpoint,
        status=status,
        input_tokens=input_tokens,
        generated_tokens=generated_tokens,
        cached_tokens=cached_tokens,
        prompt_ms=_number(timings.get("prompt_ms")),
        generated_ms=_number(timings.get("predicted_ms")),
        time_to_first_byte_ms=(
            max(0.0, (first_byte_at - started) * 1000)
            if first_byte_at is not None
            else None
        ),
        end_to_end_ms=max(0.0, (finished - started) * 1000),
    )
