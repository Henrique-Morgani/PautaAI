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
