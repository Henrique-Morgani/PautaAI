"""Leitura de configuração: st.secrets (Streamlit Cloud) com fallback para variáveis de ambiente."""
import os

try:
    import streamlit as st
except Exception:  # permite rodar o pipeline fora do Streamlit (testes, scripts)
    st = None


def get(key: str, default=None, section: str | None = None):
    """Busca uma chave em st.secrets[section][key] ou st.secrets[key]; depois em os.environ."""
    if st is not None:
        try:
            if section and section in st.secrets and key in st.secrets[section]:
                return st.secrets[section][key]
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
    env_key = f"{section}_{key}".upper() if section else key.upper()
    return os.environ.get(env_key, os.environ.get(key.upper(), default))


def get_section(section: str) -> dict:
    if st is not None:
        try:
            if section in st.secrets:
                return dict(st.secrets[section])
        except Exception:
            pass
    return {}


APP_NAME = get("APP_NAME", "PautaAI")

# Provedor de palavras-chave: "ahrefs" hoje, "semrush" no futuro
KEYWORD_PROVIDER = get("KEYWORD_PROVIDER", "ahrefs")

# Provedor de IA: "gemini" ou "anthropic"
LLM_PROVIDER = get("LLM_PROVIDER", "gemini")
