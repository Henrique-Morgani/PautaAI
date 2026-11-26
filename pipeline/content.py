"""Geração do texto a partir do briefing revisado."""
from __future__ import annotations

from ai import llm, prompts
from pipeline import validate


def generate(client: dict, focus: str, analysis: dict, extra_instructions: str = "",
             target_words: str = "1200 a 1800", remove_dashes: bool = True) -> str:
    prompt = prompts.content_prompt(client, focus, analysis, extra_instructions, target_words)
    body = llm.complete(prompts.CONTENT_SYSTEM, prompt, temperature=0.6).strip()
    if body.startswith("```"):
        body = body.strip("`").removeprefix("markdown").strip()
    if remove_dashes:
        body = validate.strip_em_dashes(body)
    return body


def rewrite_section(client: dict, focus: str, analysis: dict, body: str, section_heading: str,
                    instruction: str) -> str:
    """Reescreve só uma seção do texto, mantendo o resto igual."""
    prompt = (f"Texto atual em markdown:\n\n{body}\n\n"
              f"Reescreva SOMENTE a seção cujo heading é \"{section_heading}\" (incluindo seus subtítulos), "
              f"seguindo esta instrução: {instruction}\n"
              f"Palavra-chave foco: {focus}. Devolva o texto COMPLETO, com as demais seções idênticas.")
    out = llm.complete(prompts.CONTENT_SYSTEM, prompt, temperature=0.5).strip()
    return validate.strip_em_dashes(out)
