"""Camada de IA trocável: Gemini (padrão) ou Claude (Anthropic).

Secrets:
    LLM_PROVIDER = "gemini" | "anthropic"
    [gemini]    api_key, model
    [anthropic] api_key, model
"""
from __future__ import annotations

import json
import re

from core import config


class LLMError(RuntimeError):
    pass


def _gemini(system: str, prompt: str, want_json: bool, temperature: float) -> str:
    from google import genai
    from google.genai import types

    key = config.get("api_key", section="gemini") or config.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("Chave do Gemini não configurada ([gemini] api_key).")
    model = config.get("model", section="gemini") or "gemini-2.5-pro"
    client = genai.Client(api_key=key)
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature, max_output_tokens=32000,
        response_mime_type="application/json" if want_json else "text/plain",
    )
    resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
    return resp.text or ""


def _anthropic(system: str, prompt: str, want_json: bool, temperature: float) -> str:
    import anthropic

    key = config.get("api_key", section="anthropic") or config.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("Chave da Anthropic não configurada ([anthropic] api_key).")
    model = config.get("model", section="anthropic") or "claude-sonnet-5-5"
    client = anthropic.Anthropic(api_key=key)
    if want_json:
        prompt += "\n\nResponda somente com o JSON, sem texto antes ou depois e sem bloco de código."
    with client.messages.stream(model=model, max_tokens=32000, temperature=temperature, system=system,
                                messages=[{"role": "user", "content": prompt}]) as stream:
        msg = stream.get_final_message()
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


_BACKENDS = {"gemini": _gemini, "anthropic": _anthropic}

# Permite injetar uma função fake nos testes: llm.OVERRIDE = lambda system, prompt, want_json: "..."
OVERRIDE = None


def complete(system: str, prompt: str, want_json: bool = False, temperature: float = 0.4) -> str:
    if OVERRIDE:
        return OVERRIDE(system, prompt, want_json)
    provider = (config.LLM_PROVIDER or "gemini").lower()
    if provider not in _BACKENDS:
        raise LLMError(f"Provedor de IA desconhecido: {provider}")
    return _BACKENDS[provider](system, prompt, want_json, temperature)


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise LLMError("A IA não devolveu um JSON válido. Tente gerar novamente.")


def complete_json(system: str, prompt: str, temperature: float = 0.3) -> dict:
    return parse_json(complete(system, prompt, want_json=True, temperature=temperature))
