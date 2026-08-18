"""Mock adapter: deterministic placeholder responses for demo mode.

Used only when real provider credentials are absent (demo models are
clearly labelled `demo_mode`). Responses are honest placeholders, not
disguised as real LLM output. Latency is simulated from the model's
expected latency so the demo metrics behave realistically.
"""

import asyncio
import json
import random
import re
import time
from typing import AsyncIterator, List

from ..registry import ModelSpec
from ..schemas import ChatMessage
from .base import LLMAdapter, LLMResult

TASK_ANSWERS = {
    "coding": (
        "Here is the solution to fix the React infinite render issue:\n\n"
        "```jsx\nimport React, { useState, useEffect } from 'react';\n\n"
        "export function DataViewer({ dataId }) {\n"
        "  const [data, setData] = useState(null);\n\n"
        "  useEffect(() => {\n"
        "    let isMounted = true;\n"
        "    async function loadData() {\n"
        "      const res = await fetchData(dataId);\n"
        "      if (isMounted) setData(res);\n"
        "    }\n"
        "    loadData();\n"
        "    return () => { isMounted = false; };\n"
        "  }, [dataId]); // Include dataId in dependency array to avoid infinite renders\n\n"
        "  return <div>{data ? <span>{data.title}</span> : 'Loading...'}</div>;\n"
        "}\n```\n\n"
        "**Root Cause**: Updating state inside `useEffect` without a dependency array triggers a re-render after every update, creating an infinite loop."
    ),
    "architecture": (
        "### Fault-Tolerant Distributed Database Architecture\n\n"
        "1. **Consensus & Replication**: Multi-Raft consensus across independent availability zones with quorum writes (majority agreement).\n"
        "2. **Storage Engine**: LSM-Tree based local storage (e.g., RocksDB) for high-throughput write absorption and background compaction.\n"
        "3. **Partitioning & Sharding**: Range-based or consistent hashing with virtual nodes to balance partitions evenly across nodes.\n"
        "4. **Transaction Protocol**: Distributed 2-Phase Commit (2PC) with Spanner-style TrueTime / Hybrid Logical Clocks (HLC) for serializable ACID transactions.\n"
        "5. **High Availability & Failover**: Active heartbeat leases with automatic leader election (< 3s failover) and anti-entropy repair via Merkle trees."
    ),
    "binary_search": (
        "Here is an optimal Binary Search implementation in Python:\n\n"
        "```python\ndef binary_search(arr: list[int], target: int) -> int:\n"
        "    left, right = 0, len(arr) - 1\n"
        "    while left <= right:\n"
        "        mid = left + (right - left) // 2\n"
        "        if arr[mid] == target:\n"
        "            return mid\n"
        "        elif arr[mid] < target:\n"
        "            left = mid + 1\n"
        "        else:\n"
        "            right = mid - 1\n"
        "    return -1  # Target not found\n```\n\n"
        "**Time Complexity**: O(log n) · **Space Complexity**: O(1)"
    ),
    "math": (
        "You can break this problem down into smaller steps, verify each "
        "step numerically, and then combine the results. For a precise "
        "answer a symbolic solver or careful hand derivation is the way "
        "to go."
    ),
    "reasoning": (
        "Let's weigh the options. The key trade-offs are correctness vs "
        "complexity, and cost vs latency. Given the constraints, the "
        "balanced recommendation is to start with the simpler approach, "
        "measure it, and only escalate if measurements justify it."
    ),
    "general": (
        "Here is a concise answer to your question, focused on the "
        "practical essentials. If you want, I can go deeper on any "
        "specific part."
    ),
}

ANALYZER_DECISIONS = {
    # Simple queries -> self
    "hi": {"answer_mode": "self", "context_relevant": False, "reason": "Simple greeting answered directly",
           "target_model": None, "task_type": "greeting", "complexity": 0.1,
           "answer": "Hello! How can I help you today?"},
    "hello": {"answer_mode": "self", "context_relevant": False, "reason": "Simple greeting answered directly",
              "target_model": None, "task_type": "greeting", "complexity": 0.1,
              "answer": "Hello! How can I help you today?"},
    "what is 5+5": {"answer_mode": "self", "context_relevant": False, "reason": "Simple arithmetic answered directly",
                    "target_model": None, "task_type": "math", "complexity": 0.1,
                    "answer": "5 + 5 = 10"},
    "what is html": {"answer_mode": "self", "context_relevant": False, "reason": "Simple factual question answered directly",
                     "target_model": None, "task_type": "factual", "complexity": 0.2,
                     "answer": "HTML (HyperText Markup Language) is the standard markup language used for creating web pages and web applications."},
    # Complex queries -> switch
    "debug": {"answer_mode": "switch", "context_relevant": False, "reason": "Debugging requires stronger coding & reasoning capability",
              "target_model": "demo-powerful", "task_type": "coding", "complexity": 0.85,
              "answer": None},
    "react": {"answer_mode": "switch", "context_relevant": False, "reason": "Debugging React re-renders requires specialized coding model",
              "target_model": "demo-powerful", "task_type": "coding", "complexity": 0.8,
              "answer": None},
    "re-renders": {"answer_mode": "switch", "context_relevant": False, "reason": "Debugging React infinite renders requires specialized coding model",
                   "target_model": "demo-powerful", "task_type": "coding", "complexity": 0.8,
                   "answer": None},
    "distributed database": {"answer_mode": "switch", "context_relevant": False, "reason": "Distributed systems architecture requires powerful reasoning model",
                             "target_model": "demo-powerful", "task_type": "technical", "complexity": 0.9,
                             "answer": None},
    "binary search": {"answer_mode": "switch", "context_relevant": True, "reason": "Algorithm implementation requires specialized coding model",
                      "target_model": "demo-powerful", "task_type": "coding", "complexity": 0.7,
                      "answer": None},
}


class MockAdapter(LLMAdapter):
    provider = "mock"

    def _is_analyzer_call(self, messages: List[ChatMessage]) -> bool:
        """Check if this is an analyzer LLM call (contains ROUTING ANALYZER in system prompt)."""
        for m in messages:
            if m.role == "system" and "ROUTING ANALYZER" in m.content:
                return True
        return False

    def _extract_user_query(self, messages: List[ChatMessage]) -> str:
        """Extract the user query from the last message."""
        if not messages:
            return ""
        last = messages[-1].content if messages else ""
        if "USER MESSAGE: " in last:
            return last.split("USER MESSAGE: ", 1)[1].strip().lower()
        return last.lower()

    def _get_analyzer_decision(self, query: str, has_history: bool = False) -> dict:
        """Get analyzer decision based on query intent."""
        query_lower = query.lower()
        for keyword, decision in ANALYZER_DECISIONS.items():
            if len(keyword) <= 4:
                if re.search(rf'\b{re.escape(keyword)}\b', query_lower):
                    d = decision.copy()
                    d["context_relevant"] = has_history
                    return d
            else:
                if re.search(rf'\b{re.escape(keyword)}\b', query_lower):
                    d = decision.copy()
                    d["context_relevant"] = has_history
                    return d
        # Detect follow-ups: short query with history = follow-up needing context
        is_followup = has_history and len(query) < 80 and not any(re.search(rf'\b{re.escape(k)}\b', query_lower) for k in ["debug", "distributed", "architecture", "implement", "design", "prove", "optimize", "re-renders"])
        if is_followup:
            return {"answer_mode": "switch", "context_relevant": True, "reason": "Follow-up question requiring previous conversation context",
                    "target_model": "demo-powerful", "task_type": "coding", "complexity": 0.6,
                    "answer": None}
        if len(query) < 50 and not any(re.search(rf'\b{re.escape(k)}\b', query_lower) for k in ["debug", "distributed", "architecture", "implement", "design", "prove", "optimize", "re-renders", "react", "binary search"]):
            return {"answer_mode": "self", "context_relevant": has_history, "reason": "Simple question answered directly by Analyzer LLM",
                    "target_model": None, "task_type": "factual", "complexity": 0.2,
                    "answer": "This is a direct answer from the Analyzer LLM to a simple request."}
        return {"answer_mode": "switch", "context_relevant": has_history, "reason": "Complex request switched to specialized model",
                "target_model": "demo-powerful", "task_type": "technical", "complexity": 0.75,
                "answer": None}

    async def generate(self, model: ModelSpec, messages: List[ChatMessage]) -> LLMResult:
        t0 = time.perf_counter()
        await asyncio.sleep(model.expected_latency_ms * (0.5 + random.random() * 0.5) / 1000.0)

        if self._is_analyzer_call(messages):
            # Return structured JSON decision for analyzer
            query = self._extract_user_query(messages)
            has_history = any("CONVERSATION HISTORY:" in m.content for m in messages)
            decision = self._get_analyzer_decision(query, has_history)
            reply = json.dumps(decision)
            tokens_in = max(1, len(str(messages)) // 4) + 20
            tokens_out = max(1, len(reply) // 4)
        else:
            # Regular response
            last = messages[-1].content if messages else ""
            last_lower = last.lower()
            if "react" in last_lower or "render" in last_lower or "debug" in last_lower:
                task_text = TASK_ANSWERS["coding"]
            elif "database" in last_lower or "distributed" in last_lower or "architect" in last_lower:
                task_text = TASK_ANSWERS["architecture"]
            elif "binary search" in last_lower:
                task_text = TASK_ANSWERS["binary_search"]
            else:
                task_text = TASK_ANSWERS.get("general")

            if model.model_id == "demo-fast":
                reply = (
                    f"[Demo mode] Quick answer from **{model.name}**:\n\n{task_text}\n\n"
                    "_This is a simulated demo response. Configure a real API key in `.env` to get real model output._"
                )
            elif model.model_id == "demo-balanced":
                reply = (
                    f"[Demo mode] Balanced answer from **{model.name}**:\n\n{task_text}\n\n"
                    "_This is a simulated demo response. Configure a real API key in `.env` to get real model output._"
                )
            else:
                reply = (
                    f"[Demo mode] Detailed answer from **{model.name}**:\n\n{task_text}\n\n"
                    "_This is a simulated demo response. Configure a real API key in `.env` to get real model output._"
                )
            tokens_in = max(1, len(last) // 4) + 20
            tokens_out = max(1, len(reply) // 4)

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return LLMResult(text=reply, input_tokens=tokens_in, output_tokens=tokens_out,
                         usage_source="demo", ttft_ms=latency_ms)

    async def stream(self, model: ModelSpec, messages: List[ChatMessage]) -> AsyncIterator[str]:
        """Chunked demo stream: same simulated latency, then word chunks."""
        result = await self.generate(model, messages)
        words = result.text.split(" ")
        for i in range(0, len(words), 3):
            yield " ".join(words[i:i + 3]) + " "
            await asyncio.sleep(0.02)  # typing effect, demo only