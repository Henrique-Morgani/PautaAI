"""Dados simulados no formato real das APIs, para testar o pipeline sem gastar créditos."""
import json
from pathlib import Path

from providers import crawler, keywords, serp

FIX = Path(__file__).parent / "fixtures"


class FakeAhrefs(keywords.AhrefsProvider):
    def __init__(self):
        self.calls = 0

    def _get(self, endpoint, params):
        self.calls += 1
        if endpoint == "overview":
            return [{"keyword": params["keywords"].split(",")[0], "volume": 1900, "difficulty": 12,
                     "cpc": 85, "traffic_potential": 5400, "intents": {"informational": True, "commercial": True},
                     "parent_topic": {"keyword": "rack para sala"}}]
        base = [("rack suspenso para sala", 33100, 9), ("rack para sala moderno", 12100, 7),
                ("rack para sala pequena", 9900, 5), ("rack para sala moderno planejado", 2400, 4),
                ("rack para sala grande", 1600, 3), ("altura rack tv", 1300, 2),
                ("altura ideal para rack suspenso", 880, 1), ("ideias de rack para sala pequena", 590, 2),
                ("tipos de rack", 480, 3), ("tamanho padrão de rack para sala", 390, 1),
                ("rack branco", 8100, 6), ("rack com painel", 6600, 8)]
        if params.get("terms") == "questions":
            base = [("qual a altura ideal do rack para tv", 720, 2), ("como escolher rack para sala", 320, 4)]
        return [{"keyword": k, "volume": v, "difficulty": d, "cpc": 60, "traffic_potential": v * 2,
                 "intents": {"commercial": True}, "parent_topic": None} for k, v, d in base]


def fake_serp(q, gl="br", hl="pt-br"):
    raw = json.loads((FIX / "serper.json").read_text())
    return serp.normalize(raw)


def fake_crawl(urls):
    html = (FIX / "competitor.html").read_text()
    out = []
    for u in urls:
        if "instagram" in u:
            out.append(crawler.fetch(u))  # retorna rede_social sem acessar a rede
        else:
            out.append(crawler.parse_html(html, u))
    return out


def fake_sitemap(domain, sitemap_url=""):
    return ["https://www.madesa.com/collections/estante-e-rack-para-tv",
            "https://www.madesa.com/collections/rack-com-painel",
            "https://www.madesa.com/collections/painel-para-tv",
            "https://www.madesa.com/collections/sofa",
            "https://www.madesa.com/products/rack-suspenso-madesa-cancun-180cm",
            "https://www.madesa.com/blogs/dicas/rack-ou-painel-qual-escolher",
            "https://www.madesa.com/pages/contato"]


def fake_llm(system, prompt, want_json):
    if want_json:
        return (FIX / "analysis.json").read_text()
    return (FIX / "body.md").read_text()
