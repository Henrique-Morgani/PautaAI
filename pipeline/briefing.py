"""Pipeline da análise: coleta -> análise da IA -> validação.

collect() junta todos os dados brutos; analyze() chama a IA; os dois são separados para a tela
poder mostrar o progresso por etapa e para permitir regenerar só a análise sem gastar API de novo.
"""
from __future__ import annotations

import re
from typing import Callable

from ai import llm, prompts
from providers import crawler, keywords, serp, sitemap

COUNTRY_TO_HL = {"br": "pt-br", "pt": "pt-pt", "mx": "es-419", "ar": "es-419", "co": "es-419",
                 "cl": "es-419", "es": "es", "us": "en"}


def collect(client: dict, focus: str, manual_secondary: list[str] | None = None,
            ai_overview_manual: str = "", progress: Callable[[str, float], None] | None = None,
            paa_manual: list[str] | None = None,
            kw_provider: keywords.KeywordProvider | None = None,
            serp_fn=serp.search, crawl_fn=crawler.fetch_many, sitemap_fn=sitemap.fetch_urls) -> dict:
    progress = progress or (lambda *_: None)
    country = (client.get("country") or "br").lower()
    raw: dict = {"manual_secondary": manual_secondary or [], "paa_manual": paa_manual or [], "errors": []}

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
    if not raw["serp"].get("paa") and paa_manual:
        raw["serp"]["paa"] = paa_manual
        raw["paa_source"] = "manual"
    elif raw["serp"].get("paa"):
        raw["paa_source"] = "serp"

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


def analyze(client: dict, focus: str, topic: str, raw: dict, notes: str = "",
            kw_provider: keywords.KeywordProvider | None = None) -> dict:
    prompt = prompts.analysis_prompt(client, focus, topic, raw, notes)
    analysis = llm.complete_json(prompts.ANALYSIS_SYSTEM, prompt)
    analysis = _fix_title_description(analysis, client, focus)
    # garante que as secundárias obrigatórias do analista estejam presentes
    sec = []
    for k in (analysis.get("secondary_keywords") or []) + raw.get("manual_secondary", []):
        k = (k or "").strip()
        if k and _norm(k) not in {_norm(x) for x in sec} and _norm(k) != _norm(focus):
            sec.append(_lower_kw(k))
    analysis["secondary_keywords"] = sec
    analysis["semantic_terms"] = list(dict.fromkeys(_lower_kw(t) for t in analysis.get("semantic_terms", []) if t))
    fill_missing_volumes(analysis, raw, client, kw_provider)
    return postprocess(analysis, client, raw, focus)


def _lower_kw(k: str) -> str:
    """Palavras-chave em minúsculas, como são buscadas; preserva siglas e nomes com mais de uma maiúscula."""
    return " ".join(w if (len(w) > 1 and w.isupper()) or sum(c.isupper() for c in w) > 1 else w.lower()
                    for w in str(k).split())


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(s.split())


def fill_missing_volumes(analysis: dict, raw: dict, client: dict, kw_provider=None):
    """A IA às vezes cria secundárias que não estavam nas candidatas: busca o volume delas no Ahrefs
    (1 chamada) para o analista ver quais têm demanda real."""
    kw = raw.setdefault("keywords", {})
    known = {_norm(c.get("keyword")) for c in (kw.get("candidates") or []) + (kw.get("focus") or [])
             + (kw.get("extra") or [])}
    missing = [k for k in analysis.get("secondary_keywords", []) if _norm(k) not in known]
    if not missing:
        return
    try:
        prov = kw_provider or keywords.get_provider()
        rows = prov.overview(missing[:20], (client.get("country") or "br").lower())
        found = {_norm(r.get("keyword")) for r in rows}
        # termo sem resultado no Ahrefs = sem volume medido
        rows += [{"keyword": k, "volume": 0, "difficulty": None, "source": "sem dados"}
                 for k in missing if _norm(k) not in found]
        kw["extra"] = (kw.get("extra") or []) + rows
    except Exception as e:
        raw.setdefault("errors", []).append(f"Volume das secundárias sugeridas pela IA: {e}")


def _fix_title_description(analysis: dict, client: dict, focus: str) -> dict:
    """Se o title passar de 60 ou a description sair de 120-155 caracteres, pede só esses dois de novo."""
    est = analysis.get("estrutura") or {}
    title, desc = est.get("title", ""), est.get("description", "")
    if title and title[0].islower():
        title = title[0].upper() + title[1:]
        est["title"] = title
    if len(title) <= 60 and 120 <= len(desc) <= 155:
        return analysis
    try:
        fixed = llm.complete_json(
            "Você é analista de SEO. Reescreva title e description respeitando os limites. "
            "Português correto com acentos. Não use travessão. Responda só JSON.",
            f"Keyword foco: {focus}\nRegras do cliente: {client.get('tone_of_voice') or '-'}\n"
            f"Title atual ({len(title)} caracteres): {title}\nDescription atual ({len(desc)} caracteres): {desc}\n"
            "Limites: title com no máximo 60 caracteres contando o sufixo da marca; description entre 120 e 155.\n"
            'Formato: {"title": "...", "description": "..."}')
        t, d = fixed.get("title", "").strip(), fixed.get("description", "").strip()
        if t and len(t) <= 60:
            est["title"] = t[0].upper() + t[1:]
        if d and 110 <= len(d) <= 160:
            est["description"] = d
    except Exception:
        pass
    analysis["estrutura"] = est
    return analysis


_FAQ_RE = re.compile(r"d[uú]vidas|perguntas frequentes|\bfaq\b", re.I)


def postprocess(analysis: dict, client: dict, raw: dict, focus: str) -> dict:
    """Correções determinísticas sobre a saída da IA."""
    # 1. links internos: só URLs que existem no sitemap/links prioritários
    allowed = {c["url"].rstrip("/") for c in raw.get("internal_candidates", [])}
    allowed |= {l.strip().rstrip("/") for l in (client.get("priority_links") or "").splitlines() if l.strip()}
    if allowed:
        analysis["links_internos"] = [l for l in analysis.get("links_internos", [])
                                      if str(l.get("url", "")).rstrip("/") in allowed]

    # 2. FAQ: perguntas como H3 logo abaixo do H2 de dúvidas frequentes
    est = analysis.setdefault("estrutura", {})
    heads = [h for h in est.get("headings", []) if h.get("text")
             and not re.fullmatch(r"\s*([ií]ndice|sum[aá]rio|conte[uú]do)\s*:?\s*", h["text"], re.I)]
    faq = [q for q in analysis.get("faq", []) if q]
    if faq:
        idx = next((i for i, h in enumerate(heads) if h.get("level") == 2 and _FAQ_RE.search(h["text"])), None)
        if idx is None:
            heads.append({"level": 2, "text": f"Dúvidas frequentes sobre {focus.strip().lower()}"})
            idx = len(heads) - 1
        end = idx + 1
        while end < len(heads) and heads[end].get("level", 2) > 2:
            end += 1
        existing = [h for h in heads[idx + 1:end] if h.get("level") == 3]
        if not existing:
            heads[idx + 1:end] = [{"level": 3, "text": q.strip()} for q in faq]
    est["headings"] = heads
    return analysis
