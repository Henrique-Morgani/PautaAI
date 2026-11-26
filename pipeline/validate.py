"""Checagens automáticas de SEO on-page do briefing e do texto gerado.

Cada checagem devolve {"item", "ok": bool, "detalhe", "nivel": "erro"|"aviso"}.
"""
from __future__ import annotations

import re
import unicodedata

STOP = set("a o as os de da do das dos e em no na nos nas para por com um uma que".split())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def _tokens(s: str) -> list[str]:
    return [t for t in _norm(s).split() if t not in STOP]


def contains_kw(text: str, kw: str, min_ratio: float = 0.75) -> bool:
    """Considera presente se a frase exata existe ou se a maior parte dos termos aparece."""
    if _norm(kw).strip() in _norm(text):
        return True
    k = _tokens(kw)
    if not k:
        return False
    t = set(_tokens(text))
    return sum(1 for x in k if x in t) / len(k) >= min_ratio


def _c(item, ok, detalhe, nivel="erro"):
    return {"item": item, "ok": bool(ok), "detalhe": detalhe, "nivel": nivel}


def check_briefing(focus: str, analysis: dict) -> list[dict]:
    est = analysis.get("estrutura", {})
    title, desc, url = est.get("title", ""), est.get("description", ""), est.get("url", "")
    heads = est.get("headings", [])
    h1s = [h for h in heads if h.get("level") == 1]
    out = [
        _c("Title até 60 caracteres", 0 < len(title) <= 60, f"{len(title)} caracteres"),
        _c("Keyword foco no title", contains_kw(title, focus), title or "vazio"),
        _c("Description entre 120 e 155 caracteres", 120 <= len(desc) <= 155, f"{len(desc)} caracteres", "aviso"),
        _c("Keyword foco na description", contains_kw(desc, focus), "", "aviso"),
        _c("URL em formato de slug", bool(re.fullmatch(r"/?[a-z0-9]+(-[a-z0-9]+)*/?", url or "")), url or "vazia"),
        _c("Keyword foco na URL", contains_kw(url.replace("-", " "), focus, 0.6), "", "aviso"),
        _c("Um único H1", len(h1s) == 1, f"{len(h1s)} H1 encontrado(s)"),
        _c("Keyword foco no H1", bool(h1s) and contains_kw(h1s[0]["text"], focus), h1s[0]["text"] if h1s else ""),
    ]
    jumps = [f"H{a['level']} → H{b['level']}: {b['text']}" for a, b in zip(heads, heads[1:])
             if b.get("level", 0) - a.get("level", 0) > 1]
    out.append(_c("Hierarquia sem pular níveis", not jumps, "; ".join(jumps[:3]) or "ok", "aviso"))
    sec = analysis.get("secondary_keywords", [])
    all_heads = " ".join(h["text"] for h in heads)
    covered = [k for k in sec if contains_kw(all_heads, k)]
    out.append(_c("Secundárias presentes nos headings", len(covered) >= max(1, len(sec) // 3),
                  f"{len(covered)} de {len(sec)} aparecem em algum heading", "aviso"))
    return out


def check_content(focus: str, analysis: dict, body_md: str) -> list[dict]:
    plain = re.sub(r"[#*_>\[\]()`|-]", " ", body_md)
    words = len(re.findall(r"\w+", plain))
    paras = [p for p in body_md.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    intro = " ".join(paras[:2])
    first100 = " ".join(re.findall(r"\w+", intro)[:100])
    h1 = re.search(r"^# (.+)$", body_md, re.M)
    sec = analysis.get("secondary_keywords", [])
    missing = [k for k in sec if not contains_kw(plain, k, 0.9)]
    links = re.findall(r"\]\((https?://[^)]+)\)", body_md)
    dashes = body_md.count("—")
    occurrences = _norm(plain).count(_norm(focus).strip())
    return [
        _c("H1 com a keyword foco", bool(h1) and contains_kw(h1.group(1), focus), h1.group(1) if h1 else "sem H1"),
        _c("Keyword foco nas primeiras 100 palavras", contains_kw(first100, focus), "", "aviso"),
        _c("Tamanho do texto", words >= 800, f"{words} palavras", "aviso"),
        _c("Secundárias usadas no texto", not missing, ("faltando: " + ", ".join(missing)) if missing else "todas usadas", "aviso"),
        _c("Links internos inseridos", len(links) >= 1, f"{len(links)} link(s)", "aviso"),
        _c("Sem travessão (—)", dashes == 0, f"{dashes} ocorrência(s)", "aviso"),
        _c("Repetição exata da keyword foco", occurrences <= max(6, words // 250), f"{occurrences} vez(es)", "aviso"),
    ]


def strip_em_dashes(text: str) -> str:
    """Troca travessões por vírgula, mantendo o sentido na maioria dos casos."""
    text = re.sub(r"\s*—\s*", ", ", text)
    return re.sub(r",\s*,", ",", text)
