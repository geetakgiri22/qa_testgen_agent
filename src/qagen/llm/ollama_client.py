"""Thin Ollama /api/chat client (local only) with health check and robust JSON parsing."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import requests

from ..config import LangSmithSettings, OllamaSettings, load_settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised for any failure talking to Ollama."""


@dataclass
class HealthStatus:
    ok: bool
    server_up: bool
    model_available: bool
    message: str
    models: list[str]


class OllamaClient:
    def __init__(self, settings: OllamaSettings | None = None,
                 langsmith_settings: LangSmithSettings | None = None):
        self.s = settings or load_settings().ollama
        self.langsmith_settings = langsmith_settings or load_settings().langsmith
        self._langsmith_client = None
        self._traceable = None
        if self.langsmith_settings.enabled:
            if not self.langsmith_settings.api_key:
                raise ValueError("LangSmith tracing is enabled but LANGSMITH_API_KEY is not set.")
            from langsmith import Client, agent_address, traceable

            self._langsmith_client = Client(
                api_key=self.langsmith_settings.api_key,
                api_url=self.langsmith_settings.endpoint,
            )
            self._langsmith_address = agent_address(
                self.langsmith_settings.agent_id,
                self.langsmith_settings.agent_environment,
            )
            self._traceable = traceable

    # ---- connectivity -------------------------------------------------
    def health_check(self) -> HealthStatus:
        try:
            r = requests.get(self.s.tags_url, timeout=5)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
        except requests.RequestException as exc:
            log.warning("Ollama unreachable: %s", exc)
            return HealthStatus(False, False, False,
                                f"Ollama is not reachable at {self.s.base_url}. "
                                "Start it with 'ollama serve'.", [])
        wanted = self.s.model
        have = any(m == wanted or (":" not in wanted and m.split(":")[0] == wanted) for m in models)
        if not have:
            return HealthStatus(False, True, False,
                                f"Ollama is running but model '{wanted}' is not installed. "
                                f"Run: ollama pull {wanted}", models)
        return HealthStatus(True, True, True, f"Ollama ready - model '{wanted}' available.", models)

    # ---- chat -----------------------------------------------------------
    def chat(self, system: str, user: str, json_mode: bool = True) -> str:
        messages = [
            {"role": "system", "content": [{"type": "text", "text": system}]},
            {"role": "user", "content": [{"type": "text", "text": user}]},
        ]
        options = {
            "num_ctx": self.s.num_ctx,
            "num_predict": self.s.num_predict,
            "temperature": self.s.temperature,
        }

        def invoke(messages: list[dict], options: dict, use_json: bool) -> dict:
            payload = {
                "model": self.s.model,
                "stream": False,
                "messages": [
                    {
                        "role": message["role"],
                        "content": "\n".join(part["text"] for part in message["content"]
                                             if part.get("type") == "text"),
                    }
                    for message in messages
                ],
                "options": options,
            }
            if use_json:
                payload["format"] = "json"
            try:
                r = requests.post(self.s.chat_url, json=payload, timeout=self.s.timeout)
                r.raise_for_status()
                response = r.json()
                content = strip_think(response["message"]["content"])
            except requests.Timeout as exc:
                raise LLMError(
                    f"Ollama timed out after {self.s.timeout}s. Try fewer requirements per run."
                ) from exc
            except requests.RequestException as exc:
                raise LLMError(f"Ollama request failed: {exc}") from exc
            except (KeyError, ValueError) as exc:
                raise LLMError(f"Unexpected Ollama response: {exc}") from exc

            result = {
                "choices": [{"message": {"role": "assistant", "content": content}}],
            }
            input_tokens = response.get("prompt_eval_count")
            output_tokens = response.get("eval_count")
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                result["usage_metadata"] = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            return result

        if self._traceable is not None:
            traced_invoke = self._traceable(
                invoke,
                run_type="llm",
                name="Ollama Chat",
                client=self._langsmith_client,
                address=self._langsmith_address,
                metadata={"ls_provider": "ollama", "ls_model_name": self.s.model},
                enabled=True,
            )
            result = traced_invoke(messages, options, json_mode)
        else:
            result = invoke(messages, options, json_mode)
        return result["choices"][0]["message"]["content"]

    def chat_json(self, system: str, user: str, retries: int = 1) -> dict | list:
        last: Exception | None = None
        for attempt in range(retries + 1):
            raw = self.chat(system, user, json_mode=True)
            try:
                return extract_json(raw)
            except ValueError as exc:
                last = exc
                log.warning("Invalid JSON from model (attempt %d): %s", attempt + 1, exc)
                user = user + "\nReturn ONLY valid JSON. No prose, no markdown."
        raise LLMError(f"Model did not return valid JSON: {last}")


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    text = _THINK.sub("", text)
    return re.sub(r"^.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_json(text: str):
    """Parse JSON from model text, tolerating code fences and trailing prose."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object found in model output")
