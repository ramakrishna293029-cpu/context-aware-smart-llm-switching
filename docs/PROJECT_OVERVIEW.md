# Project Overview

## Title
**Context-Aware Smart LLM Switching for Cost and Performance Optimization**

---

## 1. Problem Statement

Modern enterprise generative AI applications face a critical economic and performance dilemma:

1. **Frontier Model Overspending:** Always routing every user query to top-tier frontier models (e.g., Gemini 3.8 Flash, GPT-4, Claude 3.5 Sonnet) produces high-quality answers but incurs massive financial costs and high latency ($1,000\text{--}5,000\text{ ms}$). Upwards of 60–75% of real-world user interactions consist of greetings, conversational pleasantries, simple lookups, or straightforward factual queries that do not require frontier reasoning.
2. **Compact Model Quality Failure:** Exclusively utilizing small, budget-friendly models (e.g., 8B parameter models) minimizes operational expense but causes severe failures when users request complex software algorithms, rigorous mathematical proofs, or system architecture designs.
3. **Static Heuristic Brittleness:** Hardcoded keyword/regex triage is brittle, easily deceived by nuances, fails to adapt to dynamic API outages or rate limits, and lacks the ability to learn from past routing outcomes.

---

## 2. Project Objectives

The primary objective of this project is to build an autonomous, production-grade **Context-Aware Smart LLM Switching Proxy** that achieves optimal cost-performance Pareto efficiency:

* **Dynamic Multi-Tier Switching:** Intelligently dispatch user prompts to one of **6 specialized model tiers** spanning lightweight completion engines to frontier reasoning models.
* **Contextual Bandit Learning:** Formulate model routing as an online **Contextual Multi-Armed Bandit (Disjoint LinUCB)** problem, balancing exploitation of known high-performing models with exploration of uncertain tiers.
* **Low-Latency Feature Extraction:** Project conversational context and prompt semantics into a **16-dimensional normalized vector** ($\mathbf{x} \in \mathbb{R}^{16}$) locally in $<0.1\text{ ms}$ using TF-IDF and Latent Semantic Analysis (TruncatedSVD).
* **Deterministic SLA & Budget Enforcement:** Apply **Multi-Criteria Decision Analysis (MCDA)** to eliminate candidates violating context windows, cost-per-request caps, or response deadlines before bandit evaluation.
* **Context-Aware Completion Caching:** Maintain an in-memory SHA-1 cache with conversation history normalization to return instant ($0.01\text{ ms}$), zero-cost responses for repeated queries.
* **Enterprise Fault Tolerance:** Integrate three-state circuit breakers (`CLOSED`, `OPEN`, `HALF_OPEN`) with per-tier timeout thresholds and automatic fallback chains.
* **Automated Quality & Syntax Verification:** Validate code outputs using Python AST parsing (`ast.parse`) and verify arithmetic computations to detect hallucinations before awarding bandit rewards.
* **Observability & Transparency:** Deliver a glassmorphic dashboard tracking exact token usage, micro-USD costs, latency distributions, and live LinUCB arm parameters with zero data fabrication.

---

## 3. Technology Stack

* **Backend Framework:** FastAPI, Uvicorn, Python 3.10+
* **Machine Learning & Bandits:** NumPy, scikit-learn (TF-IDF, TruncatedSVD), Disjoint LinUCB with Sherman-Morrison rank-1 updates
* **Large Language Models & Providers:**
  * Google Gemini API (`gemini-3.5-flash-lite`, `gemini-3.6-flash`, `gemini-3.8-flash`)
  * Groq Cloud API (`openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, `openai/gpt-oss-120b`)
* **Persistence & Database:** SQLite (`metrics.db`) with WAL mode for ACID-compliant request logging, budget tracking, and LinUCB arm persistence
* **Frontend UI:** Vanilla JavaScript (ES6+), Server-Sent Events (SSE), CSS3 Glassmorphic Obsidian Design System, KaTeX for mathematical rendering, Marked.js for markdown streaming, DOMPurify for sanitization
* **Testing & QA:** Pytest, Asyncio, FastAPI TestClient, unittest.mock (308 automated tests)

---

## 4. Key Performance Indicators (KPIs)

Based on empirical benchmarks comparing fixed frontier routing against our Context-Aware LinUCB Switching Router:

* **Turn Latency Reduction:** **96.6% average latency reduction** ($26,549\text{ ms} \to 898\text{ ms}$).
* **Tail Latency Reduction:** **97.2% P95 latency reduction** ($67,776\text{ ms} \to 1,887\text{ ms}$).
* **Cost Efficiency:** **81.6% total cost reduction** compared to fixed frontier escalation.
* **Cache Acceleration:** **$0.01\text{ ms}$ response time** on cache hits with $0.00 token cost.
* **System Availability:** **100% success rate** maintained under simulated provider timeouts via automated fallback chains.
