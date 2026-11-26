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
    model = (config.get("model", section="gemini") or "gemini-pro-latest").replace("models/", "")
    # v1beta é a versão da API que aceita modelos preview e os aliases "-latest"
    client = genai.Client(api_key=key, http_options=types.HttpOptions(api_version="v1beta"))
    # 65536 é o máximo de saída dos modelos Gemini atuais; nos modelos com "thinking",
    # o raciocínio interno também conta nesse limite, por isso o valor alto
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature, max_output_tokens=65536,
        response_mime_type="application/json" if want_json else "text/plain",
    )

    def call(contents):
        nonlocal model
        try:
            return client.models.generate_content(model=model, contents=contents, config=cfg)
        except Exception as ex:
            if "404" not in str(ex) and "NOT_FOUND" not in str(ex):
                raise
            # modelo configurado não existe para esta chave: escolhe o melhor disponível
            fallback = _best_gemini_model(client)
            if not fallback:
                raise LLMError(f"Modelo '{model}' indisponível e nenhum modelo Gemini encontrado para esta chave.") from ex
            model = fallback
            return client.models.generate_content(model=model, contents=contents, config=cfg)

    resp = call(prompt)
    text, finish = resp.text or "", _finish(resp)
    # texto cortado por tamanho: pede para continuar de onde parou (até 3 vezes)
    tries = 0
    while finish == "MAX_TOKENS" and not want_json and tries < 3:
        tries += 1
        cont = (f"{prompt}\n\nVocê já escreveu o trecho abaixo, mas ele foi interrompido:\n\n{text}\n\n"
                "Continue EXATAMENTE de onde o texto parou, sem repetir nada do que já foi escrito "
                "e sem comentários. Termine todas as seções da estrutura.")
        resp = call(cont)
        more = resp.text or ""
        text = text.rstrip() + ("" if more.startswith((" ", "\n")) else " ") + more.lstrip(" ")
        finish = _finish(resp)
    _set_finish(finish, model)
    if finish in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "OTHER") and not text.strip():
        raise LLMError(f"O Gemini bloqueou a resposta (motivo: {finish}). Tente gerar de novo.")
    return text


def _finish(resp) -> str:
    try:
        fr = resp.candidates[0].finish_reason
        return getattr(fr, "name", str(fr or "")).replace("FinishReason.", "")
    except Exception:
        return ""


# último motivo de término, para a interface avisar quando o texto vier incompleto
LAST_FINISH = {"reason": "", "model": ""}


def _set_finish(reason: str, model: str):
    LAST_FINISH["reason"], LAST_FINISH["model"] = reason or "", model or ""


FINISH_LABELS = {
    "MAX_TOKENS": "o texto atingiu o limite de tamanho da IA mesmo após 3 continuações",
    "SAFETY": "o Google interrompeu a resposta por filtro de segurança",
    "RECITATION": "o Google interrompeu a resposta por semelhança com textos já publicados na web",
    "PROHIBITED_CONTENT": "o Google interrompeu a resposta por política de conteúdo",
    "OTHER": "o Google interrompeu a resposta sem informar o motivo",
}


def _best_gemini_model(client) -> str:
    """Lista os modelos da chave e prefere: pro estável > pro preview > flash."""
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if actions and "generateContent" not in actions:
            continue
        n = (m.name or "").replace("models/", "")
        if n.startswith("gemini") and not any(x in n for x in ("image", "tts", "audio", "embedding", "live", "lite")):
            names.append(n)

    def score(n):
        ver = [float(x) for x in __import__("re").findall(r"gemini-(\d+(?:\.\d+)?)", n)[:1]] or [0]
        return (2 if "pro" in n else 1 if "flash" in n else 0, ver[0], 0 if "preview" in n or "exp" in n else 1)

    return max(names, key=score) if names else ""


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
    _set_finish("MAX_TOKENS" if msg.stop_reason == "max_tokens" else "STOP", model)
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


_BACKENDS = {"gemini": _gemini, "anthropic": _anthropic}

# Permite injetar uma função fake nos testes: llm.OVERRIDE = lambda system, prompt, want_json: "..."
OVERRIDE = None


def complete(system: str, prompt: str, want_json: bool = False, temperature: float = 0.4) -> str:
    if OVERRIDE:
        _set_finish("STOP", "teste")
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
