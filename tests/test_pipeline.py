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


def test_gemini_continues_when_cut(monkeypatch):
    from types import SimpleNamespace as NS
    from google import genai
    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(contents)
            if len(calls) == 1:
                return NS(text="# Título\n\nPrimeira parte do texto que foi", candidates=[NS(finish_reason=NS(name="MAX_TOKENS"))])
            return NS(text="interrompida e agora termina.", candidates=[NS(finish_reason=NS(name="STOP"))])

    class FakeClient:
        def __init__(self, **kw):
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    out = llm._gemini("sys", "escreva", False, 0.5)
    assert out.endswith("foi interrompida e agora termina.") and len(calls) == 2
    assert "Continue EXATAMENTE" in calls[1]
    assert llm.LAST_FINISH["reason"] == "STOP"


def test_content_check_detects_cut_text():
    import json
    a = json.loads((fakes.FIX / "analysis.json").read_text())
    body = "# Como escolher o rack ideal para sua sala na Copa do Mundo\n\nIntro.\n\n## Por que o rack é importante na sala da Copa?\n\nO rack organiza a sala e"
    checks = {c["item"]: c for c in validate.check_content("rack ideal para sala", a, body)}
    assert not checks["Texto termina com frase completa"]["ok"]
    assert not checks["Todas as seções da estrutura no texto"]["ok"]
    full = (fakes.FIX / "body.md").read_text()
    checks = {c["item"]: c for c in validate.check_content("rack ideal para sala", a, full)}
    assert checks["Texto termina com frase completa"]["ok"], checks
    assert checks["Todas as seções da estrutura no texto"]["ok"], checks


def test_footer_headings_are_boilerplate():
    page = crawler.parse_html((fakes.FIX / "competitor.html").read_text(), "https://x.com/a")
    texts = [h["text"] for h in page["headings"] if not h["boilerplate"]]
    assert "Qualquer coisa do rodapé" not in texts and "Lojas oficiais" not in texts
    assert "Formas de pagamento" not in texts


def test_reader_fallback_on_403(monkeypatch):
    from types import SimpleNamespace as NS
    md = ("Title: Tênis de corrida | Loja\n\nMarkdown Content:\n# Tênis de corrida\n\nTexto " + "palavra " * 200 +
          "\n\n## Como escolher o tênis de corrida\n\n- item\n- item\n\n### Pisada neutra\n\n## Institucional\n")

    def fake_get(url, timeout=0, headers=None):
        if url.startswith("https://r.jina.ai/"):
            return NS(status_code=200, text=md)
        return NS(status_code=403, text="blocked")

    monkeypatch.setattr(crawler.requests, "get", fake_get)
    page = crawler.fetch("https://www.netshoes.com.br/running/tenis")
    assert page["status"] == "ok" and page.get("via") == "leitor externo"
    texts = [h["text"] for h in page["headings"] if not h["boilerplate"]]
    assert texts == ["Tênis de corrida", "Como escolher o tênis de corrida", "Pisada neutra"]


def test_postprocess_faq_and_links():
    import json
    a = json.loads((fakes.FIX / "analysis.json").read_text())
    a["links_internos"].append({"url": "https://www.madesa.com/inventada", "ancora": "x", "onde": "y"})
    raw = _collect()
    out = bp.postprocess(a, CLIENT, raw, "rack ideal para sala")
    urls = [l["url"] for l in out["links_internos"]]
    assert "https://www.madesa.com/inventada" not in urls and urls
    heads = out["estrutura"]["headings"]
    i = next(i for i, h in enumerate(heads) if "Dúvidas frequentes" in h["text"])
    assert heads[i]["level"] == 2 and [h["text"] for h in heads[i + 1:]] == a["faq"]
    assert all(h["level"] == 3 for h in heads[i + 1:])


def test_manual_secondary_gets_volume_and_alert_renders():
    import json
    raw = _collect()
    a = json.loads((fakes.FIX / "analysis.json").read_text())
    a["secondary_keywords"].append("Rack Ideal Para Sala")  # variação com maiúsculas da foco (vem do overview)
    a["alerta_serp"] = {"tipo_de_pagina_dominante": "categorias", "alerta": "Risco de não ranquear.",
                        "keyword_alternativa": "como escolher rack"}
    html = render.briefing_html(CLIENT, "rack ideal para sala", raw, a)
    assert "Alerta de intenção da SERP" in html and "como escolher rack" in html
    assert "<td>Rack Ideal Para Sala</td><td>1.900</td>" in html
    assert "Perguntas com volume de busca (Ahrefs)" in html


def test_prompt_carries_client_rules():
    from ai import prompts
    c = {**CLIENT, "tone_of_voice": "Title terminando em | Blog Decathlon", "forbidden_terms": "Mizuno"}
    pr = prompts.analysis_prompt(c, "tenis de corrida", "", _collect())
    assert "| Blog Decathlon" in pr and "Mizuno" in pr and "tipo_pagina_estimado" in pr
    assert "NUNCA use links internos" in prompts.ANALYSIS_SYSTEM


def test_block_page_is_not_content(monkeypatch):
    from types import SimpleNamespace as NS
    blocked_html = "<html><head><title>Access Denied</title></head><body><h1>Access Denied</h1><p>You don't have permission.</p></body></html>"
    blocked_md = "Title: Access Denied\n\nMarkdown Content:\n# Access Denied\n\nYou don't have permission to access this server."

    def fake_get(url, timeout=0, headers=None):
        if url.startswith("https://r.jina.ai/"):
            return NS(status_code=200, text=blocked_md + " " * 400)
        return NS(status_code=200, text=blocked_html, apparent_encoding="utf-8", encoding="utf-8")

    monkeypatch.setattr(crawler.requests, "get", fake_get)
    page = crawler.fetch("https://www.adidas.com.br/calcados-running")
    assert page["status"] == "erro" and "bloqueou" in page["error"]


def test_serper_completes_with_page_2(monkeypatch):
    import json
    from types import SimpleNamespace as NS
    from providers import serp
    first = json.loads((fakes.FIX / "serper.json").read_text())  # 5 orgânicos
    second = {"organic": [{"title": f"R{i}", "link": f"https://site{i}.com/x", "snippet": ""} for i in range(8)]}

    def fake_post(url, timeout=0, headers=None, json=None):
        return NS(status_code=200, json=lambda: second if json.get("page") == 2 else first, text="")

    monkeypatch.setattr(serp.requests, "post", fake_post)
    monkeypatch.setenv("SERPER_API_KEY", "x")
    out = serp.search("rack")
    assert len(out["organic"]) == 10 and [o["position"] for o in out["organic"]] == list(range(1, 11))


def test_missing_secondary_volumes_and_index_removed():
    import json
    raw = _collect()
    llm.OVERRIDE = lambda s, p, j: json.dumps({**json.loads((fakes.FIX / "analysis.json").read_text()),
        "secondary_keywords": ["rack suspenso para sala", "rack para sala com nicho"],
        "estrutura": {"title": "como escolher o rack ideal para a sala | Blog Madesa",
                      "description": "x" * 140, "url": "/rack/",
                      "headings": [{"level": 1, "text": "Como escolher o rack"}, {"level": 2, "text": "Índice"},
                                   {"level": 2, "text": "Tipos de rack"}]}})
    a = bp.analyze(CLIENT, "rack ideal para sala", "", raw, kw_provider=fakes.FakeAhrefs())
    llm.OVERRIDE = None
    assert a["estrutura"]["title"].startswith("Como")
    assert "Índice" not in [h["text"] for h in a["estrutura"]["headings"]]
    extra = {r["keyword"] for r in raw["keywords"]["extra"]}
    assert "rack para sala com nicho" in extra


def test_product_grid_is_collapsed():
    cards = "".join(f"<h4>Tênis FLAME {i} Placa de Carbono Corrida - Feminino | Rosa {i}</h4>" for i in range(30))
    html = f"<html><body><h1>361 Sport</h1>{cards}{cards}<h2>Tecnologia para sua corrida</h2></body></html>"
    page = crawler.parse_html(html, "https://361sport.com.br/")
    texts = [h["text"] for h in page["headings"] if not h["boilerplate"]]
    assert texts == ["361 Sport", "Tecnologia para sua corrida"]
    assert page["product_titles_omitted"] == 30


def test_serp_features_and_dedupe_accents():
    import json
    from providers import serp
    raw = json.loads((fakes.FIX / "serper.json").read_text())
    raw["videos"] = [{"title": "Como escolher tênis", "link": "https://youtube.com/x", "channel": "Canal"}]
    out = serp.normalize(raw)
    assert out["serp_features"]["Vídeos"]["count"] == 1
    llm.OVERRIDE = lambda s, p, j: json.dumps({**json.loads((fakes.FIX / "analysis.json").read_text()),
        "secondary_keywords": ["Tênis para corrida", "tenis para corrida", "Rack ideal para sala", "Tipos de rack"],
        "semantic_terms": ["Corrida", "corrida", "Placa de carbono"]})
    r = _collect()
    r["manual_secondary"] = ["Tenis para corrida"]
    a = bp.analyze(CLIENT, "rack ideal para sala", "", r, kw_provider=fakes.FakeAhrefs())
    llm.OVERRIDE = None
    assert a["secondary_keywords"] == ["tênis para corrida", "tipos de rack"]
    assert a["semantic_terms"] == ["corrida", "placa de carbono"]
