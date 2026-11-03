"""Optional Gemini / Claude access through one shared ask_json interface."""

from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.error


def strip_json_fence(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


class AIProvider:
    def __init__(self, settings: dict):
        self.settings = settings
        self.quota_stopped = False

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 429:
                wait = 60
                m = re.search(r"retry.*?(\d+)", body, re.IGNORECASE)
                if m:
                    wait = int(m.group(1))
                time.sleep(min(wait, 120))
                raise RuntimeError("AI rate limit (429). Waited, please retry.") from exc
            if "quota" in body.lower() or "exceed" in body.lower():
                self.quota_stopped = True
                raise RuntimeError("AI daily quota reached. Use Offline Brain.") from exc
            raise RuntimeError(f"AI request failed ({exc.code}): {body[:300]}") from exc

    def ask_json(self, system: str, user: str, max_tokens: int = 6000) -> dict | None:
        provider = self.settings.get("ai_provider", "offline")
        if provider == "gemini":
            return self._gemini(system, user, max_tokens)
        if provider == "claude":
            return self._claude(system, user, max_tokens)
        return None

    def _gemini(self, system: str, user: str, max_tokens: int) -> dict | None:
        key = self.settings.get("gemini_api_key", "")
        if not key:
            raise RuntimeError("Gemini API key is missing. Add it in Settings or use Offline Brain.")
        models = [self.settings.get("gemini_model", "gemini-flash-latest"),
                  self.settings.get("gemini_fallback_model", "gemini-flash-lite-latest")]
        last_exc = None
        for model in dict.fromkeys(models):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
            }
            try:
                data = self._post(url, payload, {"Content-Type": "application/json"})
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(strip_json_fence(text))
            except Exception as exc:
                last_exc = exc
                if "503" in str(exc) or "overloaded" in str(exc).lower():
                    continue  # lite-model fallback
                raise
        raise RuntimeError(f"Gemini failed: {last_exc}")

    def _claude(self, system: str, user: str, max_tokens: int) -> dict | None:
        key = self.settings.get("claude_api_key", "")
        if not key:
            raise RuntimeError("Claude API key is missing. Add it in Settings or use Offline Brain.")
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": self.settings.get("claude_model", "claude-sonnet-4-5"),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._post(url, payload, {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        })
        text = "".join(b.get("text", "") for b in data.get("content", []))
        return json.loads(strip_json_fence(text))
