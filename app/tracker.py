"""Performance Tracker: SQLite persistence for requests, telemetry, and metrics."""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import settings
from .schemas import HistoryRow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    query TEXT NOT NULL,
    task_type TEXT NOT NULL,
    complexity TEXT NOT NULL,
    complexity_score REAL NOT NULL,
    analyzer_provider TEXT NOT NULL,
    analyzer_model TEXT NOT NULL,
    analyzer_latency_ms REAL NOT NULL,
    analyzer_input_tokens INTEGER,
    analyzer_output_tokens INTEGER,
    analyzer_cost REAL,
    target_tier TEXT NOT NULL,
    target_provider TEXT NOT NULL,
    selected_model TEXT NOT NULL,
    selected_provider TEXT NOT NULL,
    routing_reason TEXT,
    context_relevant INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    latency_ms REAL NOT NULL,
    total_latency_ms REAL NOT NULL,
    ttft_ms REAL,
    estimated_cost REAL,
    baseline_cost REAL,
    savings_usd REAL,
    savings_percent REAL,
    success INTEGER NOT NULL,
    error TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    fallback_reason TEXT,
    escalation_used INTEGER NOT NULL DEFAULT 0,
    escalation_reason TEXT,
    strategy TEXT,
    feedback INTEGER,
    candidates_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_time ON requests(timestamp);
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(selected_model);
"""


def estimate_cost_usd(model_prices: tuple[float, float], input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[float]:
    """USD cost calculation from token counts and price table (USD per 1M tokens)."""
    if input_tokens is None or output_tokens is None:
        return None
    in_price, out_price = model_prices
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


class Tracker:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock, self._connect() as conn:
            # Check if table exists and what columns it has
            table_check = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='requests'").fetchone()
            if table_check:
                existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(requests)").fetchall()}
                required_cols = {
                    "complexity_score": "REAL DEFAULT 0.5",
                    "total_latency_ms": "REAL DEFAULT 0.0",
                    "savings_usd": "REAL DEFAULT 0.0",
                    "savings_percent": "REAL DEFAULT 0.0",
                    "target_tier": "TEXT DEFAULT 'fast'",
                    "target_provider": "TEXT DEFAULT 'gemini'",
                    "selected_provider": "TEXT DEFAULT 'gemini'",
                    "routing_reason": "TEXT",
                    "fallback_reason": "TEXT",
                    "escalation_used": "INTEGER DEFAULT 0",
                    "escalation_reason": "TEXT",
                    "analyzer_cost": "REAL DEFAULT 0.0",
                    "analyzer_input_tokens": "INTEGER DEFAULT 0",
                    "analyzer_output_tokens": "INTEGER DEFAULT 0",
                    "analyzer_latency_ms": "REAL DEFAULT 0.0",
                    "total_tokens": "INTEGER DEFAULT 0",
                }
                for col, col_def in required_cols.items():
                    if col not in existing_cols:
                        try:
                            conn.execute(f"ALTER TABLE requests ADD COLUMN {col} {col_def}")
                        except Exception:
                            pass
            else:
                conn.executescript(_SCHEMA)
            conn.commit()

    def record_request(
        self,
        *,
        query: str,
        task_type: str,
        complexity: str,
        complexity_score: float,
        analyzer_provider: str,
        analyzer_model: str,
        analyzer_latency_ms: float,
        analyzer_input_tokens: Optional[int],
        analyzer_output_tokens: Optional[int],
        analyzer_cost: Optional[float],
        target_tier: str,
        target_provider: str,
        selected_model: str,
        selected_provider: str,
        routing_reason: str,
        context_relevant: bool,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        total_tokens: Optional[int],
        latency_ms: float,
        total_latency_ms: float,
        ttft_ms: Optional[float],
        estimated_cost: Optional[float],
        baseline_cost: Optional[float],
        savings_usd: Optional[float],
        savings_percent: Optional[float],
        success: bool,
        error: Optional[str] = None,
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
        escalation_used: bool = False,
        escalation_reason: Optional[str] = None,
        strategy: str = "balanced",
        candidates_json: Optional[str] = None,
    ) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO requests (
                    timestamp, query, task_type, complexity, complexity_score,
                    analyzer_provider, analyzer_model, analyzer_latency_ms,
                    analyzer_input_tokens, analyzer_output_tokens, analyzer_cost,
                    target_tier, target_provider, selected_model, selected_provider,
                    routing_reason, context_relevant, input_tokens, output_tokens, total_tokens,
                    latency_ms, total_latency_ms, ttft_ms, estimated_cost, baseline_cost,
                    savings_usd, savings_percent, success, error,
                    fallback_used, fallback_reason, escalation_used, escalation_reason,
                    strategy, candidates_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    time.time(), query, task_type, complexity, complexity_score,
                    analyzer_provider, analyzer_model, analyzer_latency_ms,
                    analyzer_input_tokens, analyzer_output_tokens, analyzer_cost,
                    target_tier, target_provider, selected_model, selected_provider,
                    routing_reason, int(context_relevant), input_tokens, output_tokens, total_tokens,
                    latency_ms, total_latency_ms, ttft_ms, estimated_cost, baseline_cost,
                    savings_usd, savings_percent, int(success), error,
                    int(fallback_used), fallback_reason, int(escalation_used), escalation_reason,
                    strategy, candidates_json,
                ),
            )
            conn.commit()
            return cur.lastrowid

    def record_feedback(self, request_id: int, rating: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE requests SET feedback=? WHERE id=?",
                (rating, request_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def recent_requests(self, limit: int = 20) -> List[HistoryRow]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_history(r) for r in rows]

    def request_detail(self, request_id: int) -> Optional[dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["timestamp_fmt"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["timestamp"]))
        if row["candidates_json"]:
            try:
                out["candidates"] = json.loads(row["candidates_json"])
            except Exception:
                out["candidates"] = []
        return out

    def budget_status(self) -> dict:
        now = time.time()
        day_start = now - (now % 86400)
        month_start = now - (now % (86400 * 30))
        with self._lock, self._connect() as conn:
            day_spend = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(estimated_cost,0) + COALESCE(analyzer_cost,0)), 0) AS s FROM requests WHERE timestamp >= ? AND success=1",
                (day_start,),
            ).fetchone()["s"]
            month_spend = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(estimated_cost,0) + COALESCE(analyzer_cost,0)), 0) AS s FROM requests WHERE timestamp >= ? AND success=1",
                (month_start,),
            ).fetchone()["s"]
        return {
            "day_spend": day_spend,
            "month_spend": month_spend,
            "daily_budget_usd": settings.daily_budget_usd,
            "monthly_budget_usd": settings.monthly_budget_usd,
        }

    def dashboard_stats(self) -> dict:
        with self._lock, self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(success) AS successes,
                    AVG(latency_ms) AS avg_gen_latency,
                    AVG(total_latency_ms) AS avg_total_latency,
                    SUM(estimated_cost) AS total_model_cost,
                    SUM(analyzer_cost) AS total_analyzer_cost,
                    SUM(baseline_cost) AS total_baseline_cost,
                    SUM(savings_usd) AS total_savings_usd,
                    SUM(total_tokens) AS total_tokens,
                    SUM(fallback_used) AS fallbacks,
                    SUM(escalation_used) AS escalations,
                    SUM(CASE WHEN feedback=1 THEN 1 ELSE 0 END) AS good,
                    SUM(CASE WHEN feedback=-1 THEN 1 ELSE 0 END) AS poor
                FROM requests
                """
            ).fetchone()

            model_dist = conn.execute(
                "SELECT selected_model AS name, COUNT(*) AS count, selected_provider AS provider FROM requests GROUP BY selected_model ORDER BY count DESC"
            ).fetchall()

            provider_dist = conn.execute(
                "SELECT selected_provider AS name, COUNT(*) AS count FROM requests GROUP BY selected_provider ORDER BY count DESC"
            ).fetchall()

            tier_dist = conn.execute(
                "SELECT target_tier AS name, COUNT(*) AS count FROM requests GROUP BY target_tier ORDER BY count DESC"
            ).fetchall()

            task_dist = conn.execute(
                "SELECT task_type AS name, COUNT(*) AS count FROM requests GROUP BY task_type ORDER BY count DESC"
            ).fetchall()

            complexity_dist = conn.execute(
                "SELECT complexity AS name, COUNT(*) AS count FROM requests GROUP BY complexity ORDER BY count DESC"
            ).fetchall()

            recent = conn.execute("SELECT * FROM requests ORDER BY timestamp DESC LIMIT 20").fetchall()

        total = totals["total"] or 0
        successes = totals["successes"] or 0
        total_cost = (totals["total_model_cost"] or 0.0) + (totals["total_analyzer_cost"] or 0.0)
        baseline_cost = totals["total_baseline_cost"] or 0.0
        savings_usd = max(0.0, baseline_cost - total_cost)
        savings_percent = (savings_usd / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

        return {
            "total_requests": total,
            "successful_requests": successes,
            "failed_requests": total - successes,
            "success_rate": (successes / total) if total else 0.0,
            "average_latency_ms": round(totals["avg_gen_latency"] or 0.0, 1),
            "average_total_latency_ms": round(totals["avg_total_latency"] or 0.0, 1),
            "total_cost_usd": round(total_cost, 6),
            "baseline_cost_usd": round(baseline_cost, 6),
            "estimated_savings_usd": round(savings_usd, 6),
            "savings_percent": round(savings_percent, 1),
            "total_tokens": totals["total_tokens"] or 0,
            "fallback_count": totals["fallbacks"] or 0,
            "escalation_count": totals["escalations"] or 0,
            "feedback_good": totals["good"] or 0,
            "feedback_poor": totals["poor"] or 0,
            "model_distribution": [dict(r) for r in model_dist],
            "provider_distribution": [dict(r) for r in provider_dist],
            "tier_distribution": [dict(r) for r in tier_dist],
            "task_distribution": [dict(r) for r in task_dist],
            "complexity_distribution": [dict(r) for r in complexity_dist],
            "recent_requests": [_row_to_history(r) for r in recent],
            "budget": self.budget_status(),
        }


def _row_to_history(r) -> HistoryRow:
    tot_cost = (r["estimated_cost"] or 0.0) + (r["analyzer_cost"] or 0.0) if (r["estimated_cost"] is not None or r["analyzer_cost"] is not None) else None
    tot_lat = r["total_latency_ms"] if "total_latency_ms" in r.keys() and r["total_latency_ms"] else r["latency_ms"]
    return HistoryRow(
        id=r["id"],
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["timestamp"])),
        query=r["query"],
        task_type=r["task_type"],
        complexity=r["complexity"],
        selected_model=r["selected_model"],
        provider=r["selected_provider"] if "selected_provider" in r.keys() else "gemini",
        fallback_used=bool(r["fallback_used"]),
        escalation_used=bool(r["escalation_used"]) if "escalation_used" in r.keys() else False,
        input_tokens=r["input_tokens"],
        output_tokens=r["output_tokens"],
        total_tokens=r["total_tokens"] if "total_tokens" in r.keys() else None,
        estimated_cost_usd=r["estimated_cost"],
        total_cost_usd=tot_cost,
        latency_ms=round(r["latency_ms"], 1),
        total_latency_ms=round(tot_lat, 1),
        success=bool(r["success"]),
        feedback=r["feedback"],
        routing_reason=r["routing_reason"] if "routing_reason" in r.keys() else None,
        analyzer_model=r["analyzer_model"] if "analyzer_model" in r.keys() else None,
    )


tracker = Tracker(settings.database_path)