"""Provedores de palavras-chave.

Toda a aplicação conversa só com a interface KeywordProvider. Para trocar Ahrefs por Semrush,
basta implementar SemrushProvider e mudar KEYWORD_PROVIDER nos secrets.

Formato padrão de cada keyword retornada:
    {"keyword": str, "volume": int|None, "difficulty": int|None, "cpc": float|None,
     "traffic_potential": int|None, "intents": list[str], "parent_topic": str|None,
     "source": str}
"""
from __future__ import annotations

import requests

from core import config


class KeywordProviderError(RuntimeError):
    pass


class KeywordProvider:
    name = "base"

    def overview(self, keywords: list[str], country: str) -> list[dict]:
        raise NotImplementedError

    def matching_terms(self, keyword: str, country: str, limit: int = 50,
                       questions: bool = False) -> list[dict]:
        raise NotImplementedError

    def related_terms(self, keyword: str, country: str, limit: int = 50) -> list[dict]:
        raise NotImplementedError

    def units_used(self) -> int:
        return 0


# ---------------------------------------------------------------- Ahrefs (API v3)

class AhrefsProvider(KeywordProvider):
    name = "ahrefs"
    BASE = "https://api.ahrefs.com/v3/keywords-explorer"
    FIELDS = "keyword,volume,difficulty,cpc,traffic_potential,intents,parent_topic"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.get("api_key", section="ahrefs") or config.get("AHREFS_API_KEY")
        if not self.api_key:
            raise KeywordProviderError("Chave da API do Ahrefs não configurada ([ahrefs] api_key).")
        self.calls = 0

    def _get(self, endpoint: str, params: dict) -> list[dict]:
        params = {"output": "json", **params}
        r = requests.get(f"{self.BASE}/{endpoint}", params=params, timeout=60,
                         headers={"Authorization": f"Bearer {self.api_key}",
                                  "Accept": "application/json"})
        self.calls += 1
        if r.status_code != 200:
            raise KeywordProviderError(f"Ahrefs {endpoint} retornou {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data.get("keywords", data if isinstance(data, list) else [])

    @staticmethod
    def _norm(row: dict, source: str) -> dict:
        intents = row.get("intents") or {}
        if isinstance(intents, dict):
            intents = [k for k, v in intents.items() if v]
        parent = row.get("parent_topic")
        if isinstance(parent, dict):
            parent = parent.get("keyword")
        return {
            "keyword": row.get("keyword", ""),
            "volume": row.get("volume"),
            "difficulty": row.get("difficulty"),
            "cpc": (row.get("cpc") / 100) if isinstance(row.get("cpc"), (int, float)) else None,  # Ahrefs devolve cpc em centavos
            "traffic_potential": row.get("traffic_potential"),
            "intents": intents or [],
            "parent_topic": parent,
            "source": source,
        }

    def overview(self, keywords, country):
        rows = self._get("overview", {"keywords": ",".join(keywords), "country": country,
                                      "select": self.FIELDS})
        return [self._norm(r, "overview") for r in rows]

    def matching_terms(self, keyword, country, limit=50, questions=False):
        rows = self._get("matching-terms", {
            "keywords": keyword, "country": country, "select": self.FIELDS,
            "limit": limit, "order_by": "volume:desc",
            "terms": "questions" if questions else "all", "match_mode": "terms",
        })
        return [self._norm(r, "perguntas" if questions else "matching") for r in rows]

    def related_terms(self, keyword, country, limit=50):
        rows = self._get("related-terms", {
            "keywords": keyword, "country": country, "select": self.FIELDS,
            "limit": limit, "order_by": "volume:desc", "terms": "all", "view_for": "top_10",
        })
        return [self._norm(r, "related") for r in rows]

    def units_used(self):
        return self.calls


# ---------------------------------------------------------------- Semrush (futuro)

class SemrushProvider(KeywordProvider):
    """Esqueleto para a migração futura.

    Mapeamento sugerido:
      overview        -> type=phrase_this
      matching_terms  -> type=phrase_fullsearch  (questions=True -> type=phrase_questions)
      related_terms   -> type=phrase_related
    A API do Semrush devolve CSV separado por ';' (colunas Ph, Nq, Kd, Cp, In).
    """
    name = "semrush"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.get("api_key", section="semrush")
        raise KeywordProviderError("Provedor Semrush ainda não implementado. Use KEYWORD_PROVIDER = 'ahrefs'.")


def get_provider(name: str | None = None) -> KeywordProvider:
    name = (name or config.KEYWORD_PROVIDER or "ahrefs").lower()
    if name == "ahrefs":
        return AhrefsProvider()
    if name == "semrush":
        return SemrushProvider()
    raise KeywordProviderError(f"Provedor de keywords desconhecido: {name}")


def collect_keyword_universe(provider: KeywordProvider, focus: str, country: str,
                             extra_seeds: list[str] | None = None, limit: int = 50) -> dict:
    """Coleta tudo o que a análise precisa sobre palavras-chave em poucas chamadas."""
    seeds = [focus] + [s for s in (extra_seeds or []) if s and s != focus]
    focus_metrics = provider.overview(seeds[:10], country)
    candidates: dict[str, dict] = {}
    for fn, kwargs in ((provider.matching_terms, {}),
                       (provider.matching_terms, {"questions": True}),
                       (provider.related_terms, {})):
        try:
            for row in fn(focus, country, limit=limit, **kwargs):
                k = row["keyword"].strip().lower()
                if k and k != focus.lower() and k not in candidates:
                    candidates[k] = row
        except Exception as e:  # uma falha parcial não derruba a análise
            candidates.setdefault("__erros__", {"keyword": "__erros__", "erros": []})["erros"].append(str(e))
    errors = candidates.pop("__erros__", {}).get("erros", [])
    ordered = sorted(candidates.values(), key=lambda r: r.get("volume") or 0, reverse=True)
    return {"focus": focus_metrics, "candidates": ordered, "errors": errors,
            "provider": provider.name, "calls": provider.units_used()}
