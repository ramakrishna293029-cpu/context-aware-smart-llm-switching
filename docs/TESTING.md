# Testing & Quality Assurance Guide

## Context-Aware Smart LLM Switching for Cost and Performance Optimization

---

## 1. Testing Philosophy & Test Infrastructure

The testing suite guarantees that every algorithmic and infrastructure component operates deterministically without relying on third-party API availability, spending financial credits, or leaking test data into the operational database.

### Core Testing Pillars:
1. **Fully Isolated In-Memory Database (`:memory:`):**
   * Configured via `isolate_database` session fixture in `backend/tests/conftest.py`.
   * Intercepts `settings.database_path` and replaces it with SQLite `:memory:`.
   * Enforces a post-session assertion verifying that zero test queries pollute `data/metrics.db`.
2. **Deterministic Fake Provider (`backend/tests/fake_provider.py`):**
   * Local multithreaded HTTP server listening on port 8999.
   * Simulates OpenAI, Gemini, and Groq endpoints with configurable simulated latency, token counts, and error modes (HTTP 500, 429 rate limit, network timeout).
3. **Comprehensive Coverage (308 Tests):**
   * Covers unit mathematics, integration pipelines, adversarial injections, circuit breaker state machines, and streaming SSE endpoints.

---

## 2. Test Suite Catalog

| Test File | Focus Area | Key Verifications |
|---|---|---|
| `test_stage2_corrections.py` | Second-Stage Technical Corrections | Verifies all 5 verified fixes: failed model attribution, word-boundary context detection (Scenarios A–D), Python AST syntax verification, arithmetic verifier, and Context-Aware Completion Cache. |
| `test_6tiers.py` | 6-Tier Architecture | Validates provider model mappings for Tiers 1 through 6, ensuring correct endpoints (`gemini-3.5-flash-lite`, `openai/gpt-oss-20b`, `gemini-3.6-flash`, etc.). |
| `test_linucb.py` | LinUCB Mathematics | Verifies ridge regression weight calculations ($\hat{\theta}_a = A_a^{-1} b_a$), Sherman-Morrison rank-1 online inverse updates, exploration bonuses, and matrix regularization. |
| `test_linucb_e2e.py` | End-to-End Bandit Pipeline | Tests full query execution, cache hits ($0.01\text{ ms}$), arm updates, and persistence across simulated reboots. |
| `test_eligibility.py` | MCDA Filter | Verifies hard constraints: circuit breaker status, SLA latency deadlines, context window token limits, and `MAX_COST_PER_REQUEST` caps. |
| `test_features.py` | 16-D Feature Extractor | Tests shape `(16,)`, dtype `float64`, unit norm $\|\mathbf{x}\|_2 = 1.0$, numerical stability on empty queries, and multi-domain corpus projection. |
| `test_reward.py` | Reward Engine & AST Checks | Verifies Python AST syntax deduction ($-0.35$ penalty on broken code), deterministic arithmetic verification ($-0.50$ penalty), and user feedback integration. |
| `test_circuit.py` | Circuit Breakers | Tests transitions between `CLOSED`, `OPEN`, and `HALF_OPEN` states, consecutive failure trip counters, and probe requests. |
| `test_api.py` | REST & SSE Endpoints | Tests `/health`, `/api/chat`, `/api/chat/stream`, `/api/analyze`, `/api/feedback`, and `/api/stats`. |
| `test_adversarial.py` | Adversarial Stress & Security | Tests prompt injection resistance, rapid request bursts, malformed JSON, and oversized token payloads. |
| `test_adaptive_routing.py` | Adaptive Routing Policies | Evaluates Pareto efficiency across `balanced`, `lowest_cost`, `fastest`, and `highest_quality` strategies. |

---

## 3. Running the Tests

Ensure your virtual environment is active before executing tests.

### Run the Complete Test Suite
```bash
pytest -v
```
*(Runs all 308 tests across the test catalog.)*

### Run Specific Test Modules
* **Run Second-Stage Technical Regression Tests:**
  ```bash
  pytest backend/tests/test_stage2_corrections.py -v
  ```
* **Run LinUCB Contextual Bandit Tests:**
  ```bash
  pytest backend/tests/test_linucb.py backend/tests/test_linucb_e2e.py -v
  ```
* **Run Feature Extraction Tests:**
  ```bash
  pytest backend/tests/test_features.py -v
  ```
* **Run Reward & AST Verification Tests:**
  ```bash
  pytest backend/tests/test_reward.py -v
  ```
* **Run Circuit Breaker & 6-Tier Tests:**
  ```bash
  pytest backend/tests/test_circuit.py backend/tests/test_6tiers.py -v
  ```
* **Run API Integration & Streaming Tests:**
  ```bash
  pytest backend/tests/test_api.py -v
  ```

---

## 4. Test Execution Expected Output

```text
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\...\Context-Aware-Smart-LLM-Switching
configfile: pytest.ini
collected 308 items

backend/tests/test_6tiers.py ........                                    [  2%]
backend/tests/test_adaptive_routing.py ..........                        [  5%]
backend/tests/test_adversarial.py ...................................    [ 17%]
backend/tests/test_adversarial_m1_challenger.py ........................ [ 27%]
.....................................                                    [ 36%]
backend/tests/test_api.py ....................................           [ 48%]
backend/tests/test_context_and_telemetry.py ......ss.............s..     [ 56%]
backend/tests/test_eligibility.py ...............                        [ 61%]
backend/tests/test_features.py ..................................        [ 72%]
backend/tests/test_linucb.py ..........................                  [ 80%]
backend/tests/test_linucb_e2e.py ...........                             [ 84%]
backend/tests/test_reward.py ......................                      [ 91%]
backend/tests/test_routing.py ..............                             [ 95%]
backend/tests/test_stage2_corrections.py .............                   [100%]

============ 305 passed, 3 skipped in ~70s ============
```
