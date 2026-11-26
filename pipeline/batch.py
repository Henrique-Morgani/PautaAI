"""Lotes: várias análises e/ou textos processados em segundo plano, um por vez.

- Os itens ficam na tabela pa_jobs (sobrevivem ao fechar a aba).
- Um único processador (thread) por instância do app consome a fila. Ele é iniciado sempre que
  alguém abre o app e há itens pendentes, então continua mesmo que a aba seja fechada.
- Se o app reiniciar no meio, os itens "rodando" voltam para a fila automaticamente.
- Um item por vez, para respeitar os limites de uso do Ahrefs, do Serper e do Gemini.
"""
from __future__ import annotations

import io
import re
import threading
import time
import unicodedata
import uuid
import zipfile

from core import db
from export import gdocs, render
from pipeline import briefing as bp
from pipeline import content as cp

_lock = threading.Lock()
_worker: threading.Thread | None = None

# permite injetar fakes nos testes
COLLECT_KW: dict = {}


def client_dict(c) -> dict:
    return {k: getattr(c, k) for k in ("id", "name", "domain", "blog_path", "sitemap_url", "country", "language",
                                       "brand_context", "tone_of_voice", "competitors", "priority_links",
                                       "forbidden_terms")}


# ------------------------------------------------------------------ entrada

def parse_lines(text: str) -> list[dict]:
    """Uma pauta por linha: palavra-chave ; pauta (opcional) ; secundárias separadas por vírgula (opcional)
    ; observações (opcional)."""
    items = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(";")]
        kw = parts[0]
        if not kw:
            continue
        items.append({
            "keyword": kw,
            "topic": parts[1] if len(parts) > 1 else "",
            "secondary": [x.strip() for x in parts[2].split(",") if x.strip()] if len(parts) > 2 else [],
            "notes": parts[3] if len(parts) > 3 else "",
        })
    return _dedupe(items)


def parse_table(df) -> list[dict]:
    """Planilha com colunas: palavra-chave | pauta | secundárias | observações (nomes flexíveis)."""
    def col(*names):
        for c in df.columns:
            n = _norm(str(c))
            if any(n.startswith(x) for x in names):
                return c
        return None

    ck = col("palavra", "keyword", "kw", "termo") or df.columns[0]
    ct, cs, cn = col("pauta", "titulo", "tema"), col("secund"), col("observ", "nota", "briefing")
    items = []
    for _, r in df.iterrows():
        kw = str(r.get(ck) or "").strip()
        if not kw or kw.lower() == "nan":
            continue
        val = lambda c: ("" if c is None or str(r.get(c)) == "nan" else str(r.get(c)).strip())
        items.append({"keyword": kw, "topic": val(ct),
                      "secondary": [x.strip() for x in re.split(r"[,\n;]", val(cs)) if x.strip()],
                      "notes": val(cn)})
    return _dedupe(items)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        k = _norm(it["keyword"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ------------------------------------------------------------------ criação de lotes

def create_analysis_batch(client_id: int, user_id: int, items: list[dict], with_text: bool = False,
                          size: str = "1200 a 1800", extra: str = "", name: str = "") -> str:
    batch_id = uuid.uuid4().hex[:12]
    kind = "analise_texto" if with_text else "analise"
    name = name or f"{len(items)} pautas ({time.strftime('%d/%m %H:%M')})"
    db.create_jobs([{"batch_id": batch_id, "batch_name": name, "client_id": client_id, "user_id": user_id,
                     "kind": kind, "payload": {**it, "size": size, "extra": extra}} for it in items])
    ensure_worker()
    return batch_id


def create_text_batch(briefing_ids: list[int], user_id: int, size: str = "1200 a 1800", extra: str = "",
                      name: str = "") -> str:
    batch_id = uuid.uuid4().hex[:12]
    rows = []
    for bid in briefing_ids:
        b = db.get_briefing(bid)
        if not b:
            continue
        rows.append({"batch_id": batch_id, "batch_name": name or f"{len(briefing_ids)} textos ({time.strftime('%d/%m %H:%M')})",
                     "client_id": b.client_id, "user_id": user_id, "kind": "texto", "briefing_id": b.id,
                     "payload": {"keyword": b.focus_keyword, "topic": b.topic, "size": size, "extra": extra}})
    db.create_jobs(rows)
    ensure_worker()
    return batch_id


# ------------------------------------------------------------------ processamento

def doc_title(client_name: str, focus: str, kind: str) -> str:
    label = "Análise para produção de conteúdo" if kind == "analise" else "Conteúdo | Produção de Conteúdo de Blog"
    return f"{client_name} | SEO | {label} - {focus}"


def process_job(job) -> None:
    """Executa um item. Lança exceção em caso de erro (o worker registra)."""
    client = db.get_client(job.client_id)
    cd = client_dict(client)
    p = job.payload or {}
    focus = p.get("keyword", "").strip()
    briefing_id = job.briefing_id

    if job.kind in ("analise", "analise_texto"):
        db.update_job(job.id, step="coletando dados")
        raw = bp.collect(cd, focus, p.get("secondary") or [], "", **COLLECT_KW)
        db.update_job(job.id, step="analisando com IA")
        analysis = bp.analyze(cd, focus, p.get("topic", ""), raw, p.get("notes", ""),
                              kw_provider=COLLECT_KW.get("kw_provider"))
        b = db.save_briefing({"client_id": job.client_id, "user_id": job.user_id, "focus_keyword": focus,
                              "topic": p.get("topic", ""), "raw_data": {**raw, "notes": p.get("notes", "")},
                              "analysis": analysis, "status": "rascunho"})
        briefing_id = b.id
        db.update_job(job.id, briefing_id=b.id)
        if gdocs.is_configured():
            db.update_job(job.id, step="criando Google Doc da análise")
            url = gdocs.create_doc(doc_title(client.name, focus, "analise"),
                                   render.briefing_html(cd, focus, raw, analysis))
            db.save_briefing({"gdoc_url": url}, b.id)

    if job.kind in ("texto", "analise_texto"):
        b = db.get_briefing(briefing_id)
        if not b or not (b.analysis or {}).get("estrutura"):
            raise RuntimeError("A análise não tem estrutura de headings. Revise antes de gerar o texto.")
        db.update_job(job.id, step="escrevendo o texto")
        body = cp.generate(cd, b.focus_keyword, b.analysis, p.get("extra", ""), p.get("size", "1200 a 1800"))
        c = db.save_content({"briefing_id": b.id, "user_id": job.user_id, "body_markdown": body})
        db.update_job(job.id, content_id=c.id)
        db.save_briefing({"status": "texto_gerado"}, b.id)
        if gdocs.is_configured():
            db.update_job(job.id, step="criando Google Doc do texto")
            url = gdocs.create_doc(doc_title(client.name, b.focus_keyword, "texto"),
                                   render.content_html(b.focus_keyword, b.analysis, body))
            with db.session() as s:
                obj = s.get(db.Content, c.id)
                obj.gdoc_url = url
                s.commit()


def run_pending(max_jobs: int | None = None) -> int:
    """Processa a fila até esvaziar (ou até max_jobs). Devolve quantos itens processou."""
    done = 0
    while max_jobs is None or done < max_jobs:
        job = db.claim_next_job()
        if not job:
            break
        try:
            process_job(job)
            db.update_job(job.id, status="concluido", step="concluído", error="")
        except Exception as ex:
            db.update_job(job.id, status="erro", step="erro", error=str(ex)[:1500])
        done += 1
    return done


def _loop():
    global _worker
    try:
        db.reset_running_jobs()
        idle = 0
        while idle < 3:
            if run_pending(max_jobs=1):
                idle = 0
            else:
                idle += 1
                time.sleep(5)
    finally:
        with _lock:
            _worker = None


def ensure_worker() -> bool:
    """Inicia o processador se houver itens pendentes e ele ainda não estiver rodando."""
    global _worker
    with _lock:
        if _worker and _worker.is_alive():
            return True
        if db.pending_count() == 0:
            return False
        _worker = threading.Thread(target=_loop, name="pautaai-batch", daemon=True)
        _worker.start()
        return True


def worker_alive() -> bool:
    return bool(_worker and _worker.is_alive())


# ------------------------------------------------------------------ download

def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip()[:150]


def batch_zip(batch: dict) -> bytes:
    """Um .html por análise e por texto concluídos (abrem no Word e importam no Google Docs)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for j in batch["jobs"]:
            if j.status != "concluido":
                continue
            client = db.get_client(j.client_id)
            b = db.get_briefing(j.briefing_id) if j.briefing_id else None
            if not b:
                continue
            if j.kind in ("analise", "analise_texto"):
                html = render.briefing_html(client_dict(client), b.focus_keyword, b.raw_data or {}, b.analysis or {})
                z.writestr(_safe(doc_title(client.name, b.focus_keyword, "analise")) + ".html", html)
            if j.content_id:
                c = db.get_content(j.content_id)
                html = render.content_html(b.focus_keyword, b.analysis or {}, c.body_markdown or "")
                z.writestr(_safe(doc_title(client.name, b.focus_keyword, "texto")) + ".html", html)
    return buf.getvalue()
