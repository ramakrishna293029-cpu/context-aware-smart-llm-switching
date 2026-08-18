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
TEST_DB = ROOT_DIR / "data" / "test-metrics.db"


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

    # Point test database to isolated file
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB.exists():
        try:
            TEST_DB.unlink()
        except Exception:
            pass

    object.__setattr__(settings, "database_path", TEST_DB)
    app.tracker.tracker = app.tracker.Tracker(TEST_DB)
    app.main.tracker = app.tracker.tracker

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
    """Reset rate limiting and budgets between individual test runs."""
    from app.config import settings
    import app.main

    object.__setattr__(settings, "daily_budget_usd", 0.0)
    object.__setattr__(settings, "max_cost_per_request", 0.0)
    app.main._rate_hits.clear()
    yield
    object.__setattr__(settings, "daily_budget_usd", 0.0)
    object.__setattr__(settings, "max_cost_per_request", 0.0)
    app.main._rate_hits.clear()
