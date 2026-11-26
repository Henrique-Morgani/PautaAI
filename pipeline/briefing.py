"""Pipeline da análise: coleta -> análise da IA -> validação.

collect() junta todos os dados brutos; analyze() chama a IA; os dois são separados para a tela
poder mostrar o progresso por etapa e para permitir regenerar só a análise sem gastar API de novo.
"""
from __future__ import annotations

from typing import Callable

from ai import llm, prompts
from providers import crawler, keywords, serp, sitemap

COUNTRY_TO_HL = {"br": "pt-br", "pt": "pt-pt", "mx": "es-419", "ar": "es-419", "co": "es-419",
                 "cl": "es-419", "es": "es", "us": "en"}


def collect(client: dict, focus: str, manual_secondary: list[str] | None = None,
            ai_overview_manual: str = "", progress: Callable[[str, float], None] | None = None,
            kw_provider: keywords.KeywordProvider | None = None,
            serp_fn=serp.search, crawl_fn=crawler.fetch_many, sitemap_fn=sitemap.fetch_urls) -> dict:
    progress = progress or (lambda *_: None)
    country = (client.get("country") or "br").lower()
    raw: dict = {"manual_secondary": manual_secondary or [], "errors": []}

    progress("Buscando palavras-chave", 0.1)
    try:
        prov = kw_provider or keywords.get_provider()
        raw["keywords"] = keywords.collect_keyword_universe(prov, focus, country, manual_secondary)
        raw["errors"] += raw["keywords"].get("errors", [])
    except Exception as e:
        raw["keywords"] = {"focus": [], "candidates": [], "provider": "erro"}
        raw["errors"].append(f"Palavras-chave: {e}")

    progress("Lendo a SERP", 0.3)
    try:
        raw["serp"] = serp_fn(focus, gl=country, hl=COUNTRY_TO_HL.get(country, "pt-br"))
    except Exception as e:
        raw["serp"] = {"organic": [], "paa": [], "related_searches": [], "ai_overview": ""}
        raw["errors"].append(f"SERP: {e}")
    raw["ai_overview"] = ai_overview_manual.strip() or raw["serp"].get("ai_overview", "")
    raw["ai_overview_source"] = "manual" if ai_overview_manual.strip() else ("serp" if raw["ai_overview"] else "")

    progress("Lendo as páginas concorrentes", 0.5)
    organic = raw["serp"].get("organic", [])
    pages = crawl_fn([o["url"] for o in organic]) if organic else []
    comps = []
    for o, p in zip(organic, pages):
        comps.append({**p, "position": o["position"], "domain": o["domain"],
                      "serp_title": o["title"], "serp_description": o["description"]})
    raw["competitors"] = comps

    progress("Lendo o sitemap do cliente", 0.7)
    try:
        urls = sitemap_fn(client.get("domain", ""), client.get("sitemap_url", ""))
        terms = [focus] + (manual_secondary or []) + [c["keyword"] for c in raw["keywords"].get("candidates", [])[:15]]
        raw["internal_candidates"] = sitemap.rank_candidates(urls, terms)
        raw["sitemap_total"] = len(urls)
    except Exception as e:
        raw["internal_candidates"], raw["sitemap_total"] = [], 0
        raw["errors"].append(f"Sitemap: {e}")

    progress("Coleta concluída", 0.8)
    return raw


def analyze(client: dict, focus: str, topic: str, raw: dict, notes: str = "") -> dict:
    prompt = prompts.analysis_prompt(client, focus, topic, raw, notes)
    analysis = llm.complete_json(prompts.ANALYSIS_SYSTEM, prompt)
    # garante que as secundárias obrigatórias do analista estejam presentes
    sec = analysis.get("secondary_keywords") or []
    for k in raw.get("manual_secondary", []):
        if k and k.lower() not in [s.lower() for s in sec]:
            sec.append(k)
    analysis["secondary_keywords"] = sec
    return analysis
