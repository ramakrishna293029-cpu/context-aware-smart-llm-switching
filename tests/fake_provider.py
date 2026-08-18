"""Standalone fake OpenAI-compatible provider for local testing and CI/CD.

Usage: python tests/fake_provider.py [port]
Simulates real /v1/chat/completions responses with usage, supports SSE
streaming, reasoning tokens, and injects failures for models containing
fail500 / fail401 / fail429 / fail404 or prompt markers.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _parse_port() -> int:
    if len(sys.argv) > 1:
        try:
            return int(sys.argv[1])
        except ValueError:
            pass
    return 8999


PORT = _parse_port()

COMPLEX_MARKERS = (
    "distributed database", "square root of 2", "prove that",
    "optimize", "architecture", "debug", "react", "algorithm",
    "binary search", "python", "quicksort", "dijkstra", "system design",
    "distributed", "raft", "docker", "kubernetes", "c++", "traceback",
    "typeerror", "sql", "consensus", "linked list",
)


class FakeProviderHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "message": "Fake Provider Online"}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        model = body.get("model", "")
        messages = body.get("messages", [])
        all_content = " ".join(m.get("content", "") for m in messages)
        prompt = all_content
        usage = {"prompt_tokens": 12, "completion_tokens": 17, "total_tokens": 29}

        # Error injections by model name
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

        # Check if this is an Analyzer call
        is_analyzer = any(
            k in prompt for k in ("ANALYZER", "ROUTING", "INTELLIGENT QUERY ANALYZER", "DECISION CRITERIA")
        ) or body.get("response_format", {}).get("type") == "json_object" or "analyzer" in model.lower()

        if is_analyzer:
            if "FAIL-ANALYZER" in prompt:
                self._error(500, "Analyzer outage")
                return

            # Extract user query
            user_query = ""
            for m in messages:
                if m.get("role") == "user":
                    user_query += " " + m.get("content", "")
            if not user_query:
                user_query = prompt

            q_lower = user_query.lower()
            complex_ = any(m in q_lower for m in COMPLEX_MARKERS)
            has_history = "CONVERSATION HISTORY:" in prompt or "\nuser: " in prompt.lower()

            if complex_:
                decision = {
                    "answer_mode": "switch",
                    "task_type": "coding" if any(k in q_lower for k in ("code", "python", "react", "binary search", "debug", "algorithm")) else "reasoning",
                    "complexity": "high",
                    "complexity_score": 0.85,
                    "reasoning_required": True,
                    "coding_required": any(k in q_lower for k in ("code", "python", "react", "binary search", "debug", "algorithm")),
                    "context_required": has_history,
                    "target_tier": "coding" if any(k in q_lower for k in ("code", "python", "react", "binary search", "debug", "algorithm")) else "reasoning",
                    "target_provider": "openai",
                    "target_model": "openai-powerful",
                    "reason": "Complex technical query requires specialized model capabilities.",
                    "answer": None,
                }
            else:
                decision = {
                    "answer_mode": "self",
                    "task_type": "factual",
                    "complexity": "low",
                    "complexity_score": 0.15,
                    "reasoning_required": False,
                    "coding_required": False,
                    "context_required": has_history,
                    "target_tier": "fast",
                    "target_provider": "openai",
                    "target_model": None,
                    "reason": "Simple query answered directly by base model in self-mode.",
                    "answer": f"[REAL-analyzer] echo: {user_query.strip()[:40]}",
                }
            text = json.dumps(decision)
            reasoning_text = None
        else:
            # Final model response
            if "FALLBACK-DEMAND" in prompt:
                # Primary reasoning/powerful models fail, allowing fallback to succeed on coding/fast models
                if any(m in model.lower() for m in ("o3-mini", "fake-groq-reasoning", "gpt-4o", "fake-max", "openai-powerful")):
                    self._error(500, "Simulated primary outage for fallback test")
                    return

            text = f"[REAL-{model}] echo: {prompt[:40]}"
            reasoning_text = "Analyzing constraints and optimal implementation strategy..." if any(k in prompt.lower() for k in ("prove", "reason", "irrational", "r1")) else None

        # Streaming response
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            if reasoning_text:
                chunk = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"reasoning_content": reasoning_text + " "}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())

            for word in text.split(" "):
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

        # Unary response
        msg_payload = {"role": "assistant", "content": text}
        if reasoning_text:
            msg_payload["reasoning_content"] = reasoning_text

        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": msg_payload}],
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
        self.wfile.write(json.dumps({"error": {"message": message, "code": code}}).encode())


if __name__ == "__main__":
    print(f"Fake Provider listening on port {PORT}")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), FakeProviderHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()