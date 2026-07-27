from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
from typing import Any
from urllib import error, request

import pytest

from llamacpp_launcher.interceptor import (
    InterceptorServer,
    SseCompletionTransformer,
    transform_completion_json,
)
from llamacpp_launcher.models import Glossary, GlossaryEntry, ValidationError
from llamacpp_launcher.replacement import CompiledGlossary


def glossary() -> Glossary:
    return Glossary(
        name="Terms",
        entries=[
            GlossaryEntry(source="魔法", replacement="magic"),
            GlossaryEntry(source="魔法少女", replacement="magical girl"),
            GlossaryEntry(
                source="Llama", replacement="alpaca", case_sensitive=False
            ),
        ],
    )


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class UpstreamHandler(BaseHTTPRequestHandler):
    last_path = ""
    last_body = b""
    last_authorization = ""
    stream_started = threading.Event()
    stream_release = threading.Event()

    def do_GET(self) -> None:
        type(self).last_path = self.path
        if self.path.startswith("/v1/models"):
            self._send(
                b'{"object":"list","data":[{"id":"local-model","object":"model"}]}',
                200,
                "application/json",
            )
            return
        self._send(b'{"error":"not found"}', 404, "application/json")

    def do_POST(self) -> None:
        type(self).last_path = self.path
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).last_body = body
        type(self).last_authorization = self.headers.get("Authorization", "")
        payload = json.loads(body)
        if payload.get("error"):
            self._send(b'{"error":"upstream"}', 400, "application/json")
            return
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if payload.get("hang"):
                type(self).stream_started.set()
                self.wfile.write(b'data: {"choices":[{"index":0,"text":"Lla"}]}\n\n')
                self.wfile.flush()
                type(self).stream_release.wait(10)
                return
            if self.path.startswith("/v1/chat/completions"):
                events = [
                    {"id": "x", "choices": [{"index": 0, "delta": {"content": "魔"}}]},
                    {
                        "id": "x",
                        "usage": {
                            "prompt_tokens": 44,
                            "completion_tokens": 35,
                            "prompt_tokens_details": {"cached_tokens": 20},
                        },
                        "timings": {
                            "cache_n": 20,
                            "prompt_n": 24,
                            "prompt_ms": 100,
                            "predicted_n": 35,
                            "predicted_ms": 700,
                        },
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "content": "法少女",
                                    "reasoning_content": "魔法少女",
                                },
                            }
                        ],
                    },
                    {
                        "id": "x",
                        "usage": {
                            "prompt_tokens": 44,
                            "completion_tokens": 35,
                            "prompt_tokens_details": {"cached_tokens": 20},
                        },
                        "timings": {
                            "cache_n": 20,
                            "prompt_n": 24,
                            "prompt_ms": 100,
                            "predicted_n": 35,
                            "predicted_ms": 700,
                        },
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                ]
            else:
                events = [
                    {"id": "x", "choices": [{"index": 0, "text": "Lla"}]},
                    {
                        "id": "x",
                        "usage": {
                            "prompt_tokens": 44,
                            "completion_tokens": 35,
                            "prompt_tokens_details": {"cached_tokens": 20},
                        },
                        "timings": {
                            "cache_n": 20,
                            "prompt_n": 24,
                            "prompt_ms": 100,
                            "predicted_n": 35,
                            "predicted_ms": 700,
                        },
                        "choices": [
                            {"index": 0, "text": "ma", "finish_reason": "stop"}
                        ],
                    },
                ]
            for event in events:
                self.wfile.write(
                    (
                        "data: "
                        + json.dumps(event, ensure_ascii=False)
                        + "\n\n"
                    ).encode("utf-8")
                )
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        if self.path.startswith("/v1/chat/completions"):
            response: dict[str, Any] = {
                "id": "chat",
                "model": "test",
                "usage": {
                    "prompt_tokens": 44,
                    "completion_tokens": 35,
                    "total_tokens": 79,
                    "prompt_tokens_details": {"cached_tokens": 20},
                },
                "timings": {
                    "cache_n": 20,
                    "prompt_n": 24,
                    "prompt_ms": 100,
                    "predicted_n": 35,
                    "predicted_ms": 700,
                },
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "魔法少女 uses LLaMA",
                            "reasoning_content": "魔法少女",
                            "tool_calls": [{"id": "unchanged"}],
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        else:
            response = {
                "id": "completion",
                "timings": {
                    "cache_n": 10,
                    "prompt_n": 5,
                    "prompt_ms": 80,
                    "predicted_n": 12,
                    "predicted_ms": 240,
                },
                "choices": [{"text": "Llama and 魔法", "finish_reason": "stop"}],
            }
        self._send(
            json.dumps(response, ensure_ascii=False).encode("utf-8"),
            200,
            "application/json",
        )

    def _send(self, body: bytes, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


@pytest.fixture
def upstream() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(2)


@pytest.fixture
def interceptor(upstream: tuple[ThreadingHTTPServer, str]) -> tuple[InterceptorServer, str]:
    _server, base = upstream
    server = InterceptorServer()
    port = free_port()
    server.start("127.0.0.1", port, base, glossary())
    yield server, f"http://127.0.0.1:{port}"
    server.stop()


def post_json(url: str, payload: dict[str, Any]) -> tuple[int, bytes, str]:
    encoded = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get_content_type()


def test_non_streaming_chat_transforms_only_content_and_forwards_request(
    interceptor: tuple[InterceptorServer, str],
) -> None:
    _server, base = interceptor
    status, raw, content_type = post_json(
        base + "/v1/chat/completions?trace=yes", {"prompt": "unchanged"}
    )
    payload = json.loads(raw)

    assert status == 200
    assert content_type == "application/json"
    message = payload["choices"][0]["message"]
    assert message["content"] == "magical girl uses alpaca"
    assert message["reasoning_content"] == "魔法少女"
    assert message["tool_calls"] == [{"id": "unchanged"}]
    assert payload["model"] == "test"
    assert UpstreamHandler.last_path == "/v1/chat/completions?trace=yes"
    assert json.loads(UpstreamHandler.last_body) == {"prompt": "unchanged"}
    assert UpstreamHandler.last_authorization == "Bearer local"


def test_non_streaming_request_summary_uses_usage_and_timings(
    interceptor: tuple[InterceptorServer, str],
) -> None:
    server, base = interceptor
    summaries = []
    server.set_request_summary_callback(summaries.append)

    status, _, _ = post_json(base + "/v1/chat/completions", {})

    assert status == 200
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.endpoint == "/v1/chat/completions"
    assert summary.status == 200
    assert summary.input_tokens == 44
    assert summary.generated_tokens == 35
    assert summary.cached_tokens == 20
    assert summary.prompt_ms == 100
    assert summary.generated_ms == 700
    assert summary.server_compute_ms == 800
    assert summary.end_to_end_ms is not None
    assert not hasattr(summary, "content")


def test_non_streaming_completion_and_upstream_error(
    interceptor: tuple[InterceptorServer, str],
) -> None:
    _server, base = interceptor
    status, raw, _ = post_json(base + "/v1/completions", {})
    assert status == 200
    assert json.loads(raw)["choices"][0]["text"] == "alpaca and magic"

    status, raw, _ = post_json(base + "/v1/completions", {"error": True})
    assert status == 400
    assert raw == b'{"error":"upstream"}'


def test_completion_summary_falls_back_to_llama_timings_and_reports_errors(
    interceptor: tuple[InterceptorServer, str],
) -> None:
    server, base = interceptor
    summaries = []
    server.set_request_summary_callback(summaries.append)

    post_json(base + "/v1/completions", {})
    post_json(base + "/v1/completions", {"error": True})

    assert summaries[0].input_tokens == 15
    assert summaries[0].generated_tokens == 12
    assert summaries[0].cached_tokens == 10
    assert summaries[1].status == 400
    assert summaries[1].input_tokens is None


@pytest.mark.parametrize(
    ("path", "expected", "preserved"),
    [
        ("/v1/chat/completions", "magical girl", "魔法少女"),
        ("/v1/completions", "alpaca", None),
    ],
)
def test_sse_transforms_across_chunks_and_preserves_metadata(
    interceptor: tuple[InterceptorServer, str],
    path: str,
    expected: str,
    preserved: str | None,
) -> None:
    _server, base = interceptor
    status, raw, content_type = post_json(base + path, {"stream": True})
    text = raw.decode("utf-8")

    assert status == 200
    assert content_type == "text/event-stream"
    assert expected in text
    assert "data: [DONE]" in text
    if preserved is not None:
        assert f'"reasoning_content":"{preserved}"' in text


def test_streaming_summary_captures_terminal_usage_and_ttfb(
    interceptor: tuple[InterceptorServer, str],
) -> None:
    server, base = interceptor
    summaries = []
    server.set_request_summary_callback(summaries.append)

    status, _, _ = post_json(base + "/v1/completions", {"stream": True})

    assert status == 200
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.input_tokens == 44
    assert summary.generated_tokens == 35
    assert summary.cached_tokens == 20
    assert summary.time_to_first_byte_ms is not None
    assert summary.end_to_end_ms is not None
    assert summary.end_to_end_ms >= summary.time_to_first_byte_ms


def test_no_glossary_passes_through_completion(upstream: tuple[ThreadingHTTPServer, str]) -> None:
    _upstream_server, upstream_base = upstream
    server = InterceptorServer()
    port = free_port()
    server.start("127.0.0.1", port, upstream_base, None)
    try:
        status, raw, _ = post_json(
            f"http://127.0.0.1:{port}/v1/completions", {}
        )
        assert status == 200
        assert json.loads(raw)["choices"][0]["text"] == "Llama and 魔法"
    finally:
        server.stop()


def test_stop_cancels_an_active_stream(
    upstream: tuple[ThreadingHTTPServer, str],
) -> None:
    _upstream_server, upstream_base = upstream
    UpstreamHandler.stream_started.clear()
    UpstreamHandler.stream_release.clear()
    server = InterceptorServer()
    port = free_port()
    server.start("127.0.0.1", port, upstream_base, glossary())
    def consume_stream() -> None:
        try:
            post_json(
                f"http://127.0.0.1:{port}/v1/completions",
                {"stream": True, "hang": True},
            )
        except Exception:
            pass

    client = threading.Thread(
        target=consume_stream,
        daemon=True,
    )
    client.start()
    assert UpstreamHandler.stream_started.wait(2)
    started = time.monotonic()
    try:
        server.stop(timeout_seconds=2)
    finally:
        UpstreamHandler.stream_release.set()
    assert time.monotonic() - started < 2


def test_unsupported_path_gateway_failure_and_clean_port_release(
    upstream: tuple[ThreadingHTTPServer, str],
) -> None:
    _upstream_server, upstream_base = upstream
    server = InterceptorServer()
    port = free_port()
    server.start("127.0.0.1", port, upstream_base, glossary())
    status, _, _ = post_json(f"http://127.0.0.1:{port}/v1/embeddings", {})
    assert status == 404
    server.stop()

    replacement = InterceptorServer()
    replacement.start("127.0.0.1", port, "http://127.0.0.1:1", glossary())
    try:
        status, raw, _ = post_json(
            f"http://127.0.0.1:{port}/v1/completions", {}
        )
        assert status == 502
        assert b"Could not reach llama.cpp" in raw
    finally:
        replacement.stop()


def test_browser_cors_preflight_and_completion_response(
    interceptor: tuple[InterceptorServer, str],
) -> None:
    _server, base = interceptor
    UpstreamHandler.last_path = "not-forwarded"
    preflight = request.Request(
        base + "/v1/completions",
        method="OPTIONS",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    with request.urlopen(preflight, timeout=5) as response:
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert "POST" in response.headers["Access-Control-Allow-Methods"]
        assert (
            response.headers["Access-Control-Allow-Headers"]
            == "authorization, content-type"
        )
        assert response.headers.get("Access-Control-Allow-Credentials") is None
    assert UpstreamHandler.last_path == "not-forwarded"

    completion = request.Request(
        base + "/v1/completions",
        data=b"{}",
        method="POST",
        headers={
            "Origin": "http://localhost:3000",
            "Content-Type": "application/json",
        },
    )
    with request.urlopen(completion, timeout=5) as response:
        assert response.status == 200
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert response.headers.get("Access-Control-Allow-Credentials") is None

    streaming = request.Request(
        base + "/v1/completions",
        data=b'{"stream":true}',
        method="POST",
        headers={
            "Origin": "http://localhost:3000",
            "Content-Type": "application/json",
        },
    )
    with request.urlopen(streaming, timeout=5) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert b"data: [DONE]" in response.read()

    unsupported = request.Request(
        base + "/v1/embeddings",
        data=b"{}",
        method="POST",
        headers={"Origin": "http://localhost:3000"},
    )
    with pytest.raises(error.HTTPError) as failure:
        request.urlopen(unsupported, timeout=5)
    assert failure.value.code == 404
    assert failure.value.headers["Access-Control-Allow-Origin"] == "*"


def test_models_are_forwarded_unchanged_with_cors(
    interceptor: tuple[InterceptorServer, str],
) -> None:
    _server, base = interceptor
    models = request.Request(
        base + "/v1/models?source=browser",
        method="GET",
        headers={"Origin": "http://localhost:3000"},
    )
    with request.urlopen(models, timeout=5) as response:
        raw = response.read()
        assert response.status == 200
        assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert json.loads(raw) == {
        "object": "list",
        "data": [{"id": "local-model", "object": "model"}],
    }
    assert UpstreamHandler.last_path == "/v1/models?source=browser"


def test_bind_failure_is_reported(upstream: tuple[ThreadingHTTPServer, str]) -> None:
    _server, base = upstream
    first = InterceptorServer()
    second = InterceptorServer()
    port = free_port()
    first.start("127.0.0.1", port, base, glossary())
    try:
        with pytest.raises(ValidationError, match="Could not start"):
            second.start("127.0.0.1", port, base, glossary())
    finally:
        first.stop()


def test_transform_helpers_preserve_reasoning_and_flush_done() -> None:
    compiled = CompiledGlossary.from_glossary(glossary())
    payload = {
        "choices": [
            {
                "message": {
                    "content": "魔法",
                    "reasoning_content": "魔法",
                }
            }
        ]
    }
    transformed = transform_completion_json(payload, "/v1/chat/completions", compiled)
    assert transformed["choices"][0]["message"]["content"] == "magic"
    assert transformed["choices"][0]["message"]["reasoning_content"] == "魔法"

    stream = SseCompletionTransformer("/v1/completions", compiled)
    first = stream.transform_data('{"choices":[{"index":0,"text":"Lla"}]}')
    second = stream.transform_data('{"choices":[{"index":0,"text":"ma"}]}')
    done = stream.transform_data("[DONE]")
    assert '"text":""' in first[0]
    assert "alpaca" in second[0]
    assert done[-1] == "[DONE]"
