"""SERP via Serper (google.serper.dev): top 10 orgânico, PAA, buscas relacionadas e,
quando o Google exibir e o Serper devolver, a Visão de IA (AI Overview).

Se a Visão de IA não vier na resposta, a tela de nova análise aceita que o analista cole o texto.
"""
from __future__ import annotations

from urllib.parse import urlparse

import requests

from core import config


class SerpError(RuntimeError):
    pass


def search(query: str, gl: str = "br", hl: str = "pt-br", num: int = 10) -> dict:
    """Pede 20 resultados ao Serper (o Google costuma mostrar menos de 10 orgânicos quando há
    Shopping, vídeos e PAA) e fica com os 10 primeiros orgânicos."""
    key = config.get("api_key", section="serper") or config.get("SERPER_API_KEY")
    if not key:
        raise SerpError("Chave do Serper não configurada ([serper] api_key).")
    r = requests.post("https://google.serper.dev/search", timeout=40,
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json={"q": query, "gl": gl, "hl": hl,
                            "num": int(config.get("num", section="serper") or 20)})
    if r.status_code != 200:
        raise SerpError(f"Serper retornou {r.status_code}: {r.text[:300]}")
    return normalize(r.json(), num)


def _domain(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def _ai_overview_text(raw: dict) -> str:
    """O formato da Visão de IA varia; tenta os campos conhecidos e junta o texto."""
    block = raw.get("aiOverview") or raw.get("ai_overview") or {}
    if isinstance(block, str):
        return block
    parts = []
    for key in ("text", "snippet", "answer"):
        if isinstance(block.get(key), str):
            parts.append(block[key])
    for item in block.get("text_blocks", []) or block.get("items", []) or []:
        if isinstance(item, dict):
            t = item.get("snippet") or item.get("text") or ""
            if t:
                parts.append(t)
            for li in item.get("list", []) or []:
                if isinstance(li, dict) and (li.get("snippet") or li.get("title")):
                    parts.append(f"- {li.get('title', '')} {li.get('snippet', '')}".strip())
    return "\n".join(parts).strip()


def normalize(raw: dict, num: int = 10) -> dict:
    organic = []
    for i, o in enumerate(raw.get("organic", [])[:num], start=1):
        organic.append({
            "position": o.get("position", i),
            "title": o.get("title", ""),
            "description": o.get("snippet", ""),
            "url": o.get("link", ""),
            "domain": _domain(o.get("link", "")),
            "date": o.get("date", ""),
        })
    return {
        "organic": organic,
        "paa": [p.get("question", "") for p in raw.get("peopleAlsoAsk", []) if p.get("question")],
        "related_searches": [r.get("query", "") for r in raw.get("relatedSearches", []) if r.get("query")],
        "ai_overview": _ai_overview_text(raw),
        "answer_box": (raw.get("answerBox") or {}).get("snippet") or (raw.get("answerBox") or {}).get("answer", ""),
        "credits": raw.get("credits", 1),
    }
