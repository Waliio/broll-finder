"""Optional AI providers. Offline Brain is the default and needs no key.

ask_json(system, user) -> dict, shared by Gemini and Claude so the
pipeline never cares which provider is active. Robust JSON parsing,
retries, 503 fallback to the lite Gemini model, 429 waits, daily-quota stop.
"""
from __future__ import annotations

import json
import re
import time

FENCE_RE = re.compile(r"^```(?:json)?|```$", flags=re.M)


def parse_json_robust(text: str) -> dict:
    text = FENCE_RE.sub("", (text or "").strip()).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if starts:
        text = text[min(starts):]
    data = json.loads(text)
    if isinstance(data, list):
        return {"items": data}
    return data


class AIError(Exception):
    pass


class AIProvider:
    def __init__(self, settings: dict):
        self.settings = settings
        self._client = None
        self._last_call = 0.0
        self.gemini_model = settings.get("gemini_model", "gemini-flash-latest")

    def ask_json(self, system: str, user: str, max_tokens: int = 4000) -> dict | None:
        provider = self.settings.get("ai_provider", "offline")
        if provider == "offline":
            raise AIError("Offline Brain is active; AI is not used for this step.")
        call = self._call_gemini if provider == "gemini" else self._call_claude
        system = system + "\n\nRespond with valid JSON only. No markdown, no commentary."
        fallback = self.settings.get("gemini_fallback_model", "gemini-flash-lite-latest")
        for attempt in range(6):
            try:
                return parse_json_robust(call(system, user, max_tokens))
            except (json.JSONDecodeError, ValueError):
                continue
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate" in msg.lower():
                    if "per day" in msg.lower() or "PerDay" in msg:
                        return None
                    time.sleep(60 * (attempt + 1))
                elif "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                    if provider == "gemini" and attempt >= 1 and self.gemini_model != fallback:
                        self.gemini_model = fallback
                    else:
                        time.sleep(20)
                else:
                    time.sleep(10)
        return None

    def _call_gemini(self, system, user, max_tokens):
        if self._client is None:
            from google import genai
            key = self.settings.get("gemini_api_key", "")
            if not key:
                raise AIError("No Gemini key saved. Add one in Settings, or use Offline Brain.")
            self._client = genai.Client(api_key=key)
        from google.genai import types
        wait = 4.5 - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()
        resp = self._client.models.generate_content(
            model=self.gemini_model, contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json",
                max_output_tokens=max(max_tokens, 8000), temperature=0.4))
        return resp.text

    def _call_claude(self, system, user, max_tokens):
        if self._client is None:
            import anthropic
            key = self.settings.get("claude_api_key", "")
            if not key:
                raise AIError("No Claude key saved. Add one in Settings, or use Offline Brain.")
            self._client = anthropic.Anthropic(api_key=key)
        resp = self._client.messages.create(
            model=self.settings.get("claude_model", "claude-sonnet-4-5"),
            max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    def test_key(self) -> bool:
        """One tiny request. Returns True only if the provider answers."""
        try:
            out = self.ask_json("You are a test.", '{"ok": true}', max_tokens=200)
            return bool(out)
        except Exception:
            return False
