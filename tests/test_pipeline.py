"""Teste de ponta a ponta com dados simulados. Rodar: python -m pytest -q tests (na raiz do projeto)."""
import functools
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "")

from ai import llm  # noqa: E402
from export import render  # noqa: E402
from pipeline import briefing as bp, content as cp, validate  # noqa: E402
from providers import crawler, keywords  # noqa: E402
from tests import fakes  # noqa: E402

CLIENT = {"name": "Madesa", "domain": "madesa.com", "country": "br", "brand_context": "Móveis",
          "priority_links": "", "tone_of_voice": "", "forbidden_terms": "", "sitemap_url": ""}


def _collect():
    return bp.collect(CLIENT, "rack ideal para sala", ["altura rack tv"], "",
                      kw_provider=fakes.FakeAhrefs(), serp_fn=fakes.fake_serp,
                      crawl_fn=fakes.fake_crawl, sitemap_fn=fakes.fake_sitemap)


def test_crawler_filters_boilerplate_and_reads_features():
    page = crawler.parse_html((fakes.FIX / "competitor.html").read_text(), "https://x.com/a")
    texts = [h["text"] for h in page["headings"] if not h["boilerplate"]]
    assert texts[0].startswith("Rack ou painel")
    assert "Compartilhe" not in texts and "Conteúdos Recentes" not in texts and "Posts Recentes" not in texts
    assert page["has_faq_schema"] and page["tables"] == 1 and page["published"] == "2022-10-20"
    assert "2022" in page["years_mentioned"]


def test_social_is_not_fetched():
    assert crawler.fetch("https://www.instagram.com/p/abc/")["status"] == "rede_social"


def test_ahrefs_normalization():
    rows = fakes.FakeAhrefs().overview(["rack ideal para sala"], "br")
    assert rows[0]["cpc"] == 0.85 and "informational" in rows[0]["intents"]
    assert rows[0]["parent_topic"] == "rack para sala"


def test_collect_and_analyze_end_to_end():
    raw = _collect()
    assert not raw["errors"], raw["errors"]
    assert len(raw["keywords"]["candidates"]) >= 10
    assert raw["serp"]["paa"] and len(raw["competitors"]) == 5
    assert raw["competitors"][1]["status"] == "rede_social"
    top = raw["internal_candidates"][:4]
    assert sum(1 for c in top if c["type"] == "categoria") >= 2, top
    assert all("contato" not in c["url"] for c in raw["internal_candidates"])

    llm.OVERRIDE = fakes.fake_llm
    a = bp.analyze(CLIENT, "rack ideal para sala", "", raw)
    assert "altura rack tv" in a["secondary_keywords"]

    checks = {c["item"]: c for c in validate.check_briefing("rack ideal para sala", a)}
    assert checks["Title até 60 caracteres"]["ok"]
    assert checks["Um único H1"]["ok"] and checks["Keyword foco no H1"]["ok"]

    html = render.briefing_html(CLIENT, "rack ideal para sala", raw, a)
    for section in ("Visão de IA da SERP", "PAA", "10 primeiros resultados da SERP", "Heading tags",
                    "Leitura estratégica do cenário", "Estratégia de Link Building", "Estrutura para otimização"):
        assert section in html
    assert "Compartilhe" not in html
    (ROOT / "tests" / "out_briefing.html").write_text(html)

    body = cp.generate(CLIENT, "rack ideal para sala", a)
    cchecks = validate.check_content("rack ideal para sala", a, body)
    assert any(c["item"] == "Links internos inseridos" and c["ok"] for c in cchecks)
    chtml = render.content_html("rack ideal para sala", a, body)
    assert "&lt;h2&gt;" in chtml and "Palavra-chave foco:" in chtml
    (ROOT / "tests" / "out_content.html").write_text(chtml)
    llm.OVERRIDE = None


def test_strip_em_dash():
    assert "—" not in validate.strip_em_dashes("O rack — peça central — organiza a sala")


def test_semrush_placeholder_raises():
    try:
        keywords.get_provider("semrush")
        assert False
    except keywords.KeywordProviderError:
        pass
