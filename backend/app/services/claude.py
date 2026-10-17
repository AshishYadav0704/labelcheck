"""Anthropic Claude provider (Messages API over REST, no SDK).

Structured output comes from a forced tool call: the model must call a tool
whose input schema is the extraction schema, so the answer is always JSON of
the right shape. See ai.py for what the AI is allowed to do.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import requests

from ..config import Settings
from ..models import CATEGORIES
from .ai import (EXPLANATION_PROMPT, EXPLANATION_SCHEMA, EXTRACTION_PROMPT, AIError, extraction_schema,
                 language_name, to_json_schema)

log = logging.getLogger("labelcheck.claude")

API_VERSION = "2023-06-01"
EXTRACTION_TOOL = {
    "name": "record_label",
    "description": "Record the information read from the food label photos.",
    "input_schema": to_json_schema(extraction_schema(CATEGORIES)),
}
EXPLANATION_TOOL = {
    "name": "write_explanation",
    "description": "Write the plain-language explanation of the report.",
    "input_schema": to_json_schema(EXPLANATION_SCHEMA),
}
RETRYABLE = {500, 502, 503, 504, 529}


class ClaudeError(AIError):
    """Raised when Claude cannot produce a usable answer."""


class ClaudeClient:
    provider = "claude"

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    @property
    def model(self) -> str:
        return self.settings.anthropic_model

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        url = f"{self.settings.anthropic_base_url.rstrip('/')}/v1/messages"
        last_error = "unknown error"
        for attempt in range(3):
            try:
                resp = self.session.post(url, json=body, headers=headers, timeout=self.settings.ai_timeout_s)
            except requests.RequestException as exc:
                last_error = f"network error: {exc.__class__.__name__}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                raise ClaudeError("The AI service is busy (rate limit reached). Please try again in a minute.", 503)
            if resp.status_code in RETRYABLE:
                last_error = f"Claude HTTP {resp.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            detail = ""
            try:
                detail = str(resp.json().get("error", {}).get("message", ""))[:300]
            except ValueError:
                pass
            log.error("Claude request failed: %s %s", resp.status_code, detail)
            raise ClaudeError(f"AI service rejected the request ({resp.status_code}).",
                              400 if resp.status_code in (400, 413) else 502)
        raise ClaudeError(f"AI service unavailable ({last_error}).", 503)

    def _tool_call(self, content: list[dict[str, Any]], tool: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"]},
            "messages": [{"role": "user", "content": content}],
        }
        data = self._post(body)
        stop = data.get("stop_reason")
        if stop == "refusal":
            raise ClaudeError("The AI service declined to read this image.", 422)
        for block in data.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == tool["name"]:
                result = block.get("input")
                if isinstance(result, str):  # defensive: some proxies serialise the input
                    try:
                        result = json.loads(result)
                    except json.JSONDecodeError as exc:
                        raise ClaudeError("The AI service returned unreadable data.", 502) from exc
                if not isinstance(result, dict):
                    raise ClaudeError("The AI service returned unexpected data.", 502)
                if stop == "max_tokens":
                    log.warning("Claude answer hit max_tokens; result may be incomplete.")
                return result
        raise ClaudeError("The AI service returned no structured answer.", 502)

    def extract_label(self, images: list[tuple[bytes, str]]) -> dict[str, Any]:
        if not self.enabled:
            raise ClaudeError("Label reading is not configured on this server (ANTHROPIC_API_KEY missing).", 503)
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": mime,
                                         "data": base64.b64encode(data).decode("ascii")}}
            for data, mime in images
        ]
        content.append({"type": "text", "text": EXTRACTION_PROMPT})
        return self._tool_call(content, EXTRACTION_TOOL, max_tokens=4096)

    def explain(self, facts: dict[str, Any], language: str) -> dict[str, Any]:
        if not self.enabled:
            raise ClaudeError("Explanations are not configured (ANTHROPIC_API_KEY missing).", 503)
        prompt = EXPLANATION_PROMPT.format(language=language_name(language),
                                           facts=json.dumps(facts, ensure_ascii=False, indent=1))
        return self._tool_call([{"type": "text", "text": prompt}], EXPLANATION_TOOL, max_tokens=1500)
