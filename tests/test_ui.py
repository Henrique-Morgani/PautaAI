"""Teste da interface com Streamlit AppTest e APIs simuladas."""
import functools, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
os.environ["ADMIN_EMAIL"] = "admin@teste.com"; os.environ["ADMIN_PASSWORD"] = "senha12345"
os.environ["DATABASE_URL"] = "sqlite:///ui_test.db"
from streamlit.testing.v1 import AppTest
from ai import llm
from pipeline import briefing as bp
from tests import fakes

def test_full_flow():
    Path("ui_test.db").unlink(missing_ok=True)
    llm.OVERRIDE = fakes.fake_llm
    orig = bp.collect.__wrapped__ if hasattr(bp.collect, "__wrapped__") else bp.collect
    bp.collect = functools.partial(orig, kw_provider=fakes.FakeAhrefs(), serp_fn=fakes.fake_serp,
                                   crawl_fn=fakes.fake_crawl, sitemap_fn=fakes.fake_sitemap)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    at.text_input[0].input("admin@teste.com"); at.text_input[1].input("senha12345")
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert any("Cadastre um cliente" in w.value for w in at.warning)

    at.session_state["page"] = "clientes"; at.run()
    labels = [t.label for t in at.text_input]
    at.text_input[labels.index("Nome")].input("Madesa")
    at.text_input[labels.index("Domínio")].input("https://www.madesa.com/")
    at.button(key=None) if False else None
    [b for b in at.button if b.label == "Salvar cliente"][0].click().run()
    assert not at.exception, at.exception

    at.session_state["page"] = "nova"; at.run()
    labels = [t.label for t in at.text_input]
    at.text_input[labels.index("Palavra-chave foco")].input("rack ideal para sala")
    [b for b in at.button if b.label == "Gerar análise"][0].click().run()
    assert not at.exception, at.exception
    assert at.session_state["page"] == "briefing"
    at.run()
    assert not at.exception, at.exception
    assert at.title[0].value == "rack ideal para sala"
    assert len(at.tabs) == 5
    # salvar a estrutura e checar
    [b for b in at.button if b.label == "Salvar estrutura"][0].click().run()
    assert not at.exception, at.exception
    # gerar texto
    [b for b in at.button if b.label == "Gerar texto"][0].click().run()
    assert not at.exception, at.exception
    at.run()
    assert any("Texto (markdown" in t.label for t in at.text_area)
    at.session_state["page"] = "historico"; at.run()
    assert not at.exception, at.exception
    at.session_state["page"] = "usuarios"; at.run()
    assert not at.exception, at.exception
    llm.OVERRIDE = None
    Path("ui_test.db").unlink(missing_ok=True)
