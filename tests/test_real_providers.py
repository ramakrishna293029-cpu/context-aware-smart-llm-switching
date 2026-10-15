"""Integration test: real-provider flow against a fake OpenAI-compatible server.

The fake server plays both roles:
  * analyzer calls (prompt contains "ROUTING ANALYZER") return a structured
    JSON decision (self for simple queries, switch to openai-powerful for
    complex ones);
  * final answer calls echo [REAL-<model>] with real usage.

Run from the project root:
    python tests/test_real_providers.py              # normal flow
    python tests/test_real_providers.py fallback     # target fails -> fallback
"""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_PATH"] = ":memory:"  # isolate this script from live data/metrics.db

PORT = 8999
FALLBACK_MODE = len(sys.argv) > 1 and sys.argv[1] == "fallback"

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"
os.environ["OPENAI_FAST_MODEL"] = "fake-mini"
os.environ["OPENAI_POWERFUL_MODEL"] = "fake-max-fail500" if FALLBACK_MODE else "fake-max"
os.environ["GROQ_API_KEY"] = "groq-test-key"
os.environ["GROQ_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"
os.environ["GROQ_FAST_MODEL"] = "fake-groq-fast"
os.environ["GROQ_POWERFUL_MODEL"] = "fake-groq-max"
os.environ["GROQ_TIER2_MODEL"] = "fake-groq-t2-fail500" if FALLBACK_MODE else "fake-groq-t2"
os.environ["OPENROUTER_API_KEY"] = ""  # keep .env real providers out of this test
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_ANALYZER_API_KEY"] = ""
os.environ["GEMINI_TIER1_API_KEY"] = ""
os.environ["GEMINI_TIER3_API_KEY"] = ""
os.environ["GEMINI_TIER6_API_KEY"] = ""
os.environ["GROQ_TIER2_API_KEY"] = ""
os.environ["GROQ_TIER4_API_KEY"] = ""
os.environ["GROQ_TIER5_API_KEY"] = ""
os.environ.pop("ANALYZER_MODEL", None)

COMPLEX_MARKERS = ("distributed database", "re-renders infinitely", "Prove that")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        model = body.get("model", "")
        messages = body.get("messages", [])
        all_content = " ".join(m.get("content", "") for m in messages)
        prompt = all_content
        usage = {"prompt_tokens": 12, "completion_tokens": 17, "total_tokens": 29}

        is_analyzer = (
            any(k in prompt.upper() for k in ("ROUTING ANALYZER", "ANALYZER LLM", "ANALYZER", "DECISION CRITERIA", "BOX 3"))
            or "analyzer" in model.lower()
            or body.get("response_format", {}).get("type") == "json_object"
        )

        if "fail500" in model and not is_analyzer:
            self._error(500, "simulated outage")
            return

        if is_analyzer:
            user_query = ""
            for m in messages:
                if m.get("role") == "user":
                    user_query += " " + m.get("content", "")
            if not user_query:
                user_query = prompt
            complex_ = any(m.lower() in user_query.lower() for m in COMPLEX_MARKERS)
            if complex_:
                text = json.dumps({
                    "answer_mode": "switch",
                    "context_relevant": False,
                    "reason": "Needs stronger reasoning and coding capability.",
                    "target_model": None,
                    "task_type": "technical",
                    "complexity": 0.85,
                    "answer": None,
                })
            else:
                text = json.dumps({
                    "answer_mode": "self",
                    "context_relevant": False,
                    "reason": "I can answer this accurately myself.",
                    "target_model": None,
                    "task_type": "factual",
                    "complexity": 0.15,
                    "answer": f"[REAL-analyzer] echo: {user_query.strip()[:40]}",
                })
        else:
            text = f"[REAL-{model}] solution analysis: {prompt[:40]} completed with verified derivation and steps."

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


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def main():
    from app.main import chat
    from app.registry import registry
    from app.schemas import ChatRequest

    print("registered:", [(m.model_id, m.provider, m.mode, m.endpoint_model) for m in registry.available()])
    assert registry.has_real(), "real models should be registered"

    simple = "What is HTML?"
    complex = "Debug this: my React component re-renders infinitely"

    from starlette.requests import Request
    mock_request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})

    r = await chat(ChatRequest(query=simple), request=mock_request)
    print(f"  '{simple[:45]}' -> self by {r.model.model_id} cost=${r.estimated_cost_usd:.6f} "
          f"analyzer_tokens={r.analyzer.input_tokens}/{r.analyzer.output_tokens} "
          f"total_tokens={r.total_tokens} lat={r.analyzer_latency_ms:.0f}ms")
    assert r.model.mode == "real", "mode must be real"
    assert r.answer_mode == "self", "simple query must be self-answered"
    assert "[REAL-analyzer]" in r.response, "answer must come from the analyzer (real provider)"
    assert r.input_tokens is None and r.output_tokens is None, "no separate final call on self"
    assert r.analyzer.input_tokens == 12 and r.analyzer.output_tokens == 17
    assert r.total_tokens == 29
    assert r.analyzer_cost_usd > 0 and r.estimated_cost_usd == r.analyzer_cost_usd

    r = await chat(ChatRequest(query=complex), request=mock_request)
    print(f"  '{complex[:45]}' -> {r.model.model_id} cost=${r.estimated_cost_usd:.6f} "
          f"tokens={r.input_tokens}/{r.output_tokens} lat={r.latency_ms:.0f}ms "
          f"switch={r.answer_mode} reason={r.switch_reason!r}")
    assert r.answer_mode == "switch", "complex query must switch to the powerful model"
    assert r.switch_reason
    assert r.analyzer.reason
    if FALLBACK_MODE:
        assert r.fallback_used, "primary tier fails with 500, fallback must kick in"
        assert r.model.tier in ["tier_2", "tier_4", "tier_5"]
        assert r.model.model_id != "groq-tier_2"
        assert "[REAL-" in r.response and "fail500" not in r.response
        print(f"  fallback verified: '{complex[:40]}' -> served by {r.model.model_id}")
        print("  ALL queries served by a real provider (fallback chain working)")
    else:
        assert r.model.tier in ["tier_2", "tier_4", "tier_5"]
        assert r.model.model_id == "groq-tier_2"
        assert "[REAL-" in r.response
        assert r.input_tokens == 12 and r.output_tokens == 17

    print("\nALL REAL-PROVIDER TESTS PASSED")


if __name__ == "__main__":
    server = start_server()
    try:
        asyncio.run(main())
    finally:
        server.shutdown()