"""Optional LLM layer.

Guardrail (DOCUMENT 04 - section 18, DOCUMENT 05 - section 6):
the LLM may *propose* hypotheses and phrase the narrative, but it can never
decide the root cause, invent evidence or write to DataHub. Every LLM proposal
is re-scored by the deterministic engine against evidence ids that must exist.

When LLM_PROVIDER=none the agent is fully deterministic and the demo still runs.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are the reasoning assistant of DATAFORENSIC AI, a data incident investigator.
You are given the DataHub context of an incident and a list of EVIDENCE items with stable ids.

Rules you must follow:
- Never invent evidence. Only cite evidence ids from the list you received.
- Never assert a root cause as a fact. You propose candidate explanations only.
- A hypothesis with no supporting evidence id is not allowed.
- Answer with JSON only, no prose, no markdown fences.
"""

HYPOTHESIS_INSTRUCTION = """Propose at most 2 ADDITIONAL candidate explanations that are not already
in the existing candidate list. Return JSON of the form:
{"hypotheses": [{"pattern": "UPPER_SNAKE_CASE", "description": "one sentence",
                 "supporting_evidence_ids": ["..."], "contradicting_evidence_ids": ["..."]}]}
If you have nothing to add, return {"hypotheses": []}."""

NARRATIVE_INSTRUCTION = """Write a factual 2 to 3 sentence explanation of the leading hypothesis for a
data engineer. Mention the assets and the mechanism. Do not invent numbers.
Return JSON: {"narrative": "..."}"""


class LLMClient:
    """Small provider-agnostic chat client (Anthropic Messages / OpenAI Chat)."""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 2000,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_tokens = max_tokens

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if self.provider == "anthropic":
            url = f"{(self.base_url or 'https://api.anthropic.com').rstrip('/')}/v1/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            extract = lambda data: "".join(  # noqa: E731
                block.get("text", "") for block in data.get("content", [])
            )
        else:
            url = f"{(self.base_url or 'https://api.openai.com/v1').rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            extract = lambda data: data["choices"][0]["message"]["content"]  # noqa: E731

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            text = extract(response.json())

        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(cleaned.strip())


def build_llm_client() -> LLMClient | None:
    if settings.llm_provider == "none" or not settings.llm_api_key:
        return None
    return LLMClient(
        provider=settings.llm_provider,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_tokens,
    )


class LLMReasoner:
    """Thin wrapper that always degrades gracefully to the deterministic path."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or build_llm_client()

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @property
    def engine_name(self) -> str:
        if not self.client:
            return "deterministic-engine"
        return f"deterministic-engine+{self.client.provider}:{self.client.model}"

    async def propose_hypotheses(
        self, context_summary: dict[str, Any], evidence: list[dict[str, Any]], existing: list[str]
    ) -> list[dict[str, Any]]:
        if not self.client:
            return []
        user = json.dumps(
            {
                "context": context_summary,
                "evidence": evidence,
                "existing_candidates": existing,
                "instruction": HYPOTHESIS_INSTRUCTION,
            },
            default=str,
        )
        try:
            payload = await self.client.complete_json(SYSTEM_PROMPT, user)
            return list(payload.get("hypotheses", []))[:2]
        except Exception as exc:  # noqa: BLE001 - never break the investigation
            logger.warning("llm_hypothesis_proposal_failed", extra={"error": str(exc)[:200]})
            return []

    async def narrate(
        self, root_cause: str, causal_chain: list[dict[str, Any]], evidence: list[dict[str, Any]]
    ) -> str | None:
        if not self.client:
            return None
        user = json.dumps(
            {
                "leading_hypothesis": root_cause,
                "causal_chain": causal_chain,
                "evidence": evidence[:15],
                "instruction": NARRATIVE_INSTRUCTION,
            },
            default=str,
        )
        try:
            payload = await self.client.complete_json(SYSTEM_PROMPT, user)
            narrative = str(payload.get("narrative", "")).strip()
            return narrative or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm_narrative_failed", extra={"error": str(exc)[:200]})
            return None
