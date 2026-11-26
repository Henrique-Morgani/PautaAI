"""Lotes com APIs simuladas e banco SQLite temporário."""
import io
import os
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai import llm  # noqa: E402
from core import db  # noqa: E402
from pipeline import batch  # noqa: E402
from tests import fakes  # noqa: E402


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'b.db'}")
    db._engine = db._Session = None
    llm.OVERRIDE = fakes.fake_llm
    batch.COLLECT_KW.update(kw_provider=fakes.FakeAhrefs(), serp_fn=fakes.fake_serp,
                            crawl_fn=fakes.fake_crawl, sitemap_fn=fakes.fake_sitemap)
    c = db.save_client({"name": "Madesa", "domain": "madesa.com", "country": "br"})
    yield c
    llm.OVERRIDE = None
    batch.COLLECT_KW.clear()
    db._engine = db._Session = None


def test_parse_lines_and_table():
    items = batch.parse_lines("rack para sala\n\nmesa de centro ; Como escolher mesa ; mesa redonda, mesa de vidro ; foco em sala pequena\nRack para sala")
    assert [i["keyword"] for i in items] == ["rack para sala", "mesa de centro"]
    assert items[1]["secondary"] == ["mesa redonda", "mesa de vidro"] and items[1]["notes"] == "foco em sala pequena"
    df = pd.DataFrame({"Palavra-chave": ["sofá retrátil", None], "Pauta": ["Guia", None],
                       "Secundárias": ["sofá 3 lugares, sofá cama", None]})
    t = batch.parse_table(df)
    assert t == [{"keyword": "sofá retrátil", "topic": "Guia", "secondary": ["sofá 3 lugares", "sofá cama"], "notes": ""}]


def test_analysis_batch_with_text(tmpdb):
    items = batch.parse_lines("rack ideal para sala\nrack para sala pequena")
    bid = batch.create_analysis_batch(tmpdb.id, None, items, with_text=True)
    # espera o processador em segundo plano terminar
    import time
    for _ in range(100):
        if db.pending_count() == 0:
            break
        time.sleep(0.1)
    b = [x for x in db.list_batches() if x["batch_id"] == bid][0]
    assert [j.status for j in b["jobs"]] == ["concluido", "concluido"], [j.error for j in b["jobs"]]
    assert all(j.briefing_id and j.content_id for j in b["jobs"])
    z = zipfile.ZipFile(io.BytesIO(batch.batch_zip(b)))
    names = z.namelist()
    assert len(names) == 4 and sum("Análise" in n for n in names) == 2


def test_text_batch_and_error_retry(tmpdb):
    items = batch.parse_lines("rack ideal para sala")
    batch.create_analysis_batch(tmpdb.id, None, items)
    batch.run_pending()
    b1 = db.list_briefings()[0]
    broken = db.save_briefing({"client_id": tmpdb.id, "focus_keyword": "sem estrutura", "analysis": {}})
    bid = batch.create_text_batch([b1.id, broken.id], None)
    batch.run_pending()
    jobs = [x for x in db.list_batches() if x["batch_id"] == bid][0]["jobs"]
    assert [j.status for j in jobs] == ["concluido", "erro"] and "estrutura" in jobs[1].error
    db.retry_failed(bid)
    assert db.pending_count() == 1
    db.cancel_batch(bid)
    assert db.pending_count() == 0


def test_running_jobs_resume_after_restart(tmpdb):
    batch.create_analysis_batch.__wrapped__ if hasattr(batch.create_analysis_batch, "__wrapped__") else None
    db.create_jobs([{"batch_id": "x", "client_id": tmpdb.id, "kind": "analise", "status": "rodando",
                     "payload": {"keyword": "rack"}}])
    db.reset_running_jobs()
    assert db.pending_count() == 1
    batch.run_pending()
    assert db.pending_count() == 0
