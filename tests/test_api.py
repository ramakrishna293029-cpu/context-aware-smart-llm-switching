"""pytest suite: API surface of the Smart LLM Router (analyzer-LLM-first).

Every request goes USER -> ANALYZER LLM -> DECISION (self|switch) -> REAL
answer. The fake provider below plays BOTH roles deterministically:

  * any call whose prompt contains "ROUTING ANALYZER" is the analyzer call
    -> returns a structured JSON decision (self for simple queries, switch
       to openai-powerful for complex ones, 500 on FAIL-ANALYZER)
  * any other call is the FINAL answer model -> echoes [REAL-<model>]

Covers /api/analyze, /api/chat, /api/chat/stream (SSE), /api/requests/{id},
/api/stats, /api/feedback, budget enforcement, fallback and validation.

Run from the project root:  python -m pytest tests/test_api.py -v
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PORT = 8999

os.environ["DATABASE_PATH"] = os.path.join(ROOT, "data", "test-metrics.db")  # isolate tests from the live DB

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"
os.environ["OPENAI_FAST_MODEL"] = "fake-mini"
os.environ["OPENAI_POWERFUL_MODEL"] = "fake-max"
os.environ["GROQ_API_KEY"] = "groq-test-key"
os.environ["GROQ_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"
os.environ["GROQ_FAST_MODEL"] = "fake-groq-fast"
os.environ["GROQ_POWERFUL_MODEL"] = "fake-groq-max"
os.environ["OPENROUTER_API_KEY"] = ""  # disable real OpenRouter from .env (tests stay local)
os.environ["GOOGLE_API_KEY"] = ""      # disable real Google from .env (tests stay local)
os.environ.setdefault("MAX_COST_PER_REQUEST", "0")
os.environ.setdefault("DAILY_BUDGET_USD", "0")
os.environ.setdefault("MONTHLY_BUDGET_USD", "0")
os.environ.pop("ANALYZER_MODEL", None)  # "auto" -> cheapest available real

COMPLEX_MARKERS = ("distributed database", "square root of 2", "Prove that",
                   "optimize", "architecture", "debug")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        model = body.get("model", "")
        all_content = " ".join(m.get("content", "") for m in body.get("messages", []))
        prompt = all_content
        usage = {"prompt_tokens": 12, "completion_tokens": 17, "total_tokens": 29}

        if "fail500" in model:
            self._error(500, "simulated outage")
            return

        is_analyzer = "ROUTING ANALYZER" in prompt

        if is_analyzer:
            if "FAIL-ANALYZER" in prompt:
                self._error(500, "analyzer outage")
                return
            query = prompt.split("USER MESSAGE: ", 1)[1] if "USER MESSAGE: " in prompt else ""
            complex_ = any(m in query for m in COMPLEX_MARKERS)
            has_history = "\nuser: " in prompt
            if complex_:
                decision = {
                    "answer_mode": "switch",
                    "context_relevant": has_history,
                    "reason": "This needs stronger reasoning and coding capability.",
                    "target_model": "openai-powerful",
                    "task_type": "technical",
                    "complexity": 0.85,
                    "answer": None,
                }
            else:
                decision = {
                    "answer_mode": "self",
                    "context_relevant": has_history,
                    "reason": "I can answer this accurately myself.",
                    "target_model": None,
                    "task_type": "factual",
                    "complexity": 0.15,
                    "answer": f"[REAL-analyzer] echo: {query[:40]}",
                }
            text = json.dumps(decision)
        else:
            if "FALLBACK-DEMAND" in prompt and "fake-max" in model:
                self._error(500, "simulated final-model outage")
                return
            text = f"[REAL-{model}] echo: {prompt[:40]}"

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for word in text.split(" "):
                chunk = {"choices": [{"index": 0, "delta": {"content": word + " "}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            final = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return

        payload = {
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


@pytest.fixture(scope="session", autouse=True)
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


@pytest.fixture(scope="session")
def client():
    from app.config import settings
    from app.registry import ModelRegistry
    import app.registry
    import app.main
    import app.analyzer_llm

    object.__setattr__(settings, "google_api_key", "")
    object.__setattr__(settings, "openai_api_key", "test-key")
    object.__setattr__(settings, "openai_base_url", f"http://127.0.0.1:{PORT}/v1")
    object.__setattr__(settings, "openai_fast_model", "fake-mini")
    object.__setattr__(settings, "openai_powerful_model", "fake-max")
    object.__setattr__(settings, "groq_api_key", "groq-test-key")
    object.__setattr__(settings, "groq_base_url", f"http://127.0.0.1:{PORT}/v1")
    object.__setattr__(settings, "groq_fast_model", "fake-groq-fast")
    object.__setattr__(settings, "groq_powerful_model", "fake-groq-max")
    object.__setattr__(settings, "openrouter_api_key", "")
    object.__setattr__(settings, "analyzer_model", "auto")

    test_reg = ModelRegistry.from_settings()
    app.registry.registry = test_reg
    app.main.registry = test_reg

    from fastapi.testclient import TestClient
    with TestClient(app.main.app) as c:
        yield c


def _chat(client, query, **extra):
    resp = client.post("/api/chat", json={"query": query, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(client, query, **extra):
    events = []
    with client.stream("POST", "/api/chat/stream", json={"query": query, **extra}) as resp:
        assert resp.status_code == 200, resp.read()
        for raw in resp.iter_lines():
            if raw.startswith("data:"):
                events.append(json.loads(raw[5:]))
    return events


def _set(settings, name, value):
    object.__setattr__(settings, name, value)


SIMPLE = "What is HTML?"
COMPLEX = "Design a fault-tolerant distributed database for millions of users"


class TestAnalyze:
    def test_simple_self_decision(self, client):
        r = client.post("/api/analyze", json={"query": SIMPLE}).json()
        assert r["analyzer"]["answer_mode"] == "self"
        assert r["analyzer"]["model_id"].endswith("fast")  # cheapest real analyzer
        assert r["analyzer"]["complexity"] <= 0.5
        assert r["analyzer"]["reason"]
        assert r["candidates"]

    def test_complex_switch_decision(self, client):
        r = client.post("/api/analyze", json={"query": COMPLEX}).json()
        assert r["analyzer"]["answer_mode"] == "switch"
        assert r["analyzer"]["target_model"] == "openai-powerful"
        assert r["analyzer"]["complexity"] > 0.6

    def test_requires_query(self, client):
        assert client.post("/api/analyze", json={}).status_code == 422


class TestChat:
    def test_simple_is_self_answered(self, client):
        data = _chat(client, SIMPLE)
        assert data["answer_mode"] == "self"
        assert data["context_relevant"] is False
        assert data["switch_reason"] is None
        assert data["model"]["model_id"] == data["analyzer"]["model_id"]  # no switch
        assert data["model"]["mode"] == "real"
        assert data["model"]["reason"]
        assert data["model"]["candidates"]
        assert data["model"]["scores"]["total"] > 0
        assert data["response"].startswith("[REAL-analyzer]")
        assert data["input_tokens"] is None and data["output_tokens"] is None  # no separate final call
        assert data["analyzer"]["input_tokens"] == 12
        assert data["usage_source"] == "provider"
        assert data["estimated_cost_usd"] == data["analyzer_cost_usd"] > 0
        assert data["total_tokens"] == 29
        assert data["request_id"]

    def test_complex_switches_to_powerful(self, client):
        data = _chat(client, COMPLEX)
        assert data["answer_mode"] == "switch"
        assert data["switch_reason"]
        assert data["analyzer"]["target_model"] == "openai-powerful"
        assert data["model"]["model_id"] == "openai-powerful"
        assert data["model"]["analysis"]["task_type"] == "technical"
        assert data["response"].startswith("[REAL-fake-max]")

    def test_strategy_propagates(self, client):
        data = _chat(client, COMPLEX, strategy="lowest_cost")
        assert data["model"]["strategy"] == "lowest_cost"
        assert data["analyzer"]["model_id"]

    def test_invalid_strategy_422(self, client):
        assert client.post("/api/chat", json={"query": "hi", "strategy": "bogus"}).status_code == 422

    def test_history_followup_uses_context(self, client):
        h = [
            {"role": "user", "content": "Explain binary search."},
            {"role": "assistant", "content": "Binary search is a divide and conquer algorithm."},
        ]
        data = _chat(client, "Now optimize it", history=h)
        assert data["context_relevant"] is True
        assert data["answer_mode"] == "switch"
        assert data["model"]["model_id"] == "openai-powerful"

    def test_analyzer_failure_502(self, client):
        r = client.post("/api/chat", json={"query": "FAIL-ANALYZER break everything"})
        assert r.status_code == 502
        assert "Analyzer" in r.json()["detail"]

    def test_final_failure_falls_back(self, client):
        # The analyzer targets openai-powerful (fake-max), the final call fails,
        # the fallback chain must recover on another real model.
        data = _chat(client, f"FALLBACK-DEMAND {COMPLEX}")
        assert data["success"] is True
        assert data["fallback_used"] is True
        assert data["model"]["model_id"] != "openai-powerful"
        assert data["response"].startswith("[REAL-fake-")


class TestStream:
    def test_stream_self_events(self, client):
        events = _events(client, SIMPLE)
        kinds = [e["event"] for e in events]
        assert "analyzer" in kinds
        assert "delta" in kinds
        assert "done" in kinds
        assert "routing" not in kinds
        analyzer = [e for e in events if e["event"] == "analyzer"][0]
        assert analyzer["info"]["answer_mode"] == "self"
        done = [e for e in events if e["event"] == "done"][0]
        assert done["success"] is True
        assert done["request_id"]
        assert done["input_tokens"] is None
        assert done["total_tokens"] == 29
        text = "".join(e["text"] for e in events if e["event"] == "delta")
        assert text.startswith("[REAL-analyzer]")

    def test_stream_switch_events(self, client):
        events = _events(client, COMPLEX)
        kinds = [e["event"] for e in events]
        assert "analyzer" in kinds
        assert "routing" in kinds
        assert "delta" in kinds
        assert "done" in kinds
        routing = [e for e in events if e["event"] == "routing"][0]
        assert routing["answer_mode"] == "switch"
        assert routing["reason"]
        done = [e for e in events if e["event"] == "done"][0]
        assert done["success"] is True
        assert done["model"]["model_id"] == "openai-powerful"
        text = "".join(e["text"] for e in events if e["event"] == "delta")
        assert "[REAL-fake-max]" in text

    def test_stream_analyzer_error(self, client):
        events = _events(client, "FAIL-ANALYZER break everything")
        assert [e["event"] for e in events] == ["error"]
        assert "Analyzer" in events[0]["detail"]

    def test_stream_fallback(self, client):
        events = _events(client, f"FALLBACK-DEMAND {COMPLEX}")
        done = [e for e in events if e["event"] == "done"][0]
        assert done["success"] is True
        assert done["fallback_used"] is True
        text = "".join(e["text"] for e in events if e["event"] == "delta")
        assert "[REAL-fake-" in text


class TestInspector:
    def test_request_detail(self, client):
        data = _chat(client, SIMPLE)
        rid = data["request_id"]
        r = client.get(f"/api/requests/{rid}")
        assert r.status_code == 200
        d = r.json()
        assert d["query"] == SIMPLE
        assert d["task_type"] == "factual"
        assert d["routed_model"] == d["selected_model"]
        assert d["answer_mode"] == "self"
        assert d["analyzer_model"] == d["selected_model"]
        assert d["analyzer_latency_ms"] >= 0
        assert d["analyzer_input_tokens"] == 12
        assert d["analyzer_output_tokens"] == 17
        assert d["input_tokens"] is None
        assert d["total_tokens"] == 29
        assert d["candidates"]
        assert d["latency_ms"] >= 0

    def test_unknown_request_404(self, client):
        assert client.get("/api/requests/999999").status_code == 404

    def test_feedback(self, client):
        data = _chat(client, SIMPLE)
        r = client.post("/api/feedback", json={"request_id": data["request_id"], "rating": 1})
        assert r.status_code == 200
        detail = client.get(f"/api/requests/{data['request_id']}").json()
        assert detail["feedback"] == 1

    def test_feedback_validation(self, client):
        assert client.post("/api/feedback", json={"request_id": 1, "rating": 5}).status_code == 422


class TestStats:
    def test_stats_shape(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        s = r.json()
        for key in ("total_requests", "success_rate", "average_latency_ms",
                    "average_total_latency_ms", "total_cost_usd", "total_tokens",
                    "baseline_cost_usd", "savings_percent",
                    "self_answered", "switched", "switch_rate", "context_used",
                    "model_distribution", "analyzer_distribution", "decision_distribution",
                    "recent_requests", "model_performance", "distributions", "budget"):
            assert key in s, key
        assert s["distributions"]["complexity_distribution"]
        assert s["budget"]["day_spend"] >= 0

    def test_history(self, client):
        r = client.get("/api/history")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        if r.json():
            assert "answer_mode" in r.json()[0]

    def test_models(self, client):
        r = client.get("/api/models")
        assert r.status_code == 200
        assert all(m["mode"] in ("real", "demo") for m in r.json()["models"])


class TestBudgets:
    def test_daily_budget_429(self, client):
        from app.main import settings
        _set(settings, "daily_budget_usd", 0.000001)
        try:
            r = client.post("/api/chat", json={"query": SIMPLE})
            assert r.status_code == 429
            assert "budget" in r.json()["detail"].lower()
        finally:
            _set(settings, "daily_budget_usd", 0.0)

    def test_max_cost_per_request_filters_target(self, client):
        from app.main import settings
        # Cap $0.0010: the powerful tier (~$0.0015/1K) is filtered out,
        # so a switch request must land on a cheap fast-tier model.
        _set(settings, "max_cost_per_request", 0.0010)
        try:
            r = _chat(client, COMPLEX)
            assert r["answer_mode"] == "switch"
            assert r["model"]["model_id"].endswith("fast")
        finally:
            _set(settings, "max_cost_per_request", 0.0)

    def test_max_cost_below_all_models_429(self, client):
        from app.main import settings
        _set(settings, "max_cost_per_request", 0.00001)
        try:
            r = client.post("/api/chat", json={"query": COMPLEX})
            assert r.status_code == 429
            assert "budget" in r.json()["detail"].lower()
        finally:
            _set(settings, "max_cost_per_request", 0.0)


class TestGuards:
    def test_invalid_json_400(self, client):
        r = client.post("/api/chat", content=b"{not json", headers={"Content-Type": "application/json"})
        assert r.status_code in (400, 422)

    def test_rate_limit_429(self, client):
        from app.main import _rate_hits, _RATE_MAX
        import time
        _rate_hits["testclient"] = [time.monotonic()] * _RATE_MAX
        try:
            r = client.post("/api/chat", json={"query": SIMPLE})
            assert r.status_code == 429
        finally:
            _rate_hits["testclient"] = []

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["architecture"] == "analyzer-llm"