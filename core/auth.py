"""Login próprio do app (independente do DizemAI).

- Usuários ficam na tabela pa_users (senha com bcrypt).
- O primeiro admin é criado a partir de [admin] email/senha nos secrets, na primeira execução.
- Admins podem criar e desativar usuários pela tela "Usuários".
"""
import bcrypt
import streamlit as st
from sqlalchemy import select

from core import config, db


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _check(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), h.encode())
    except Exception:
        return False


def ensure_bootstrap_admin():
    admin = config.get_section("admin")
    email = (admin.get("email") or config.get("ADMIN_EMAIL", "")).strip().lower()
    pw = admin.get("password") or config.get("ADMIN_PASSWORD", "")
    if not email or not pw:
        return
    with db.session() as s:
        exists = s.scalar(select(db.User).where(db.User.email == email))
        if not exists:
            s.add(db.User(email=email, name=admin.get("name", "Admin"),
                          password_hash=_hash(pw), is_admin=True))
            s.commit()


def create_user(email: str, name: str, password: str, is_admin: bool = False):
    email = email.strip().lower()
    with db.session() as s:
        if s.scalar(select(db.User).where(db.User.email == email)):
            raise ValueError("Já existe um usuário com esse email.")
        u = db.User(email=email, name=name, password_hash=_hash(password), is_admin=is_admin)
        s.add(u)
        s.commit()
        return u


def set_active(user_id: int, active: bool):
    with db.session() as s:
        u = s.get(db.User, user_id)
        u.active = active
        s.commit()


def change_password(user_id: int, new_password: str):
    with db.session() as s:
        u = s.get(db.User, user_id)
        u.password_hash = _hash(new_password)
        s.commit()


def list_users():
    with db.session() as s:
        return list(s.scalars(select(db.User).order_by(db.User.email)))


def current_user():
    return st.session_state.get("user")


def logout():
    st.session_state.pop("user", None)
    st.rerun()


def login_screen():
    ensure_bootstrap_admin()
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown(f"<h1 style='text-align:center;margin-bottom:0'>{config.APP_NAME}</h1>",
                    unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#6b7280'>Análise SEO para produção de conteúdo</p>",
                    unsafe_allow_html=True)
        with st.form("login"):
            email = st.text_input("Email")
            pw = st.text_input("Senha", type="password")
            ok = st.form_submit_button("Entrar", width="stretch", type="primary")
        if ok:
            with db.session() as s:
                u = s.scalar(select(db.User).where(db.User.email == email.strip().lower()))
            if u and u.active and _check(pw, u.password_hash):
                st.session_state["user"] = {"id": u.id, "email": u.email,
                                            "name": u.name or u.email, "is_admin": u.is_admin}
                st.rerun()
            else:
                st.error("Email ou senha inválidos.")
