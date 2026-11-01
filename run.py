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
    |-- pipeline.py      : Fallback Orchestrator & Completion Cache
    |-- linucb.py        : Disjoint LinUCB Contextual Bandit Router
    |-- features.py      : 16-D TF-IDF + TruncatedSVD Feature Extractor
    |-- eligibility.py   : MCDA Hard Eligibility & SLA Filter
    |-- circuit.py       : Multi-Tier Resilient Circuit Breakers
    |-- reward.py        : AST & Arithmetic Verifier + Reward Engine
    |-- context.py       : Conversation History & Context Trimming
    |-- registry.py      : 6-Tier Model Specifications & Registry
    |-- schemas.py       : Pydantic Validation & Telemetry Models
    |-- security.py      : Dynamic API Key & Custom Endpoint Resolver
    |-- tracker.py       : SQLite Telemetry, Budgets & Bandit Persistence
    |-- config.py        : Global Environment & Parameter Settings
    \\-- adapters/        : Native Provider Adapters (Gemini, Groq, OpenAI, Mock)

  [ FRONTEND STUDIO ] -> static/
    |-- index.html       : Responsive Single-Page Application (SPA)
    |-- style.css        : Modern Glassmorphic Obsidian Design System
    |-- app.js           : Real-Time SSE Stream Consumer & State Store
    \\-- vendor/          : KaTeX Mathematics, Marked Parser, DOMPurify

  [ TEST & QA SUITE ] -> tests/
    |-- test_stage2_corrections.py : Regression Tests for Stage-2 Corrections
    |-- test_6tiers.py             : 6-Tier Model Mapping & Resolution
    |-- test_linucb.py             : LinUCB Mathematical & Persistence Tests
    |-- test_linucb_e2e.py         : End-to-End Bandit Routing Tests
    |-- test_eligibility.py        : MCDA Hard Eligibility Filter Tests
    |-- test_features.py           : 16-D Feature Extraction Tests
    |-- test_reward.py             : Quality & Syntax Verification Tests
    |-- test_circuit.py            : Circuit Breaker State Transition Tests
    \\-- test_api.py                : Full API & Streaming Endpoint Tests

  [ PERSISTENT STORAGE ] -> data/
    \\-- metrics.db       : Operational Telemetry & LinUCB Parameters
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
