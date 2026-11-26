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

from core import config

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
    r"^institucional$", r"^precisa de ajuda", r"^formas de pagamento", r"^seguran[cç]a$", r"^sobre (a|o|n[oó]s) ",
    r"^sobre n[oó]s$", r"^siga (a|o|n)", r"social$", r"^central de", r"^minha conta", r"^baixe (o|nosso) app",
    r"^televendas", r"^ajuda$", r"^d[uú]vidas\?$", r"^pol[ií]tica", r"^trocas e devolu", r"^meus pedidos",
    r"^cadastre", r"^ofertas$", r"^lojas?$", r"^nossas lojas", r"^certifica", r"^selos?", r"^app$",
    r"^eleve sua", r"^filtr", r"^ordenar", r"^resultados?$", r"^\d+ produtos?",
]
_BOILER_RE = re.compile("|".join(BOILERPLATE), re.I)


BLOCK_RE = re.compile(
    r"access denied|unable to give you access|attention required|just a moment|verify you are human|"
    r"are you a robot|captcha|forbidden|request blocked|acesso negado|bot detection|"
    r"enable javascript and cookies|pardon our interruption|error 1020", re.I)


def is_block_page(page: dict) -> bool:
    """Página de bloqueio anti-robô (Akamai, Cloudflare etc.) lida como se fosse conteúdo."""
    first = " ".join([page.get("title", "")] + [h["text"] for h in page.get("headings", [])[:3]])
    return bool(BLOCK_RE.search(first)) or (page.get("word_count", 0) < 150 and bool(BLOCK_RE.search(page.get("excerpt", ""))))


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
    chrome_re = re.compile(r"footer|rodape|menu|navbar|nav-|newsletter|breadcrumb|cookie|modal|minicart|header-", re.I)

    def in_chrome(tag) -> bool:
        for parent in tag.parents:
            if parent.name in ("footer", "nav", "aside"):
                return True
            ident = " ".join(parent.get("class", []) or []) + " " + (parent.get("id") or "")
            if ident.strip() and chrome_re.search(ident):
                return True
        return False

    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        txt = _clean(h.get_text(" "))
        if txt:
            headings.append({"level": int(h.name[1]), "text": txt,
                             "boilerplate": is_boilerplate(txt) or in_chrome(h)})

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


HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
}


def parse_markdown(md: str, url: str = "") -> dict:
    """Converte o markdown do leitor externo no mesmo formato do parse_html (headings, palavras, listas)."""
    title = ""
    m = re.search(r"^Title:\s*(.+)$", md, re.M)
    if m:
        title = m.group(1).strip()
    body = md.split("Markdown Content:", 1)[-1]
    headings = []
    for hm in re.finditer(r"^(#{1,6})\s+(.+?)\s*#*$", body, re.M):
        txt = _clean(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", hm.group(2)))
        if txt:
            headings.append({"level": len(hm.group(1)), "text": txt, "boilerplate": is_boilerplate(txt)})
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)", r"\1", body)
    words = len(re.findall(r"\w+", text))
    return {
        "url": url, "title": title, "meta_description": "", "headings": headings, "word_count": words,
        "tables": len(re.findall(r"^\|.*\|\s*\n\|[\s:|-]+\|", body, re.M)),
        "lists": len(re.findall(r"(?:^|\n\n)\s*(?:[-*]|\d+\.)\s", body)),
        "images": len(re.findall(r"!\[", body)), "videos": 0, "has_faq_schema": False, "schema_types": [],
        "published": "", "modified": "", "years_mentioned": sorted(set(re.findall(r"\b(20[12]\d)\b", title))),
        "excerpt": _clean(text)[:1800], "status": "ok", "error": "", "via": "leitor externo",
    }


def _fetch_reader(url: str, timeout: int = 40) -> dict | None:
    """Leitor externo (Jina Reader): abre a página num navegador real, então funciona em sites que
    bloqueiam robôs simples ou que montam o conteúdo por JavaScript. Pode ser desligado nos secrets
    com [crawler] reader = false; uma chave opcional ([crawler] jina_api_key) aumenta o limite de uso."""
    if str(config.get("reader", section="crawler") or "true").lower() in ("false", "0", "nao", "não"):
        return None
    headers = {"Accept": "text/plain", "X-Return-Format": "markdown"}
    key = config.get("jina_api_key", section="crawler")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = requests.get(f"https://r.jina.ai/{url}", timeout=timeout, headers=headers)
        if r.status_code == 200 and len(r.text) > 300:
            return parse_markdown(r.text, url)
    except Exception:
        pass
    return None


def fetch(url: str, timeout: int = 20) -> dict:
    host = urlparse(url).netloc.lower()
    if any(u in host for u in UNREADABLE):
        return {"url": url, "status": "rede_social", "error": "Página de rede social, sem leitura de headings.",
                "headings": [], "word_count": 0}
    result, error = None, ""
    try:
        r = requests.get(url, timeout=timeout, headers=HEADERS)
        if r.status_code >= 400:
            error = f"HTTP {r.status_code}"
        else:
            r.encoding = r.apparent_encoding or r.encoding
            result = parse_html(r.text, url)
    except Exception as e:
        error = str(e)[:200]
    # bloqueou o robô ou a página monta o conteúdo por JavaScript: tenta o leitor externo
    if result and is_block_page(result):
        result, error = None, "bloqueou a leitura automática"
    useful = result and [h for h in result["headings"] if not h["boilerplate"]]
    if not useful:
        alt = _fetch_reader(url)
        if alt and is_block_page(alt):
            alt, error = None, "bloqueou a leitura automática (inclusive pelo leitor externo)"
        if alt and [h for h in alt["headings"] if not h["boilerplate"]]:
            if result:  # mantém o que só o HTML tem (schema, datas)
                for k in ("has_faq_schema", "schema_types", "published", "modified", "meta_description"):
                    alt[k] = result.get(k) or alt[k]
            return alt
    if result:
        return result
    return {"url": url, "status": "erro", "error": error or "Sem conteúdo", "headings": [], "word_count": 0}


def fetch_many(urls: list[str], workers: int = 6) -> list[dict]:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fetch, urls))
