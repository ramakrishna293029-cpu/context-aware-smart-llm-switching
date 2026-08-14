"""Performance Tracker: SQLite persistence for every request + feedback.

Stores per-request metrics (query, complexity, chosen model, tokens,
cost, latency, success, feedback). Also computes the *baseline* cost —
what the request would have cost on the strongest available model —
so the dashboard can show real savings from intelligent routing.
"""

import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import settings
from .schemas import HistoryRow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    query TEXT NOT NULL,
    task_type TEXT NOT NULL,
    complexity REAL NOT NULL,
    selected_model TEXT NOT NULL,
    provider TEXT NOT NULL,
    demo_mode INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    estimated_cost REAL NOT NULL,
    baseline_cost REAL NOT NULL,
    latency_ms REAL NOT NULL,
    success INTEGER NOT NULL,
    error TEXT,
    feedback INTEGER
);
CREATE INDEX IF NOT EXISTS idx_requests_time ON requests(timestamp);
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(selected_model);
"""


def estimate_cost_usd(model_prices, input_tokens: int, output_tokens: int) -> float:
    """USD cost = input tokens * input price per Mtok + output tokens * output price per Mtok."""
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
            conn.executescript(_SCHEMA)

    def record_request(self, *, query: str, task_type: str, complexity: float,
                       selected_model: str, provider: str, demo_mode: bool,
                       input_tokens: int, output_tokens: int,
                       estimated_cost: float, baseline_cost: float,
                       latency_ms: float, success: bool, error: Optional[str] = None) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO requests (timestamp, query, task_type, complexity, "
                "selected_model, provider, demo_mode, input_tokens, output_tokens, "
                "estimated_cost, baseline_cost, latency_ms, success, error) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), query, task_type, complexity, selected_model, provider,
                 int(demo_mode), input_tokens, output_tokens, estimated_cost,
                 baseline_cost, latency_ms, int(success), error),
            )
            return cur.lastrowid

    def record_feedback(self, request_id: int, rating: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE requests SET feedback=? WHERE id=? AND success=1",
                (rating, request_id),
            )
            return cur.rowcount > 0

    def history_stats(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        """Per (task_type, model): n, avg_feedback, success_rate."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT task_type, selected_model, COUNT(*) AS n, "
                "AVG(feedback) AS avg_feedback, AVG(success) AS success_rate "
                "FROM requests GROUP BY task_type, selected_model"
            ).fetchall()
        out: Dict[str, Dict[str, Dict[str, float]]] = {}
        for r in rows:
            out.setdefault(r["task_type"], {})[r["selected_model"]] = {
                "n": r["n"],
                "avg_feedback": r["avg_feedback"] or 0.0,
                "success_rate": r["success_rate"] or 0.0,
            }
        return out

    def dashboard_stats(self) -> dict:
        with self._lock, self._connect() as conn:
            totals = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(success) AS successes, "
                "AVG(latency_ms) AS avg_latency, "
                "AVG(complexity) AS avg_complexity, "
                "SUM(estimated_cost) AS total_cost, "
                "SUM(baseline_cost) AS baseline_cost, "
                "SUM(CASE WHEN feedback=1 THEN 1 ELSE 0 END) AS good, "
                "SUM(CASE WHEN feedback=-1 THEN 1 ELSE 0 END) AS poor "
                "FROM requests"
            ).fetchone()
            distribution = conn.execute(
                "SELECT selected_model AS model, COUNT(*) AS n "
                "FROM requests GROUP BY selected_model ORDER BY n DESC"
            ).fetchall()
            recent = conn.execute(
                "SELECT * FROM requests ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()

        total = totals["total"] or 0
        successes = totals["successes"] or 0
        total_cost = totals["total_cost"] or 0.0
        baseline_cost = totals["baseline_cost"] or 0.0
        savings = max(0.0, baseline_cost - total_cost)
        savings_pct = (savings / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

        return {
            "total_requests": total,
            "successful_requests": int(successes),
            "success_rate": (successes / total) if total else 0.0,
            "average_latency_ms": (totals["avg_latency"] or 0.0),
            "average_complexity": (totals["avg_complexity"] or 0.0),
            "total_estimated_cost_usd": total_cost,
            "baseline_cost_usd": baseline_cost,
            "estimated_savings_usd": savings,
            "savings_percent": savings_pct,
            "model_distribution": [
                {"model": r["model"], "count": r["n"]} for r in distribution
            ],
            "feedback_good": int(totals["good"] or 0),
            "feedback_poor": int(totals["poor"] or 0),
            "recent_requests": [self._to_history_row(r) for r in recent],
        }

    def _to_history_row(self, r: sqlite3.Row) -> HistoryRow:
        return HistoryRow(
            id=r["id"],
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(r["timestamp"])),
            query=r["query"],
            task_type=r["task_type"],
            complexity=r["complexity"],
            selected_model=r["selected_model"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            estimated_cost_usd=r["estimated_cost"],
            latency_ms=r["latency_ms"],
            success=bool(r["success"]),
            feedback=r["feedback"],
        )

    def recent_requests(self, limit: int = 20) -> List[HistoryRow]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._to_history_row(r) for r in rows]


tracker = Tracker(settings.database_path)