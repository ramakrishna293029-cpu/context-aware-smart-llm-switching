"""Mock adapter: deterministic placeholder responses for demo mode.

Used only when real provider credentials are absent (demo models are
clearly labelled `demo_mode`). Responses are honest placeholders, not
disguised as real LLM output. Latency is simulated from the model's
expected latency so the demo metrics behave realistically.
"""

import asyncio
import random
from typing import List

from ..registry import ModelSpec
from ..schemas import ChatMessage
from .base import LLMAdapter, LLMResult

TASK_ANSWERS = {
    "coding": (
        "Here is a straightforward implementation you could use:\n\n"
        "```python\ndef solve(problem):\n"
        "    # parse the request and apply the straightforward approach\n"
        "    return result\n```\n\n"
        "For more involved cases I would recommend structuring it with "
        "clear input validation and a few unit tests."
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
    "creative": (
        "Here is a first draft angle: open with a hook that names the "
        "core tension, develop it in three beats, and close with a "
        "punchline that circles back to the opening."
    ),
    "factual": (
        "In short: this is a common question with a well-documented "
        "answer. The essential facts are the ones people rely on most "
        "for everyday use, with plenty of deeper detail available in "
        "reference material."
    ),
    "general": (
        "Here is a concise answer to your question, focused on the "
        "practical essentials. If you want, I can go deeper on any "
        "specific part."
    ),
}


class MockAdapter(LLMAdapter):
    provider = "mock"

    async def generate(self, model: ModelSpec, messages: List[ChatMessage]) -> LLMResult:
        await asyncio.sleep(model.expected_latency_ms * (0.5 + random.random() * 0.5) / 1000.0)
        last = messages[-1].content if messages else ""
        task_text = TASK_ANSWERS.get(model.model_id, TASK_ANSWERS["general"])

        if model.model_id == "demo-fast":
            reply = (
                f"[Demo mode] Quick answer from **{model.name}**:\n\n{task_text}\n\n"
                "_This is a simulated demo response. Configure OPENAI_API_KEY to get real model output._"
            )
        elif model.model_id == "demo-balanced":
            reply = (
                f"[Demo mode] Balanced answer from **{model.name}**:\n\n{task_text}\n\n"
                "_This is a simulated demo response. Configure OPENAI_API_KEY to get real model output._"
            )
        else:
            reply = (
                f"[Demo mode] Detailed answer from **{model.name}**:\n\n{task_text}\n\n"
                "_This is a simulated demo response. Configure OPENAI_API_KEY to get real model output._"
            )

        tokens_in = max(1, len(last) // 4) + 20
        tokens_out = max(1, len(reply) // 4)
        return LLMResult(text=reply, input_tokens=tokens_in, output_tokens=tokens_out)