"""Mock adapter: Deterministic, realistic placeholder simulation for demo mode.

Used when real provider credentials are absent or in offline demo mode.
Provides accurate self vs switch analyzer responses and rich content responses.
"""

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, List, Optional

from ..schemas import ChatMessage
from .base import LLMAdapter, LLMResult, StreamChunk

if TYPE_CHECKING:
    from ..registry import ModelSpec

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
        "Here is the structured mathematical solution:\n\n"
        "1. Define the system of equations based on given constraints.\n"
        "2. Substitute terms to isolate the primary variable.\n"
        "3. Verify edge cases and boundary conditions.\n"
        "4. Conclusion: The derived analytical solution is consistent across all domains."
    ),
    "reasoning": (
        "Let's evaluate the problem systematically:\n\n"
        "1. **Core Trade-offs**: Latency vs. Cost vs. Quality.\n"
        "2. **Decision Matrix**: For high-concurrency read operations, caching at the edge delivers 95% latency reduction.\n"
        "3. **Recommendation**: Implement hierarchical tiering with fallback failovers to balance system throughput."
    ),
    "general": (
        "Here is a clear and concise explanation for your question.\n\n"
        "If you would like more details on any specific aspect, feel free to ask!"
    ),
}

ANALYZER_DECISIONS = {
    # Simple queries -> self
    "hi": {
        "answer_mode": "self", "task_type": "factual", "complexity": "low", "complexity_score": 0.1,
        "reasoning_required": False, "coding_required": False, "context_required": False,
        "target_tier": "fast", "target_provider": "gemini", "target_model": None,
        "reason": "Simple greeting answered directly by base model in self-mode.",
        "answer": "Hello! How can I help you today?"
    },
    "hello": {
        "answer_mode": "self", "task_type": "factual", "complexity": "low", "complexity_score": 0.1,
        "reasoning_required": False, "coding_required": False, "context_required": False,
        "target_tier": "fast", "target_provider": "gemini", "target_model": None,
        "reason": "Simple greeting answered directly by base model in self-mode.",
        "answer": "Hello! How can I help you today?"
    },
    "hey": {
        "answer_mode": "self", "task_type": "factual", "complexity": "low", "complexity_score": 0.1,
        "reasoning_required": False, "coding_required": False, "context_required": False,
        "target_tier": "fast", "target_provider": "gemini", "target_model": None,
        "reason": "Simple greeting answered directly by base model.",
        "answer": "Hey there! What can I help you with today?"
    },
    "what is 5+5": {
        "answer_mode": "self", "task_type": "factual", "complexity": "low", "complexity_score": 0.1,
        "reasoning_required": False, "coding_required": False, "context_required": False,
        "target_tier": "fast", "target_provider": "gemini", "target_model": None,
        "reason": "Simple arithmetic question answered directly by base model.",
        "answer": "5 + 5 = 10"
    },
    "what is html": {
        "answer_mode": "self", "task_type": "factual", "complexity": "low", "complexity_score": 0.2,
        "reasoning_required": False, "coding_required": False, "context_required": False,
        "target_tier": "fast", "target_provider": "gemini", "target_model": None,
        "reason": "Simple factual question answered directly by base model.",
        "answer": "HTML (HyperText Markup Language) is the standard markup language used to structure web pages and their content."
    },
    # Complex queries -> switch
    "debug": {
        "answer_mode": "switch", "task_type": "coding", "complexity": "high", "complexity_score": 0.85,
        "reasoning_required": True, "coding_required": True, "context_required": False,
        "target_tier": "coding", "target_provider": "groq", "target_model": "qwen/qwen3.6-27b",
        "reason": "Debugging code requires specialized high-performance coding model.",
        "answer": None
    },
    "react": {
        "answer_mode": "switch", "task_type": "coding", "complexity": "high", "complexity_score": 0.82,
        "reasoning_required": True, "coding_required": True, "context_required": False,
        "target_tier": "coding", "target_provider": "groq", "target_model": "qwen/qwen3.6-27b",
        "reason": "Debugging React state & render lifecycle requires specialized coding model.",
        "answer": None
    },
    "distributed database": {
        "answer_mode": "switch", "task_type": "system_architecture", "complexity": "high", "complexity_score": 0.92,
        "reasoning_required": True, "coding_required": False, "context_required": False,
        "target_tier": "reasoning", "target_provider": "groq", "target_model": "openai/gpt-oss-120b",
        "reason": "Distributed database system architecture requires powerful reasoning capability.",
        "answer": None
    },
    "binary search": {
        "answer_mode": "switch", "task_type": "coding", "complexity": "medium", "complexity_score": 0.70,
        "reasoning_required": True, "coding_required": True, "context_required": False,
        "target_tier": "coding", "target_provider": "groq", "target_model": "qwen/qwen3.6-27b",
        "reason": "Algorithm implementation requires specialized coding model.",
        "answer": None
    },
}


class MockAdapter(LLMAdapter):
    """Deterministic simulated adapter for offline or test execution."""
    provider = "mock"

    def supports_streaming(self) -> bool:
        return True

    def _is_analyzer_call(self, model: "ModelSpec", messages: List[ChatMessage], json_mode: bool) -> bool:
        if getattr(model, "tier", "") == "analyzer" or json_mode:
            return True
        for m in messages:
            if m.role == "system" and any(k in m.content for k in ("ANALYZER", "ROUTING", "JSON")):
                return True
        return False

    def _extract_user_query(self, messages: List[ChatMessage]) -> str:
        if not messages:
            return ""
        for m in reversed(messages):
            if m.role == "user":
                content = m.content
                if "USER MESSAGE:" in content:
                    return content.split("USER MESSAGE:", 1)[1].strip()
                if "USER QUERY:" in content:
                    return content.split("USER QUERY:", 1)[1].strip()
                return content.strip()
        return messages[-1].content.strip()

    def _get_analyzer_decision(self, query: str, has_history: bool = False) -> dict:
        q_lower = query.lower().strip()

        for key, dec in ANALYZER_DECISIONS.items():
            if len(key) <= 4:
                if re.search(rf"\b{re.escape(key)}\b", q_lower):
                    d = dec.copy()
                    d["context_required"] = has_history
                    return d
            else:
                if key in q_lower:
                    d = dec.copy()
                    d["context_required"] = has_history
                    return d

        # Complex coding keywords
        if any(k in q_lower for k in ("python", "code", "function", "algorithm", "dijkstra", "optimize", "sql", "bug", "implement")):
            return {
                "answer_mode": "switch",
                "task_type": "coding",
                "complexity": "high",
                "complexity_score": 0.85,
                "reasoning_required": True,
                "coding_required": True,
                "context_required": has_history,
                "target_tier": "coding",
                "target_provider": "groq",
                "target_model": "qwen/qwen3.6-27b",
                "reason": "Coding task requires high-accuracy coding model.",
                "answer": None,
            }

        # Complex reasoning / math / architecture keywords
        if any(k in q_lower for k in ("proof", "theorem", "architecture", "system design", "distributed", "tradeoff", "latency vs cost")):
            return {
                "answer_mode": "switch",
                "task_type": "reasoning",
                "complexity": "high",
                "complexity_score": 0.90,
                "reasoning_required": True,
                "coding_required": False,
                "context_required": has_history,
                "target_tier": "reasoning",
                "target_provider": "groq",
                "target_model": "openai/gpt-oss-120b",
                "reason": "Complex architectural or mathematical reasoning requires reasoning model.",
                "answer": None,
            }

        # Short query (< 50 chars) without complex keywords -> self mode
        if len(query) < 50:
            return {
                "answer_mode": "self",
                "task_type": "factual",
                "complexity": "low",
                "complexity_score": 0.15,
                "reasoning_required": False,
                "coding_required": False,
                "context_required": has_history,
                "target_tier": "fast",
                "target_provider": "gemini",
                "target_model": None,
                "reason": "Simple query answered directly by base model in self-mode.",
                "answer": "This is a direct answer from the Base Analyzer model.",
            }

        return {
            "answer_mode": "switch",
            "task_type": "general",
            "complexity": "medium",
            "complexity_score": 0.60,
            "reasoning_required": False,
            "coding_required": False,
            "context_required": has_history,
            "target_tier": "fast",
            "target_provider": "gemini",
            "target_model": None,
            "reason": "Query routed to fast general model for comprehensive response.",
            "answer": None,
        }

    async def generate(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResult:
        t0 = time.perf_counter()
        simulated_delay = min(0.05, getattr(model, "expected_latency_ms", 100) / 4000.0)
        await asyncio.sleep(simulated_delay)

        is_analyzer = self._is_analyzer_call(model, messages, json_mode)
        if is_analyzer:
            query = self._extract_user_query(messages)
            has_history = any("CONVERSATION HISTORY:" in m.content or "HISTORY" in m.content for m in messages)
            decision = self._get_analyzer_decision(query, has_history)
            reply = json.dumps(decision)
            tokens_in = max(1, sum(len(m.content) for m in messages) // 4) + 15
            tokens_out = max(1, len(reply) // 4)
            reasoning_content = None
        else:
            query = self._extract_user_query(messages)
            q_lower = query.lower()

            if "react" in q_lower or "render" in q_lower or "debug" in q_lower:
                body = TASK_ANSWERS["coding"]
            elif "database" in q_lower or "distributed" in q_lower or "architect" in q_lower:
                body = TASK_ANSWERS["architecture"]
            elif "binary search" in q_lower or "search" in q_lower:
                body = TASK_ANSWERS["binary_search"]
            elif "math" in q_lower or "calculate" in q_lower:
                body = TASK_ANSWERS["math"]
            elif "reason" in q_lower or "tradeoff" in q_lower:
                body = TASK_ANSWERS["reasoning"]
            else:
                body = TASK_ANSWERS["general"]

            reply = body
            reasoning_content = "Analyzing constraints and optimal implementation strategy..."
            tokens_in = max(1, sum(len(m.content) for m in messages) // 4) + 15
            tokens_out = max(1, len(reply) // 4)

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return LLMResult(
            content=reply,
            text=reply,
            reasoning_content=reasoning_content,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            model_id=model.model_id,
            usage_source="demo",
            ttft_ms=latency_ms,
        )

    async def stream_chunks(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chunks with realistic word delta and reasoning."""
        res = await self.generate(model, messages, **kwargs)
        if res.reasoning_content:
            yield StreamChunk(reasoning_text=res.reasoning_content)

        words = res.content.split(" ")
        for i in range(0, len(words), 4):
            piece = " ".join(words[i:i + 4])
            if i + 4 < len(words):
                piece += " "
            yield StreamChunk(text=piece)
            await asyncio.sleep(0.01)

        yield StreamChunk(
            text="",
            is_final=True,
            tokens_in=res.input_tokens,
            tokens_out=res.output_tokens,
            latency_ms=res.latency_ms,
        )