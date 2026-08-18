"""Standalone fake OpenAI-compatible provider for local testing.

Usage: python tests/fake_provider.py [port]
Simulates real /v1/chat/completions responses with usage, supports SSE
streaming, and injects failures for models containing fail500 / fail401
/ fail429 / fail404.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8999


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        model = body.get("model", "")

        if "fail401" in model:
            self._error(401, "Invalid API key provided")
            return
        if "fail404" in model:
            self._error(404, f"The model '{model}' does not exist")
            return
        if "fail429" in model:
            self._error(429, "Rate limit reached for model")
            return
        if "fail500" in model:
            self._error(500, "The server had an error while processing your request")
            return

        prompt = body.get("messages", [{}])[-1].get("content", "")
        text = f"[REAL-{model}] echo: {prompt[:40]}"
        usage = {"prompt_tokens": 12, "completion_tokens": 17, "total_tokens": 29}

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            words = text.split(" ")
            for i, word in enumerate(words):
                chunk = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            final = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage,
            }
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return

        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            "usage": usage,
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _error(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": {"message": message}}).encode())


if __name__ == "__main__":
    print(f"fake provider listening on {PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()