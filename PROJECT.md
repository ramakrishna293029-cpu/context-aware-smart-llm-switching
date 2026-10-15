# Project: Context-Aware Smart LLM Switching for Cost & Performance Optimization

## Architecture
The system consists of an intelligent LLM switching proxy designed to optimize inference cost, latency, and constraint adherence across a 6-tier model hierarchy guided by a Gemini 3.1 Flash-Lite routing brain.

```
Incoming Request (Query + Context)
  │
  ├── [Context Ingestion & Demarcation] ── SHA-256, UTC ISO-8601, <untrusted_context>, provenance
  ├── [Constraint Ledger] ── Monotonic vN, ACTIVE/SUPERSEDED/CONFLICTED/EXPIRED/REVOKED, 4-Factor Resolution
  ├── [Hybrid Retrieval] ── BM25 lexical + Semantic Similarity fused via RRF (k=60)
  │
  ▼
[Triage: Compact Analyzer Payload (<300ms)]
  │
  ├── Underspecified Query? ──► [Self-Mode Clarification Short-Circuit]
  ├── Simple / Greeting / Conversational? ──► [Self-Mode Answer (Tier 0 Brain)]
  │
  ▼
[Candidate Scoring & Routing Engine]
  │ S(m) = w_r * f_r + w_c * f_c + w_l * f_l + w_t * f_t
  │ Factor f_5 (Cost Efficiency) & Factor f_6 (Latency Efficiency)
  │
  ▼
[Dynamic Token Budget Allocation & Response Payload Isolation]
  │ Protects 100% active critical constraints, reserves headroom, isolated citations
  │
  ▼
[Execution Tier (Tiers 1–6)]
  │ Real provider stream / fake_provider mock
  │
  ▼
[Verification & Real-Time Telemetry Pipeline]
  │ Timers (retrieval, prep, analyzer, generation, verification)
  │ Stage costs ($), Tier 6 baseline cost ($), savings ($ and %), throughput (tok/s)
  │ Persist to metrics.db, emit SSE done event, update /api/stats
  │
  ▼
[Obsidian Dark Glassmorphic UI (#0B0F17)]
  ├── Chat Decision Drawer (Telemetry Strip, Cost Split + Green Savings, Performance Badge, Waterfall, Scoreboard)
  └── Live Analytics Dashboard (KPIs, 7-Row Per-Model Matrix Table, Provenance Request Inspector)
```

## Feature Inventory
Every feature from the Survey phase and user requirements is inventoried and mapped to a milestone.

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Baseline Test Integrity | Restore 100% pass on all 103 baseline tests (fix 5 regression points in analyzer triage, health arch string, tier names, fake_provider fallback, benchmark baseline) | M1 | Survey / R1 |
| 2 | Model Hierarchy & Endpoint Preservation | Preserve 6-tier hierarchy (`gemini-3.1-flash-lite` + Tiers 1-6), circuit breakers, existing REST & SSE endpoints | M1 | Survey / R1 |
| 3 | Context Ingestion & Provenance | `app/context.py` `ingest_document`/`ingest_code` with UTC ISO-8601, SHA-256 hash, trust level (`trusted`/`untrusted`), source citations `[source_id]`, expose `/api/context/ingest` | M2 | Survey / R3 |
| 4 | Constraint Ledger Lifecycle & Versioning | `app/constraint_ledger.py` monotonic integer versioning ($v_1, v_2, \dots$), lifecycle states (`ACTIVE`, `SUPERSEDED`, `CONFLICTED`, `EXPIRED`, `REVOKED`) | M2 | Survey / R3 |
| 5 | 4-Factor Deterministic Conflict Resolution | Authority (`SYSTEM_POLICY > DEVELOPER_GUARDRAIL > USER_EXPLICIT > INFERRED_CONTEXT > UNTRUSTED_DOCUMENT`) > Scope Specificity > Explicit Supersession > Chronology | M2 | Survey / R4 |
| 6 | Hybrid Retrieval with RRF | BM25 lexical / exact symbol matching + semantic cosine similarity fused via Reciprocal Rank Fusion ($k=60$) in `app/retrieval.py` | M2 | Survey / R3 |
| 7 | Prompt Injection Demarcation | Isolate external content inside `<untrusted_context source_id="..." trust="untrusted">` with XML-escaping; protect ledger and routing from untrusted overrides | M2 | Survey / R5 |
| 8 | Compact Analyzer Payload | Triage payload containing only query, active constraints summary, unresolved conflicts, token estimates (<300ms SLA) | M3 | Survey / R4 |
| 9 | Isolated Response Generation Payload | Segregated generation payload containing retrieved evidence with `[source_id]` citations, active constraints, and formatting rules | M3 | Survey / R4 |
| 10 | Dynamic Token Budget Allocation | Allocates tokens respecting model context ceiling and output headroom while strictly protecting 100% of active critical constraints from truncation | M3 | Survey / R4 |
| 11 | Underspecified Query Clarification | Detect queries missing essential parameters (`needs_clarification`, `missing_parameters`, `clarification_question`), short-circuiting downstream escalation via `self` mode | M3 | Survey / R5 |
| 12 | High-Precision Stage Timers | `time.perf_counter()` timers across 5 stages (`retrieval_ms`, `prep_ms`, `analyzer_ms`, `generation_ms`, `verification_ms`) | M4 | Survey / R5 |
| 13 | Real-Time Stage Cost Calculations | Exact USD costs (`analyzer_cost_usd`, `generation_cost_usd`, `total_cost_usd`), Tier 6 baseline cost, cost savings ($ and %) | M4 | Survey / R2 |
| 14 | Performance Metrics & Throughput | TTFT (`ttft_ms`), total turn latency (`total_latency_ms`), generation throughput (`tokens_per_sec`) | M4 | Survey / R2 |
| 15 | Zero-Fabricated-Telemetry Backend Guarantee | Return real telemetry or explicitly "Unavailable" if omitted by provider; persist to `metrics.db` and SSE done events | M4 | Survey / R1 / R2 |
| 16 | Analytics Dashboard API Engine | `/api/stats` endpoint returning 6 KPIs (Total Requests, Success Rate, Spend, Saved, Avg TTFT, Avg Throughput), 7-row Per-Model Matrix (Tiers 1-6 + Brain), Request Inspector provenance | M4 | Survey / R2 |
| 17 | Obsidian Dark Glassmorphic Theme | `#0B0F17` background, translucent RGBA layered surfaces, `backdrop-filter: blur(12px)`, specular edge highlights in `static/style.css` | M5 | Survey / R1 |
| 18 | Chat UI Granular Telemetry Strip & Badges | Mode/Tier pill, Cost Badge with split + Green Savings Pill, Performance Badge (TTFT, Total, Throughput) | M5 | Survey / R2 |
| 19 | Chat UI Stage Latency Waterfall Bar | 5-stage proportional visual waterfall bar in Decision Drawer | M5 | Survey / R2 |
| 20 | Chat UI Candidate Scoreboard Table | Candidate Scoreboard with $S(m)$, factor $f_5$ (cost), factor $f_6$ (latency), and winning rationale | M5 | Survey / R2 |
| 21 | Live Analytics Dashboard UI & Inspector | Render Avg TTFT and Throughput KPI cards, 7-row Per-Model Matrix Table, and enriched Request Inspector with provenance and Zero-Fabrication badge | M5 | Survey / R2 |
| 22 | Automated Verification Suite (8 Scenarios) | `tests/test_context_and_telemetry.py` validating UTC provenance, lifecycle states, 4-factor conflict, hybrid retrieval, payload isolation, budget protection, injection defense, clarification + telemetry | E2E / M6 | Survey / R6 |
| 23 | 3-Way Baseline Benchmark Runner | `benchmarks/run_3way_benchmark.py` comparing Always-Frontier (Tier 6), Static Keyword/Regex, Context-Aware Smart Switching across 6 metrics | E2E / M6 | Survey / R6 |
| 24 | Final Adversarial Hardening (Tier 5) | Adversarial test coverage hardening against edge cases and corner conditions | M6 Phase 2 | Project Pattern |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Non-Destructive Base Preservation & Baseline 103 Test Fixes | Fix 5 baseline regression points; ensure all 103 baseline tests pass 100% | none | BLOCKED: Iteration 2 Gate Fail (Harness & Cross-Test State Leak) |
| M2 | Context Ingestion, Constraint Ledger & Hybrid Retrieval | `app/context.py`, `app/constraint_ledger.py`, `app/retrieval.py`, `<untrusted_context>` | M1 | PLANNED |
| M3 | Payloads, Dynamic Token Budgeting & Clarification | Compact analyzer payload, isolated response payload, dynamic budget, clarification self mode | M2 | PLANNED |
| M4 | Real-Time Telemetry Pipeline & Live Analytics Engine | 5-stage timers, exact USD costs, throughput, `metrics.db`, `/api/stats` matrix | M3 | PLANNED |
| M5 | Obsidian Dark Glassmorphic UI & Chat Decision Drawer | `#0B0F17` theme, Decision Drawer badges, waterfall bar, scoreboard, dashboard matrix UI | M4 | PLANNED |
| E2E | E2E Testing Suite & 3-Way Benchmark Suite | `tests/test_context_and_telemetry.py` (8 scenarios) + `benchmarks/run_3way_benchmark.py` | Parallel to M1-M5 | IN_PROGRESS |
| M6 | Final Verification & Adversarial Coverage Hardening | Phase 1: 100% pass on 103 baseline + new 8 scenarios + 3-way benchmark run; Phase 2: Tier 5 adversarial hardening | M5, E2E | PLANNED |

## Interface Contracts

### Context & Ingestion ↔ Retrieval & Ledger
- `ingest_document(text: str, source_id: str, trust_level: str = "untrusted", metadata: dict = None) -> ContextDocument`
  - Document fields: `source_id`, `text`, `sha256_hash`, `timestamp_utc` (ISO-8601), `trust_level` ("trusted" | "untrusted"), `citations`
- `app/retrieval.py`:
  - `hybrid_retrieve(query: str, documents: List[ContextDocument], top_k: int = 5, bm25_weight: float = 0.5, rrf_k: int = 60) -> List[Tuple[ContextDocument, float]]`
- `app/constraint_ledger.py`:
  - `ConstraintStatus`: Enum(`ACTIVE`, `SUPERSEDED`, `CONFLICTED`, `EXPIRED`, `REVOKED`)
  - `ConstraintAuthority`: Enum(`SYSTEM_POLICY`=5, `DEVELOPER_GUARDRAIL`=4, `USER_EXPLICIT`=3, `INFERRED_CONTEXT`=2, `UNTRUSTED_DOCUMENT`=1)
  - `version`: int (monotonic $v_1, v_2, \dots$)
  - `resolve_conflict(c1, c2) -> ActiveConstraint`: evaluates Authority > Specificity > Explicit Supersession > Chronology

### Triage & Payloads ↔ Routing Brain & Downstream Models
- Compact Analyzer Payload:
  - `{"query": str, "active_constraints_summary": List[str], "unresolved_conflicts": List[str], "token_estimates": dict}`
  - Target latency SLA: <300ms
- Clarification Result:
  - `{"needs_clarification": bool, "missing_parameters": List[str], "clarification_question": Optional[str], "answer_mode": "self"}`
- Isolated Response Generation Payload:
  - `{"retrieved_evidence": List[dict], "active_constraints": List[dict], "history": List[dict], "query": str, "max_tokens": int}`
  - Dynamic token budget protects 100% of active critical constraints without truncation.

### Telemetry Pipeline ↔ API & UI
- Granular Latency Breakdown:
  - `retrieval_ms`: float, `prep_ms`: float, `analyzer_ms`: float, `generation_ms`: float, `verification_ms`: float, `total_latency_ms`: float, `ttft_ms`: float
- Stage USD Costs:
  - `analyzer_cost_usd`: float, `generation_cost_usd`: float, `total_cost_usd`: float, `baseline_cost_usd`: float (Tier 6), `cost_savings_usd`: float, `cost_savings_pct`: float
- Performance:
  - `tokens_per_sec`: float (or "Unavailable")
- Candidate Scoreboard Candidates:
  - `candidates: List[{"tier": str, "name": str, "total_score": float, "factor_cost": float, "factor_latency": float, "expected_latency_ms": float, "expected_cost_usd": float, "selected": bool, "rationale": str}]`
- SSE `done` event:
  - Emits all the above fields in JSON.

## Code Layout
- `app/`
  - `main.py`: FastAPI routes, endpoints (`/api/chat`, `/api/context/ingest`, `/api/stats`, `/api/health`, `/api/analyze`)
  - `registry.py`: 6-tier models (`gemini-3.1-flash-lite` routing brain + `gemini-tier_1` to `gemini-tier_6`), pricing, latency baselines
  - `context.py`: Ingestion, document hashing, ISO-8601 UTC, `<untrusted_context>` demarcation, dynamic budget allocation
  - `constraint_ledger.py`: Monotonic versioning, `ConstraintStatus`, 4-factor conflict resolution
  - `retrieval.py`: Lexical BM25 + Semantic Cosine + RRF ($k=60$)
  - `analyzer_llm.py`: Compact payload triage, clarification detection, greeting fast-path self-mode
  - `pipeline.py`: End-to-end execution, high-precision timers, stage costs, throughput calculation, SSE streaming
  - `tracker.py`: SQLite persistence (`metrics.db`), `/api/stats` aggregations (KPIs, 7-row matrix, request inspector)
  - `schemas.py`: Pydantic models for chat requests/responses, ingestion, candidate scoring, telemetry
- `static/`
  - `index.html`: Obsidian Dark UI shell, Chat Decision Drawer markup, Dashboard views
  - `style.css`: Glassmorphic styling (`#0B0F17`, backdrop blur, badges, waterfall, matrix)
  - `app.js`: SSE consumer, Decision Drawer renderer, Dashboard loader & Request Inspector
- `tests/`
  - `conftest.py`: Test fixtures, fake provider server, in-memory DB
  - `fake_provider.py`: Mock model server
  - `test_6tiers.py`, `test_adaptive_routing.py`, `test_adversarial.py`, `test_api.py`, `test_routing.py`: 103 baseline tests
  - `test_context_and_telemetry.py`: New 8-scenario comprehensive verification suite
- `benchmarks/`
  - `run_3way_benchmark.py`: 3-Way Baseline Benchmark Runner
