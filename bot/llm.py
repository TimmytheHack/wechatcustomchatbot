from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import EnvConfig, Settings
from .models import LLMOutput, LLMPlanning, LLMReply

SYSTEM_PROMPT = """
You are a WeChat assistant. Respond ONLY with valid JSON that matches the schema provided.
Rules:
- Keep replies short and natural.
- Do not schedule unless proactive is enabled and it improves UX.
- Do not schedule generic spam.
- Prefer replace_all when rescheduling.
- Never schedule inside quiet hours; if needed, schedule at the next allowed time.
- At most one scheduled item.
- If no schedule, set planning.action to "none" and planning.items to [].
""".strip()

SCHEMA_HINT = {
    "reply": {"text": "string", "send_gif": True, "gif_tag": "string|null"},
    "planning": {
        "action": "none|cancel_all|replace_all|append",
        "items": [
            {
                "send_at": "2026-01-18T21:30:00-05:00",
                "text": "string",
                "gif_tag": "string|null",
                "reason": "string",
                "confidence": 0.0,
            }
        ],
    },
    "memory_updates": [
        {"type": "preference|fact|none", "key": "string", "value": "string"}
    ],
}


@dataclass
class LLMContext:
    incoming_text: str
    local_time: str
    timezone: str
    settings: dict[str, Any]
    summary: str
    recent_messages: list[dict[str, Any]]
    pending_plans: list[dict[str, Any]]
    counters: dict[str, Any]


class LLMClient:
    def __init__(self, env: EnvConfig, settings: Settings) -> None:
        self._env = env
        self._settings = settings
        self._log = logging.getLogger("bot.llm")

    def is_configured(self) -> bool:
        return bool(self._env.llm_base_url and self._env.llm_api_key and self._env.llm_model)

    def generate_response(self, context: LLMContext) -> LLMOutput:
        if not self.is_configured():
            return self._dummy_response(context)

        payload = {
            "model": self._env.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._build_user_prompt(context)},
            ],
            "temperature": 0.4,
        }
        url = self._env.llm_base_url.rstrip("/") + "/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self._env.llm_api_key}"}
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            self._log.warning("LLM call failed, falling back to dummy: %s", exc)
            return self._dummy_response(context)

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = self._parse_output(content)
        if parsed is None:
            self._log.warning("LLM output invalid JSON, falling back to dummy")
            return self._dummy_response(context)
        return parsed

    def _build_user_prompt(self, context: LLMContext) -> str:
        payload = {
            "schema": SCHEMA_HINT,
            "context": {
                "local_time": context.local_time,
                "timezone": context.timezone,
                "settings": context.settings,
                "summary": context.summary,
                "recent_messages": context.recent_messages,
                "pending_plans": context.pending_plans,
                "policy_counters": context.counters,
                "incoming_text": context.incoming_text,
            },
        }
        return json.dumps(payload, ensure_ascii=True)

    def _parse_output(self, content: str) -> LLMOutput | None:
        raw = content.strip()
        if not raw:
            return None
        json_str = self._extract_json(raw)
        if not json_str:
            return None
        try:
            return LLMOutput.model_validate_json(json_str)
        except Exception:
            return None

    @staticmethod
    def _extract_json(content: str) -> str | None:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return content[start : end + 1]

    @staticmethod
    def _dummy_response(context: LLMContext) -> LLMOutput:
        text = context.incoming_text.strip()
        if not text:
            text = "Got it."
        reply = LLMReply(text=f"(dummy) {text}", send_gif=False, gif_tag=None)
        return LLMOutput(reply=reply, planning=LLMPlanning(action="none", items=[]))
