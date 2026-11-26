"""Leitura das páginas concorrentes: headings, tamanho, recursos e datas.

Para cada URL do top 10 devolve:
    title, meta_description, headings [{level, text, boilerplate}], word_count,
    tables, lists, images, videos, has_faq_schema, schema_types,
    published, modified, years_mentioned, excerpt, status, error
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# Páginas que não dá para ler como artigo (o resultado entra na SERP, mas sem headings)
UNREADABLE = ("instagram.com", "facebook.com", "tiktok.com", "youtube.com", "youtu.be",
              "pinterest.", "x.com", "twitter.com", "linkedin.com", "threads.net")

# Headings de template que não fazem parte do conteúdo (aparecem muito em blogs)
BOILERPLATE = [
    r"^compartilh", r"^deixe (seu|um) coment", r"^coment[aá]rios?$", r"posts? recentes",
    r"conte[uú]dos? recentes", r"^continuar lendo", r"^leia (tamb[eé]m|mais)", r"^veja tamb[eé]m",
    r"^categorias?$", r"^tags?$", r"^newsletter", r"^inscreva", r"^assine", r"^siga-nos",
    r"^redes sociais", r"^menu$", r"^navega[cç][aã]o", r"^posts? relacionados", r"^artigos? relacionados",
    r"^sobre o autor", r"^voc[eê] tamb[eé]m pode gostar", r"^mais lidos", r"^busca$", r"^pesquis",
    r"^gostou( das dicas)?\??$", r"^conhe[cç]a a ", r"^receba ", r"^fale conosco", r"^atendimento",
]
_BOILER_RE = re.compile("|".join(BOILERPLATE), re.I)


def is_boilerplate(text: str) -> bool:
    return bool(_BOILER_RE.search(text.strip()))


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("​", "")).strip()


def _main_node(soup: BeautifulSoup):
    for sel in ("article", "main", "[role=main]", ".post-content", ".entry-content", ".article-content"):
        node = soup.select_one(sel)
        if node and len(node.get_text(" ", strip=True)) > 500:
            return node
    body = soup.body or soup
    for tag in body.find_all(["nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    return body


def _jsonld(soup: BeautifulSoup) -> list[dict]:
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                out.append(d)
                if "@graph" in d and isinstance(d["@graph"], list):
                    stack.extend(d["@graph"])
            elif isinstance(d, list):
                stack.extend(d)
    return out


def parse_html(html: str, url: str = "") -> dict:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg"]):
        if t.name == "script" and t.get("type") == "application/ld+json":
            continue
        t.decompose()

    ld = _jsonld(soup)
    types = []
    published = modified = ""
    for d in ld:
        t = d.get("@type")
        types.extend(t if isinstance(t, list) else [t] if t else [])
        published = published or d.get("datePublished", "")
        modified = modified or d.get("dateModified", "")

    def meta(**attrs):
        m = soup.find("meta", attrs=attrs)
        return _clean(m.get("content", "")) if m else ""

    published = published or meta(property="article:published_time")
    modified = modified or meta(property="article:modified_time")
    title = _clean(soup.title.get_text()) if soup.title else ""
    desc = meta(name="description") or meta(property="og:description")

    # headings da página inteira (antes de remover header/footer), na ordem em que aparecem
    headings = []
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        txt = _clean(h.get_text(" "))
        if txt:
            headings.append({"level": int(h.name[1]), "text": txt, "boilerplate": is_boilerplate(txt)})

    main = _main_node(soup)
    text = _clean(main.get_text(" "))
    words = len(re.findall(r"\w+", text))
    years = sorted(set(re.findall(r"\b(20[12]\d)\b", " ".join([title] + [h["text"] for h in headings[:5]]))))

    return {
        "url": url,
        "title": title,
        "meta_description": desc,
        "headings": headings,
        "word_count": words,
        "tables": len(main.find_all("table")),
        "lists": len(main.find_all(["ul", "ol"])),
        "images": len(main.find_all("img")),
        "videos": len([f for f in main.find_all(["iframe", "video"])
                       if f.name == "video" or "youtube" in (f.get("src") or "") or "vimeo" in (f.get("src") or "")]),
        "has_faq_schema": "FAQPage" in types,
        "schema_types": sorted({str(t) for t in types if t}),
        "published": str(published)[:10],
        "modified": str(modified)[:10],
        "years_mentioned": years,
        "excerpt": text[:1800],
        "status": "ok",
        "error": "",
    }


def fetch(url: str, timeout: int = 20) -> dict:
    host = urlparse(url).netloc.lower()
    if any(u in host for u in UNREADABLE):
        return {"url": url, "status": "rede_social", "error": "Página de rede social, sem leitura de headings.",
                "headings": [], "word_count": 0}
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        if r.status_code >= 400:
            return {"url": url, "status": "erro", "error": f"HTTP {r.status_code}", "headings": [], "word_count": 0}
        r.encoding = r.apparent_encoding or r.encoding
        return parse_html(r.text, url)
    except Exception as e:
        return {"url": url, "status": "erro", "error": str(e)[:200], "headings": [], "word_count": 0}


def fetch_many(urls: list[str], workers: int = 6) -> list[dict]:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fetch, urls))
