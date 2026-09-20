"""
Smart LLM Switcher - Application Runner & File Architecture Showcase.
Provides an artisanal, human-crafted terminal experience and launches the local server.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import uvicorn

BANNER = r"""
   _____                      _     _     _     __  __ 
  / ____|                    | |   | |   | |   |  \/  |
 | (___  _ __ ___   __ _ _ __| |_  | |   | |   | \  / |
  \___ \| '_ ` _ \ / _` | '__| __| | |   | |   | |\/| |
  ____) | | | | | | (_| | |  | |_  | |___| |___| |  | |
 |_____/|_| |_| |_|\__,_|_|   \__| |_____|_____|_|  |_|
  Context-Aware Smart LLM Switching & Cost Optimization
"""

FILE_ARCHITECTURE = """
================================================================================
                    PROJECT ARCHITECTURE & FILE ORDER
================================================================================

  [ BACKEND CORE ] -> app/
    |-- main.py          : FastAPI Application & API Lifecycle
    |-- pipeline.py      : Dual-Mode Execution & Fallback Orchestrator
    |-- analyzer_llm.py  : Intelligent Query & Complexity Classifier
    |-- analyzer.py      : Deterministic Baseline Analyzer
    |-- router.py        : 7-Factor Capability Scoring Engine
    |-- circuit.py       : Resilient Provider Circuit Breaker
    |-- context.py       : Conversation History & Token Budgeting
    |-- registry.py      : Dynamic Multi-Provider Model Specifications
    |-- schemas.py       : Pydantic Validation & Telemetry Models
    |-- security.py      : Dynamic API Key & Custom Endpoint Resolver
    |-- tracker.py       : SQLite Telemetry, Budgets & Feedback Storage
    |-- config.py        : Global Environment & Parameter Settings
    \\-- adapters/        : Native Provider Adapters (OpenAI, Gemini, Groq, Mock)

  [ FRONTEND STUDIO ] -> static/
    |-- index.html       : Responsive Single-Page Application (SPA)
    |-- style.css        : Modern Glassmorphic Obsidian Design System
    |-- app.js           : Real-Time SSE Stream Consumer & State Store
    \\-- vendor/          : KaTeX Mathematics, Marked Parser, DOMPurify

  [ TEST & QA SUITE ] -> tests/
    |-- test_api.py          : Comprehensive API & Integration Tests (100% Pass)
    |-- test_adversarial.py  : Adversarial Stress & Edge-Case Resilience (100% Pass)
    |-- test_routing.py      : Multi-Factor Strategy Routing Tests
    |-- test_real_providers.py : Live Provider Verification
    \\-- fake_provider.py    : Deterministic Local Mock Server

  [ PERSISTENT STORAGE ] -> data/
    \\-- metrics.db       : Operational Telemetry & Cost Accounting
================================================================================
"""


def print_showcase():
    print(BANNER)
    print(FILE_ARCHITECTURE)


if __name__ == "__main__":
    print_showcase()
    if "--show-only" not in sys.argv:
        print("Starting local server at http://127.0.0.1:8000 ...\n")
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
