"""Banco de dados: Postgres (Neon) em produção, SQLite local como fallback.

Tabelas:
- users: login próprio do app (separado do DizemAI)
- clients: cadastro de clientes com contexto de marca, sitemap e regras de texto
- briefings: cada análise gerada (dados brutos + análise da IA + versão revisada)
- contents: textos gerados a partir de um briefing
"""
import json
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer,
                        String, Text, create_engine, select)
from sqlalchemy.orm import declarative_base, sessionmaker

from core import config

Base = declarative_base()


def _now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "pa_users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255))
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class Client(Base):
    __tablename__ = "pa_clients"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    domain = Column(String(255), nullable=False)          # ex.: madesa.com
    blog_path = Column(String(255), default="")            # ex.: /blog
    sitemap_url = Column(String(500), default="")          # ex.: https://www.madesa.com/sitemap.xml
    country = Column(String(10), default="br")
    language = Column(String(10), default="pt-br")
    brand_context = Column(Text, default="")               # o que a marca vende, posicionamento
    tone_of_voice = Column(Text, default="")               # tom de voz e regras de escrita
    competitors = Column(Text, default="")                 # concorrentes diretos (1 por linha)
    priority_links = Column(Text, default="")              # URLs que sempre devem ser consideradas (1 por linha)
    forbidden_terms = Column(Text, default="")             # termos que não podem aparecer
    created_at = Column(DateTime(timezone=True), default=_now)


class Briefing(Base):
    __tablename__ = "pa_briefings"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("pa_clients.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("pa_users.id"))
    focus_keyword = Column(String(500), nullable=False)
    topic = Column(String(500), default="")                 # pauta/título de trabalho
    status = Column(String(30), default="rascunho")         # rascunho | revisado | texto_gerado
    raw_data = Column(JSON)                                 # keywords, SERP, concorrentes, sitemap
    analysis = Column(JSON)                                 # saída da IA (editável na revisão)
    gdoc_url = Column(String(500), default="")
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class Content(Base):
    __tablename__ = "pa_contents"
    id = Column(Integer, primary_key=True)
    briefing_id = Column(Integer, ForeignKey("pa_briefings.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("pa_users.id"))
    body_markdown = Column(Text)
    gdoc_url = Column(String(500), default="")
    created_at = Column(DateTime(timezone=True), default=_now)


class Job(Base):
    """Item de um lote. kind: analise | texto | analise_texto."""
    __tablename__ = "pa_jobs"
    id = Column(Integer, primary_key=True)
    batch_id = Column(String(40), index=True, nullable=False)
    batch_name = Column(String(255), default="")
    client_id = Column(Integer, ForeignKey("pa_clients.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("pa_users.id"))
    kind = Column(String(20), nullable=False)
    status = Column(String(20), default="pendente", index=True)   # pendente | rodando | concluido | erro
    payload = Column(JSON)                                          # keyword, topic, secundarias, notas, opções
    briefing_id = Column(Integer, ForeignKey("pa_briefings.id"))
    content_id = Column(Integer, ForeignKey("pa_contents.id"))
    step = Column(String(120), default="")
    error = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


_engine = None
_Session = None


def _database_url() -> str:
    url = config.get("DATABASE_URL", "")
    if not url:
        return "sqlite:///pautaai_local.db"
    # Neon fornece postgresql://...; o SQLAlchemy usa o driver psycopg 3
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True, future=True,
                                json_serializer=lambda o: json.dumps(o, ensure_ascii=False, default=str))
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def session():
    engine()
    return _Session()


# ---------- helpers ----------

def list_clients():
    with session() as s:
        return list(s.scalars(select(Client).order_by(Client.name)))


def get_client(client_id: int):
    with session() as s:
        return s.get(Client, client_id)


def save_client(data: dict, client_id: int | None = None):
    with session() as s:
        obj = s.get(Client, client_id) if client_id else Client()
        for k, v in data.items():
            setattr(obj, k, v)
        s.add(obj)
        s.commit()
        return obj


def save_briefing(data: dict, briefing_id: int | None = None):
    with session() as s:
        obj = s.get(Briefing, briefing_id) if briefing_id else Briefing()
        for k, v in data.items():
            setattr(obj, k, v)
        s.add(obj)
        s.commit()
        return obj


def get_briefing(briefing_id: int):
    with session() as s:
        return s.get(Briefing, briefing_id)


def list_briefings(client_id: int | None = None, limit: int = 100):
    with session() as s:
        q = select(Briefing).order_by(Briefing.created_at.desc()).limit(limit)
        if client_id:
            q = q.where(Briefing.client_id == client_id)
        return list(s.scalars(q))


def save_content(data: dict):
    with session() as s:
        obj = Content(**data)
        s.add(obj)
        s.commit()
        return obj


def list_contents(briefing_id: int):
    with session() as s:
        return list(s.scalars(select(Content).where(Content.briefing_id == briefing_id)
                              .order_by(Content.created_at.desc())))


# ---------- lotes

def create_jobs(rows: list[dict]) -> None:
    with session() as s:
        for r in rows:
            s.add(Job(**r))
        s.commit()


def update_job(job_id: int, **fields):
    with session() as s:
        j = s.get(Job, job_id)
        for k, v in fields.items():
            setattr(j, k, v)
        s.commit()


def claim_next_job():
    """Pega o próximo item pendente (o mais antigo) e marca como rodando."""
    with session() as s:
        j = s.scalars(select(Job).where(Job.status == "pendente").order_by(Job.id).limit(1)).first()
        if not j:
            return None
        j.status, j.step = "rodando", "iniciando"
        s.commit()
        return j


def reset_running_jobs():
    """Depois de um reboot do app, itens que estavam rodando voltam para a fila."""
    with session() as s:
        for j in s.scalars(select(Job).where(Job.status == "rodando")):
            j.status, j.step = "pendente", "retomado após reinício"
        s.commit()


def pending_count() -> int:
    with session() as s:
        return len(list(s.scalars(select(Job.id).where(Job.status.in_(["pendente", "rodando"])))))


def list_batches(limit: int = 30) -> list[dict]:
    with session() as s:
        jobs = list(s.scalars(select(Job).order_by(Job.id.desc()).limit(2000)))
    batches: dict[str, dict] = {}
    for j in jobs:
        b = batches.setdefault(j.batch_id, {"batch_id": j.batch_id, "name": j.batch_name, "client_id": j.client_id,
                                            "created_at": j.created_at, "jobs": []})
        b["jobs"].append(j)
        b["created_at"] = min(b["created_at"], j.created_at)
    out = sorted(batches.values(), key=lambda b: b["created_at"], reverse=True)[:limit]
    for b in out:
        b["jobs"].sort(key=lambda j: j.id)
    return out


def cancel_batch(batch_id: str):
    with session() as s:
        for j in s.scalars(select(Job).where(Job.batch_id == batch_id, Job.status == "pendente")):
            j.status, j.error = "erro", "cancelado pelo usuário"
        s.commit()


def retry_failed(batch_id: str):
    with session() as s:
        for j in s.scalars(select(Job).where(Job.batch_id == batch_id, Job.status == "erro")):
            j.status, j.error, j.step = "pendente", "", "nova tentativa"
        s.commit()


def get_content(content_id: int):
    with session() as s:
        return s.get(Content, content_id)
