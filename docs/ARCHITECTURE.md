# System Architecture & Technical Specification

## Context-Aware Smart LLM Switching for Cost and Performance Optimization

---

## 1. High-Level Architectural Flow

```text
========================================================================================================================
                                     END-TO-END SMART LLM SWITCHING ARCHITECTURE
========================================================================================================================

           User Request (Chat / Stream / REST API)
                          │
                          ▼
            [ Context-Aware Completion Cache ] ─── (Hit: exact SHA-1 + context) ──► Instant Return (0.01 ms, $0.00)
                          │ (Miss)
                          ▼
             [ Context Dependency Detector ] ─── (Word-boundary regex & elliptical follow-up tracking)
                          │
                          ▼
           [ 16-Dimensional Feature Extractor ] ──► Context Vector x ∈ ℝ¹⁶ (||x||₂ = 1.0) via TF-IDF + TruncatedSVD
                          │
                          ▼
             [ MCDA Hard Eligibility Filter ] ─── (Filters tripped circuit breakers, deadline breaches, cost caps)
                          │ (Eligible Models Set)
                          ▼
          [ Disjoint LinUCB Contextual Bandit ] ──► Calculates UCB Score: s_a = x^T θ_a + α √(x^T A_a⁻¹ x)
                          │                         Selects Primary Model Tier & Prepares Fallback Chain
                          ▼
            [ Multi-Tier Execution Pipeline ]
                    ├── Primary Attempt ──► Circuit Breaker Monitor (Closed / Half-Open)
                    └── Failure / Timeout ──► Fallback Chain (Records exact elapsed latency & incurred cost per attempt)
                          │
                          ▼
          [ Response Quality Evaluator & Verifier ]
                    ├── Python AST Syntax Verification (ast.parse)
                    ├── Deterministic Arithmetic Verification
                    └── Length, Format & Explicit User Feedback (±1)
                          │
                          ▼
              [ Reward Engine & Bandit Update ] ──► R = w_q·Q - w_c·C - w_l·L + w_f·F
                          │                         A_a ← A_a + x x^T,  b_a ← b_a + r x
                          ▼
        [ SQLite Telemetry Store & Real-Time UI ] ──► Telemetry metrics, token audits, live bandit arm inspection
========================================================================================================================
```

---

## 2. Component Specifications

### 2.1 Context-Aware Completion Cache (`backend/app/pipeline.py`)
* **Mechanism:** Exact-match Least Recently Used (LRU) in-memory cache keyed by the SHA-1 digest of normalized query text plus contextual history.
* **Capacity & Eviction:** Up to 64 active entries with a 300-second Time-To-Live (TTL).
* **Performance:** Returns complete responses in $<0.02\text{ ms}$ with zero token consumption and zero upstream API calls.

### 2.2 Conversational Context Detector (`backend/app/pipeline.py`)
* **Problem Solved:** Standalone queries should not pay the token cost or distraction of irrelevant history. Conversely, elliptical follow-ups require prior context.
* **Algorithm:** Word-boundary regular expression matching (`\b(it|its|that|this|these|those|same|now|again)\b`, `\b(time complexity|space complexity)\b`, `\b(in java|in python|in rust|in c\+\+)\b`).
* **Scenarios Handled:**
  * *Scenario A (Dijkstra $\to$ Explain its time complexity):* Detects elliptical pronoun `its`, attaches prior Java Dijkstra code.
  * *Scenario B (Web scraper $\to$ Optimize it):* Detects refinement cue `optimize it`, preserves scraper context.
  * *Scenario C (Capital of France $\to$ 15 multiplied by 4):* Recognizes independent arithmetic, cleanly isolates history.
  * *Scenario D (Binary search $\to$ Give an example in Java):* Detects language specialization `in java`, includes history.

### 2.3 16-Dimensional Feature Extractor (`backend/app/features.py`)
* **Algorithm:** Scikit-learn `TfidfVectorizer` (sublinear term frequency, unigram + bigram n-grams) combined with `TruncatedSVD` (Latent Semantic Analysis) fitted on a diverse seed corpus.
* **Output:** A dense 16-dimensional vector $\mathbf{x} \in \mathbb{R}^{16}$ with unit $L_2$ norm ($\|\mathbf{x}\|_2 = 1.0$).
* **Latency:** Executes locally in $<0.1\text{ ms}$ without GPU requirements.

### 2.4 Multi-Criteria Decision Analysis (MCDA) Filter (`backend/app/eligibility.py`)
Before computing bandit scores, all registered models are filtered through strict feasibility constraints:
1. **Circuit Breaker Status:** Models with tripped (`OPEN`) breakers are excluded.
2. **Credential Availability:** Models lacking valid provider API keys (or active mock adapters) are dropped.
3. **Context Window Feasibility:** Ensures total prompt tokens $\le \text{model.context\_window}$.
4. **Latency Deadline:** Filters out models whose historical expected latency exceeds client-specified SLA deadlines.
5. **Cost-Per-Request Cap:** Models whose projected cost ($\text{tokens} \times \text{price}$) exceeds `MAX_COST_PER_REQUEST` are removed.

### 2.5 Disjoint LinUCB Contextual Bandit Router (`backend/app/linucb.py`)
Each of the 6 model tiers acts as an independent arm $a \in \{1, \dots, 6\}$:
* **Ridge Regression Weights:**
  $$\hat{\theta}_a = A_a^{-1} b_a$$
  where $A_a = D_a^T D_a + I_{16} \in \mathbb{R}^{16 \times 16}$ and $b_a = D_a^T r_a \in \mathbb{R}^{16}$.
* **Action Selection (Upper Confidence Bound):**
  $$s_a(\mathbf{x}) = \mathbf{x}^T \hat{\theta}_a + \alpha \sqrt{\mathbf{x}^T A_a^{-1} \mathbf{x}}$$
  * $\mathbf{x}^T \hat{\theta}_a$: Exploitation term (predicted reward based on past outcomes).
  * $\alpha \sqrt{\mathbf{x}^T A_a^{-1} \mathbf{x}}$: Exploration bonus proportional to model uncertainty in feature subspace $\mathbf{x}$.
  * The model with the highest $s_a$ is chosen as the primary tier; remaining eligible candidates are ranked to form the fallback chain.
* **Online Update:**
  Upon receiving composite reward $r \in [-1, 1]$:
  $$A_a \leftarrow A_a + \mathbf{x} \mathbf{x}^T, \quad b_a \leftarrow b_a + r \mathbf{x}$$
  Matrices are serialized into the `bandit_arms` table in SQLite for seamless persistence across server restarts.

### 2.6 The 6 Response-Model Tiers (`backend/app/registry.py`)

| Tier | Provider | Model ID in Code | Role & Primary Workload | Context Window |
|---|---|---|---|---|
| **Tier 1 (T1)** | **Google Gemini** | `gemini-3.5-flash-lite` | Ultra-fast responses, definitions, factual lookups | 1,000,000 |
| **Tier 2 (T2)** | **Groq** | `openai/gpt-oss-20b` | Structured JSON, classification, brief extraction | 131,072 |
| **Tier 3 (T3)** | **Google Gemini** | `gemini-3.6-flash` | General synthesis, summarization, balanced intelligence | 1,000,000 |
| **Tier 4 (T4)** | **Groq** | `qwen/qwen3.8-27b` | Code generation, syntax debugging, algorithmic refactoring | 32,768 |
| **Tier 5 (T5)** | **Groq** | `openai/gpt-oss-120b` | Advanced STEM reasoning, system trade-offs, mathematics | 128,000 |
| **Tier 6 (T6)** | **Google Gemini** | `gemini-3.8-flash`<br>*(Fallback: `gemini-3.5-flash`)* | Architectural design, distributed systems, maximum capability | 2,000,000 |

### 2.7 Response Quality Evaluator & Reward Engine (`backend/app/reward.py`)
The scalar reward $R \in [-1, 1]$ reinforces optimal routing behaviors:
$$R = w_q \cdot Q - w_c \cdot \hat{C} - w_l \cdot \hat{L} + w_f \cdot F$$
* **Quality Score ($Q \in [0, 1]$):** Evaluates response completeness, formatting, code fences, and structural validity.
  * **Python AST Verification (`ast.parse`):** If the response contains Python code blocks with syntax errors, a penalty of $-0.35$ is deducted.
  * **Deterministic Arithmetic Verification:** For straightforward arithmetic queries, the model's computed result is verified; computation errors incur a $-0.50$ penalty.
* **Cost Penalty ($\hat{C} \in [0, 1]$):** Measures actual USD expenditure relative to tier baseline.
* **Latency Penalty ($\hat{L} \in [0, 1]$):** Penalizes slow responses relative to SLA deadlines.
* **Human Feedback ($F \in \{-1, 0, 1\}$):** Explicit thumbs up / thumbs down submitted by users.
* **Failure Attribution:** Failed or timed-out attempts receive a strict negative reward ($R \le -0.10$). Models skipped due to open circuit breakers are not penalized.

### 2.8 Resilient Fallback & Circuit Breakers (`backend/app/circuit.py`)
Each model tier possesses an independent circuit breaker:
* `CLOSED`: Upstream is healthy. Consecutive failures increment a counter.
* `OPEN`: After 3 consecutive timeouts or connection errors, the circuit opens for a cooldown window ($30\text{ seconds}$). Traffic bypasses the tier instantly.
* `HALF_OPEN`: Allows a single probe request to verify upstream recovery before closing.
