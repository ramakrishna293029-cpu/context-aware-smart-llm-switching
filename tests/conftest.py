"""Pytest configuration and shared fixtures for offline API testing."""

import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from tests.fake_provider import FakeProviderHandler

TEST_PORT = 8999
# Fully isolated in-memory database: tests can never pollute or read the live
# data/metrics.db. Tracker keeps one shared connection for :memory: DBs.
TEST_DB = ":memory:"


@pytest.fixture(scope="session", autouse=True)
def isolate_database():
    """Forces in-memory database globally across all test files."""
    from app.config import settings
    import app.tracker
    import app.main
    import app.analyzer_llm

    object.__setattr__(settings, "database_path", TEST_DB)
    app.tracker.tracker = app.tracker.Tracker(TEST_DB)
    app.main.tracker = app.tracker.tracker
    import app.pipeline
    app.pipeline.tracker = app.tracker.tracker
    app.analyzer_llm.clear_routing_cache()
    yield
    # Post-session check: ensure data/metrics.db has no test leakage
    live_db = ROOT_DIR / "data" / "metrics.db"
    if live_db.exists():
        import sqlite3
        with sqlite3.connect(str(live_db)) as conn:
            cnt = conn.execute("SELECT count(*) FROM requests WHERE query LIKE 'Adversarial%'").fetchone()[0]
            assert cnt == 0, f"Database leak detected: {cnt} test queries in live data/metrics.db!"


@pytest.fixture(scope="session", autouse=True)
def fake_server():
    """Starts the deterministic fake HTTP provider in a background thread."""
    server = ThreadingHTTPServer(("127.0.0.1", TEST_PORT), FakeProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


@pytest.fixture(scope="session")
def client(fake_server):
    """Configures test settings, isolates DB, and returns a FastAPI TestClient."""
    from app.config import settings
    from app.registry import ModelRegistry
    import app.registry
    import app.main
    import app.tracker

    # Fully isolated in-memory database — nothing touches data/metrics.db.
    object.__setattr__(settings, "database_path", TEST_DB)
    app.tracker.tracker = app.tracker.Tracker(TEST_DB)
    app.main.tracker = app.tracker.tracker
    import app.pipeline
    app.pipeline.tracker = app.tracker.tracker
    app.analyzer_llm.clear_routing_cache()

    # Configure offline provider endpoints pointing to fake server
    object.__setattr__(settings, "openai_api_key", "test-openai-key")
    object.__setattr__(settings, "openai_base_url", f"http://127.0.0.1:{TEST_PORT}/v1")
    object.__setattr__(settings, "openai_model", "gpt-4o-mini")

    object.__setattr__(settings, "groq_api_key", "test-groq-key")
    object.__setattr__(settings, "groq_base_url", f"http://127.0.0.1:{TEST_PORT}/v1")
    object.__setattr__(settings, "groq_coding_model", "fake-groq-coding")
    object.__setattr__(settings, "groq_reasoning_model", "fake-groq-reasoning")

    object.__setattr__(settings, "openrouter_api_key", "")
    object.__setattr__(settings, "gemini_api_key", "")
    object.__setattr__(settings, "custom_base_url", "")
    object.__setattr__(settings, "analyzer_model", "auto")

    object.__setattr__(settings, "daily_budget_usd", 0.0)
    object.__setattr__(settings, "max_cost_per_request", 0.0)

    # Initialize dynamic test registry
    test_reg = ModelRegistry.from_settings(settings)
    app.registry.registry = test_reg
    app.main.default_registry = test_reg

    with TestClient(app.main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset rate limiting, budgets, circuits, and caches between individual test runs."""
    from app.config import settings
    import app.main
    import app.circuit
    import app.analyzer_llm
    import app.pipeline

    object.__setattr__(settings, "daily_budget_usd", 0.0)
    object.__setattr__(settings, "max_cost_per_request", 0.0)
    app.main._rate_hits.clear()
    app.circuit.circuits.reset()
    app.analyzer_llm.clear_routing_cache()
    app.pipeline.clear_completion_cache()
    yield
    object.__setattr__(settings, "daily_budget_usd", 0.0)
    object.__setattr__(settings, "max_cost_per_request", 0.0)
    app.main._rate_hits.clear()
    app.circuit.circuits.reset()
    app.analyzer_llm.clear_routing_cache()
    app.pipeline.clear_completion_cache()
