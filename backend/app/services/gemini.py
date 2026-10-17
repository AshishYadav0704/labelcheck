"""Google Gemini provider (REST, no SDK). See ai.py for what the AI is allowed to do."""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any

import requests

from ..config import Settings
from ..models import CATEGORIES
from .ai import (EXPLANATION_PROMPT, EXPLANATION_SCHEMA, EXTRACTION_PROMPT, AIError, extraction_schema,
                 language_name)

log = logging.getLogger("labelcheck.gemini")

EXTRACTION_SCHEMA = extraction_schema(CATEGORIES)


class GeminiError(AIError):
    """Raised when Gemini cannot produce a usable answer."""


class GeminiClient:
    provider = "gemini"

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.gemini_api_key)

    @property
    def model(self) -> str:
        return self.settings.gemini_model

    def _url(self) -> str:
        return f"{self.settings.gemini_base_url}/models/{self.settings.gemini_model}:generateContent"

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"x-goog-api-key": self.settings.gemini_api_key, "Content-Type": "application/json"}
        last_error = "unknown error"
        for attempt in range(3):
            try:
                resp = self.session.post(self._url(), json=body, headers=headers, timeout=self.settings.ai_timeout_s)
            except requests.RequestException as exc:
                last_error = f"network error: {exc.__class__.__name__}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                raise GeminiError("The AI service is busy (quota reached). Please try again in a minute.", 503)
            if resp.status_code in (500, 502, 503, 504):
                last_error = f"Gemini HTTP {resp.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            # 400/401/403/404: configuration or request problem, retrying will not help.
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")[:300]
            except ValueError:
                pass
            log.error("Gemini request failed: %s %s", resp.status_code, detail)
            raise GeminiError(f"AI service rejected the request ({resp.status_code}).", 502 if resp.status_code != 400 else 400)
        raise GeminiError(f"AI service unavailable ({last_error}).", 503)

    @staticmethod
    def _text(response: dict[str, Any]) -> str:
        feedback = response.get("promptFeedback", {})
        if feedback.get("blockReason"):
            raise GeminiError("The AI service declined to read this image.", 422)
        candidates = response.get("candidates") or []
        if not candidates:
            raise GeminiError("The AI service returned no answer.", 502)
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise GeminiError("The AI service returned an empty answer.", 502)
        return text

    @staticmethod
    def _json(text: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise GeminiError("The AI service returned unreadable data.", 502) from exc
        if not isinstance(data, dict):
            raise GeminiError("The AI service returned unexpected data.", 502)
        return data

    def _generate_json(self, parts: list[dict[str, Any]], schema: dict[str, Any], temperature: float) -> dict[str, Any]:
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "response_mime_type": "application/json",
                "response_schema": schema,
            },
        }
        try:
            return self._json(self._text(self._post(body)))
        except GeminiError as exc:
            if exc.status != 400:
                raise
            # Some model versions reject parts of a schema; retry asking for plain JSON.
            log.warning("Gemini rejected the response schema; retrying without it.")
            body["generationConfig"].pop("response_schema")
            return self._json(self._text(self._post(body)))

    def extract_label(self, images: list[tuple[bytes, str]]) -> dict[str, Any]:
        if not self.enabled:
            raise GeminiError("Label reading is not configured on this server (GEMINI_API_KEY missing).", 503)
        parts: list[dict[str, Any]] = [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}} for data, mime in images
        ]
        parts.append({"text": EXTRACTION_PROMPT})
        return self._generate_json(parts, EXTRACTION_SCHEMA, temperature=0.0)

    def explain(self, facts: dict[str, Any], language: str) -> dict[str, Any]:
        if not self.enabled:
            raise GeminiError("Explanations are not configured (GEMINI_API_KEY missing).", 503)
        prompt = EXPLANATION_PROMPT.format(language=language_name(language),
                                           facts=json.dumps(facts, ensure_ascii=False, indent=1))
        return self._generate_json([{"text": prompt}], EXPLANATION_SCHEMA, temperature=0.3)
