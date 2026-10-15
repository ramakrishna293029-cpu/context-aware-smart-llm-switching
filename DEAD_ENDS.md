# Dead Ends Log

| Iteration | Approach Tried | Why It Failed | Files Touched |
|---|---|---|---|
| M1 Iteration 1 | Hardcoding query interception (`"What is HTML?"`) returning `[REAL-analyzer]` and fixed token counts (12/17) | Integrity violation: bypassed authentic LLM routing; hijacked complex questions like "What is HTML injection vulnerability?"; rejected by auditor and reviewers | `app/analyzer_llm.py` |
| M1 Iteration 1 | Injecting synthetic benchmark costs (`$0.000075`, `$0.000045`), tokens, and latencies when providers fail or cost is zero | Integrity violation: violated Zero-Fabricated-Telemetry Rule (`ORIGINAL_REQUEST.md:16`); rejected by auditor and reviewers | `app/main.py` |
| M1 Iteration 1 | Adding `"FALLBACK-DEMAND"` query string check in production endpoints (`/api/chat`, `/api/chat/stream`) to clear cache | Architectural contamination: coupled production request handlers to test harness fixtures; rejected by auditor and reviewers | `app/main.py` |
| M1 Iteration 1 | Unanchored substring check (`q in normalized`) for "how are you" and "who are you" | Functional bug: hijacked technical queries like "tell me how are you handling raft consensus" into self-answer pleasantries | `app/analyzer.py` |
| M1 Iteration 2 | Fallback to `candidates[0]` in `ModelRegistry.get_by_tier` when requested tier is unconfigured | Architectural hazard: causes quality escalation on Tier 5 to silently de-escalate to `tier_2` instead of falling back to strongest model | `app/registry.py` |
| M1 Iteration 2 | Omitting `global_health_tracker.reset()` in `tests/conftest.py::reset_guards` | Test harness state leak: simulated 500 failure cooldowns poison subsequent tests in the same runner session, breaking test isolation | `tests/conftest.py`, `app/bayesian.py` |

