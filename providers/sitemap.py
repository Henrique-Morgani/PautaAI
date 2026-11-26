"""Sitemap do cliente: lista de URLs para sugerir links internos (categorias, produtos, posts)."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; PautaAI/1.0)"
STOP = set("a o as os de da do das dos e em no na nos nas para por com um uma que qual como ideal "
           "sua seu suas seus mais melhor".split())


def _get(url: str) -> str:
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": UA})
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def discover(domain: str, sitemap_url: str = "") -> list[str]:
    if sitemap_url:
        return [sitemap_url]
    base = f"https://{domain.strip('/')}" if not domain.startswith("http") else domain.rstrip("/")
    robots = _get(f"{base}/robots.txt")
    found = re.findall(r"(?im)^sitemap:\s*(\S+)", robots)
    return found or [f"{base}/sitemap.xml"]


def fetch_urls(domain: str, sitemap_url: str = "", max_sitemaps: int = 25, max_urls: int = 8000) -> list[str]:
    queue, seen, urls = discover(domain, sitemap_url), set(), []
    while queue and len(seen) < max_sitemaps and len(urls) < max_urls:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        xml = _get(sm)
        if not xml:
            continue
        soup = BeautifulSoup(xml, "xml")
        if soup.find("sitemapindex"):
            # prioriza sitemaps de coleções/categorias e blog, que são os melhores destinos de link interno
            locs = [l.get_text(strip=True) for l in soup.find_all("loc")]
            locs.sort(key=lambda u: 0 if re.search(r"collection|categor|blog|post|page", u, re.I) else 1)
            queue.extend(locs)
        else:
            urls.extend(l.get_text(strip=True) for l in soup.find_all("loc"))
    return urls[:max_urls]


def _tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return {t for t in re.split(r"[^a-z0-9]+", s) if len(t) > 2 and t not in STOP}


def url_type(url: str) -> str:
    p = urlparse(url).path.lower()
    if re.search(r"/(collections?|categoria|category|c)/", p):
        return "categoria"
    if re.search(r"/(products?|produto|p)/", p) or re.search(r"(/p/?$|-\d{6,}/?$|-\d{6,}/p)", p):
        return "produto"
    if re.search(r"/(blog|blogs|artigos?|dicas|post)/", p):
        return "blog"
    if re.search(r"/(pages?|institucional|ajuda|contato|politica|sobre|lojas?|account|conta|checkout|cart)(/|$)", p):
        return "pagina"
    return "categoria"


def rank_candidates(urls: list[str], terms: list[str], top: int = 40) -> list[dict]:
    """Pontua URLs do sitemap pela sobreposição com keyword foco e secundárias.
    Categorias e posts ganham peso extra; produtos individuais entram com peso menor."""
    want = set()
    for t in terms:
        want |= _tokens(t)
    weight = {"categoria": 1.6, "blog": 1.3, "pagina": 1.0, "produto": 0.4}
    scored = []
    for u in urls:
        path_tokens = _tokens(urlparse(u).path)
        hit = len(want & path_tokens)
        if hit:
            kind = url_type(u)
            scored.append({"url": u, "type": kind, "score": round(hit * weight[kind], 2)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    out, products = [], 0
    for item in scored:
        if item["type"] == "produto":
            if products >= 5:
                continue
            products += 1
        out.append(item)
    return out[:top]


def find_existing_content(urls: list[str], focus: str, extra_terms: list[str] | None = None, top: int = 5) -> list[dict]:
    """Posts do blog do cliente que já tratam do tema (risco de canibalização).
    Critério: o slug contém todos os termos principais da keyword foco (ou de uma das secundárias)."""
    targets = [t for t in [focus] + (extra_terms or []) if t]
    found = []
    for u in urls:
        if url_type(u) != "blog":
            continue
        slug = _tokens(urlparse(u).path)
        best = 0.0
        for t in targets:
            tk = _tokens(t)
            if tk:
                best = max(best, len(tk & slug) / len(tk))
        if best >= 1.0:
            found.append({"url": u, "match": round(best, 2)})
    return found[:top]
