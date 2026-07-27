"""Packaged smoke-test fixture that behaves like a tiny llama-server.exe."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import signal


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("-m", "--model")
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=8080)
    result.add_argument("-ngl", "--gpu-layers")
    result.add_argument("-c", "--ctx-size")
    result.add_argument("-np", "--parallel")
    result.add_argument("-fa", "--flash-attn")
    result.add_argument("--no-mmap", action="store_true")
    result.add_argument("--split-mode", choices=["none", "layer", "row"])
    result.add_argument("--metrics", action="store_true")
    result.add_argument("--slots", action="store_true")
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path == "/metrics":
            body = b"\n".join(
                [
                    b"llamacpp:prompt_tokens_total 128",
                    b"llamacpp:prompt_seconds_total 2",
                    b"llamacpp:prompt_tokens_seconds 64",
                    b"llamacpp:tokens_predicted_total 64",
                    b"llamacpp:tokens_predicted_seconds_total 4",
                    b"llamacpp:predicted_tokens_seconds 16",
                    b"llamacpp:requests_processing 1",
                    b"llamacpp:requests_deferred 0",
                ]
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/slots":
            body = json.dumps(
                [
                    {"id": 0, "is_processing": True, "n_ctx": 4096},
                    {"id": 1, "is_processing": False, "n_ctx": 4096},
                ]
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path not in {"/v1/chat/completions", "/v1/completions"}:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        is_chat = self.path == "/v1/chat/completions"
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            fragments = ("lla", "ma")
            for fragment in fragments:
                choice = (
                    {"index": 0, "delta": {"content": fragment}}
                    if is_chat
                    else {"index": 0, "text": fragment}
                )
                payload = json.dumps({"choices": [choice]}).encode()
                self.wfile.write(b"data: " + payload + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        choice = (
            {"index": 0, "message": {"role": "assistant", "content": "hello llama"}}
            if is_chat
            else {"index": 0, "text": "hello llama"}
        )
        payload = json.dumps({"choices": [choice]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    options = parser().parse_args()
    server = ThreadingHTTPServer((options.host, options.port), Handler)

    def stop(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)
    print(f"fake llama.cpp ready on {options.host}:{options.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("fake llama.cpp stopped", flush=True)


if __name__ == "__main__":
    main()
