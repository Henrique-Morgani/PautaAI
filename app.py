"""PautaAI: análise SEO para produção de conteúdo + geração do texto.

Fluxo: Nova análise -> coleta (Ahrefs, Serper, concorrentes, sitemap) -> análise da IA
       -> revisão do analista -> Google Doc do briefing -> geração do texto -> Google Doc do texto
"""
from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import streamlit as st

from ai import llm
from core import auth, config, db
from export import gdocs, render
from pipeline import briefing as bp
from pipeline import content as cp
from pipeline import validate

st.set_page_config(page_title=config.APP_NAME, page_icon="📝", layout="wide")

st.markdown("""
<style>
.block-container{padding-top:2rem;max-width:1250px}
.pa-card{border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;background:#fff}
.pa-big{font-size:1.6rem;font-weight:700;margin:0}
.pa-muted{color:#6b7280;font-size:.85rem;margin:0}
.pa-ok{color:#047857} .pa-warn{color:#b45309} .pa-err{color:#b91c1c}
div[data-testid="stSidebarNav"]{display:none}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers

def go(page: str, **state):
    st.session_state["page"] = page
    st.session_state.update(state)
    st.rerun()


def client_dict(c) -> dict:
    return {k: getattr(c, k) for k in ("id", "name", "domain", "blog_path", "sitemap_url", "country", "language",
                                       "brand_context", "tone_of_voice", "competitors", "priority_links",
                                       "forbidden_terms")}


def lines(s: str) -> list[str]:
    return [x.strip() for x in (s or "").splitlines() if x.strip()]


def card(label, value, help_text=""):
    st.markdown(f"<div class='pa-card'><p class='pa-muted'>{label}</p><p class='pa-big'>{value}</p>"
                f"<p class='pa-muted'>{help_text}</p></div>", unsafe_allow_html=True)


def show_checks(checks):
    for c in checks:
        icon = "✅" if c["ok"] else ("❌" if c["nivel"] == "erro" else "⚠️")
        st.markdown(f"{icon} **{c['item']}** <span class='pa-muted'>{c['detalhe']}</span>", unsafe_allow_html=True)


def slug_title(focus: str, kind: str, client_name: str) -> str:
    return f"{client_name} | SEO | {kind} - {focus}"


def export_buttons(title: str, html: str, key: str, on_success=None):
    c1, c2 = st.columns([1, 1])
    with c1:
        if gdocs.is_configured():
            if st.button("Criar Google Doc", key=f"gd_{key}", type="primary", width="stretch"):
                with st.spinner("Criando documento no Drive..."):
                    try:
                        url = gdocs.create_doc(title, html)
                        st.success(f"Documento criado: [abrir no Google Docs]({url})")
                        if on_success:
                            on_success(url)
                    except Exception as ex:
                        st.error(str(ex))
        else:
            st.info("Google Drive não configurado. Use o download e importe no Drive (o HTML abre como Google Doc).")
    with c2:
        st.download_button("Baixar arquivo (.html)", html.encode("utf-8"), file_name=f"{title}.html",
                           mime="text/html", key=f"dl_{key}", width="stretch")


# ------------------------------------------------------------------ páginas

def page_new():
    st.title("Nova análise")
    clients = db.list_clients()
    if not clients:
        st.warning("Cadastre um cliente antes de criar a primeira análise.")
        if st.button("Cadastrar cliente", type="primary"):
            go("clientes")
        return

    with st.form("nova"):
        c1, c2 = st.columns([1, 2])
        client = c1.selectbox("Cliente", clients, format_func=lambda c: c.name)
        focus = c2.text_input("Palavra-chave foco", placeholder="ex.: rack ideal para sala")
        topic = st.text_input("Pauta ou título de trabalho (opcional)",
                              placeholder="ex.: Como escolher o rack ideal para a sala na Copa do Mundo")
        c3, c4 = st.columns(2)
        manual = c3.text_area("Secundárias obrigatórias (opcional, uma por linha)", height=120)
        notes = c4.text_area("Observações para a análise (opcional)", height=120,
                             placeholder="ex.: data sazonal, produtos para destacar, abordagem pedida pelo cliente")
        with st.expander("Opcional: colar Visão de IA e PAA manualmente (use se não vierem na coleta)"):
            aio = st.text_area("Texto da Visão de IA", height=140)
            paa_txt = st.text_area("Perguntas do PAA (uma por linha)", height=100)
        submitted = st.form_submit_button("Gerar análise", type="primary", width="stretch")

    if not submitted:
        return
    if not focus.strip():
        st.error("Informe a palavra-chave foco.")
        return

    cd = client_dict(client)
    with st.status("Gerando análise...", expanded=True) as status:
        bar = st.progress(0.0)

        def progress(msg, pct):
            status.update(label=msg)
            st.write(msg)
            bar.progress(pct)

        raw = bp.collect(cd, focus.strip(), lines(manual), aio, progress=progress, paa_manual=lines(paa_txt))
        for err in raw.get("errors", []):
            st.warning(err)
        progress("Analisando com IA", 0.85)
        try:
            analysis = bp.analyze(cd, focus.strip(), topic.strip(), raw, notes)
        except Exception as ex:
            status.update(label="Falha na análise da IA", state="error")
            st.error(f"A coleta foi salva, mas a análise falhou: {ex}")
            b = db.save_briefing({"client_id": client.id, "user_id": auth.current_user()["id"],
                                  "focus_keyword": focus.strip(), "topic": topic.strip(),
                                  "raw_data": raw, "analysis": {}, "status": "rascunho"})
            st.session_state["briefing_id"] = b.id
            return
        bar.progress(1.0)
        status.update(label="Análise pronta", state="complete")

    b = db.save_briefing({"client_id": client.id, "user_id": auth.current_user()["id"],
                          "focus_keyword": focus.strip(), "topic": topic.strip(),
                          "raw_data": {**raw, "notes": notes}, "analysis": analysis, "status": "rascunho"})
    go("briefing", briefing_id=b.id)


def _headings_df(heads):
    return pd.DataFrame([{"Nível": f"H{h['level']}", "Texto": h["text"]} for h in heads] or
                        [{"Nível": "H1", "Texto": ""}])


def _df_headings(df):
    out = []
    for _, r in df.iterrows():
        txt = str(r.get("Texto") or "").strip()
        m = re.match(r"H?([1-6])", str(r.get("Nível") or "H2"))
        if txt:
            out.append({"level": int(m.group(1)) if m else 2, "text": txt})
    return out


def page_briefing():
    bid = st.session_state.get("briefing_id")
    b = db.get_briefing(bid) if bid else None
    if not b:
        st.info("Selecione uma análise no histórico.")
        return
    client = db.get_client(b.client_id)
    cd = client_dict(client)
    raw, a = b.raw_data or {}, dict(b.analysis or {})
    kw, serp = raw.get("keywords", {}), raw.get("serp", {})

    st.caption(f"{client.name} · criada em {b.created_at:%d/%m/%Y %H:%M} · status: {b.status}")
    st.title(b.focus_keyword)
    if b.topic:
        st.markdown(f"**Pauta:** {b.topic}")

    fm = (kw.get("focus") or [{}])[0] if kw.get("focus") else {}
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Volume da foco", render._fmt_num(fm.get("volume")), f"KD {render._fmt_num(fm.get('difficulty'))}")
    with c2:
        card("Candidatas a secundárias", len(kw.get("candidates", [])), f"fonte: {kw.get('provider', '-')}")
    with c3:
        lidos = sum(1 for c in raw.get("competitors", []) if c.get("status") == "ok")
        card("Concorrentes lidos", f"{lidos}/{len(raw.get('competitors', []))}", "top 10 da SERP")
    with c4:
        card("Links internos candidatos", len(raw.get("internal_candidates", [])),
             f"{render._fmt_num(raw.get('sitemap_total', 0))} URLs no sitemap")

    for err in raw.get("errors", []):
        st.warning(err)
    al = (a.get("alerta_serp") or {}) if a else {}
    if al.get("alerta"):
        st.error(f"**Alerta de intenção:** {al['alerta']}"
                 + (f"  \n**Alternativa sugerida:** {al['keyword_alternativa']}" if al.get("keyword_alternativa") else ""))

    tabs = st.tabs(["1. Dados coletados", "2. Análise", "3. Estrutura", "4. Exportar briefing", "5. Texto"])

    # ---------- 1. dados
    with tabs[0]:
        st.subheader("Palavras-chave")
        cand = pd.DataFrame(kw.get("candidates", []))
        if not cand.empty:
            cand["intents"] = cand["intents"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
            st.dataframe(cand[["keyword", "volume", "difficulty", "traffic_potential", "intents", "source"]],
                         hide_index=True, width="stretch", height=280)
        st.subheader("SERP")
        if serp.get("organic"):
            st.dataframe(pd.DataFrame(serp["organic"])[["position", "title", "description", "url"]],
                         hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**PAA** ({raw.get('paa_source') or 'não exibido'})")
            for q in serp.get("paa", []) or ["(nenhuma)"]:
                st.markdown(f"- {q}")
        with c2:
            st.markdown(f"**Visão de IA** ({raw.get('ai_overview_source') or 'não capturada'})")
            st.write(raw.get("ai_overview") or "A SERP não exibiu Visão de IA na coleta.")
        st.subheader("Concorrentes")
        for c in raw.get("competitors", []):
            with st.expander(f"[{c.get('position')}] {c.get('domain')} · {c.get('word_count') or 0} palavras"):
                st.caption(c.get("url"))
                if c.get("status") != "ok":
                    st.write(c.get("error"))
                    continue
                st.caption(f"tabelas {c.get('tables')} · listas {c.get('lists')} · imagens {c.get('images')} · "
                           f"FAQ schema {'sim' if c.get('has_faq_schema') else 'não'} · "
                           f"publicado {c.get('published') or '-'} · atualizado {c.get('modified') or '-'}")
                for h in c.get("headings", []):
                    if not h.get("boilerplate"):
                        st.markdown(f"{'&nbsp;' * 4 * (h['level'] - 1)}`H{h['level']}` {h['text']}", unsafe_allow_html=True)

    # ---------- 2. análise (editável)
    with tabs[1]:
        if not a:
            st.error("Esta análise não tem a parte da IA. Gere novamente abaixo.")
        with st.form("analise"):
            sec = st.text_area("Palavras-chave secundárias (uma por linha)", "\n".join(a.get("secondary_keywords", [])), height=200)
            sem = st.text_area("Termos semânticos (um por linha)", "\n".join(a.get("semantic_terms", [])), height=110)
            al_txt = st.text_area("Alerta de intenção da SERP (deixe vazio se não houver)", al.get("alerta", ""), height=90)
            leit = st.text_area("Leitura estratégica do cenário", a.get("leitura_estrategica", ""), height=200)
            pos = st.text_input("Posicionamento", a.get("posicionamento", ""))
            st.markdown("**Concorrentes: característica e limitação**")
            comp_df = st.data_editor(pd.DataFrame(a.get("concorrentes") or [{"concorrente": "", "caracteristica": "", "limitacao": ""}]),
                                     num_rows="dynamic", width="stretch", key="comp_ed")
            dest = st.text_area("Concorrente de destaque", a.get("concorrente_destaque", ""), height=100)
            abp = st.text_area("Abordagem predominante (uma por linha)", "\n".join(a.get("abordagem_predominante", [])), height=130)
            abr = st.text_area("Abordagem recomendada", a.get("abordagem_recomendada", ""), height=110)
            rec_df = st.data_editor(pd.DataFrame(a.get("recursos_visuais") or [{"recurso": "", "descricao": ""}]),
                                    num_rows="dynamic", width="stretch", key="rec_ed")
            it = a.get("intencao", {})
            c1, c2 = st.columns([1, 2])
            it_tipo = c1.text_input("Tipo de intenção", it.get("tipo", ""))
            it_desc = c2.text_area("Descrição da intenção", it.get("descricao", ""), height=90)
            it_busca = st.text_area("A pessoa provavelmente busca (um por linha)", "\n".join(it.get("o_que_busca", [])), height=120)
            it_tom = st.text_area("Orientação de tom e conversão", it.get("orientacao_tom", ""), height=70)
            opo = st.text_area("Oportunidades de otimização (uma por linha)", "\n".join(a.get("oportunidades", [])), height=180)
            lb = a.get("link_building", {})
            lb_res = st.text_area("Link building: resumo", lb.get("resumo", ""), height=80)
            lb_df = st.data_editor(pd.DataFrame(lb.get("ativos") or [{"titulo": "", "descricao": ""}]),
                                   num_rows="dynamic", width="stretch", key="lb_ed")
            li_df = st.data_editor(pd.DataFrame(a.get("links_internos") or [{"url": "", "ancora": "", "onde": ""}]),
                                   num_rows="dynamic", width="stretch", key="li_ed")
            faq = st.text_area("FAQ (uma pergunta por linha)", "\n".join(a.get("faq", [])), height=110)
            save = st.form_submit_button("Salvar revisão", type="primary")
        if save:
            a.update({
                "alerta_serp": {**al, "alerta": al_txt.strip()},
                "secondary_keywords": lines(sec), "semantic_terms": lines(sem), "leitura_estrategica": leit,
                "posicionamento": pos, "concorrentes": comp_df.fillna("").to_dict("records"),
                "concorrente_destaque": dest, "abordagem_predominante": lines(abp), "abordagem_recomendada": abr,
                "recursos_visuais": rec_df.fillna("").to_dict("records"),
                "intencao": {"tipo": it_tipo, "descricao": it_desc, "o_que_busca": lines(it_busca), "orientacao_tom": it_tom},
                "oportunidades": lines(opo), "link_building": {"resumo": lb_res, "ativos": lb_df.fillna("").to_dict("records")},
                "links_internos": [r for r in li_df.fillna("").to_dict("records") if r.get("url")], "faq": lines(faq),
            })
            db.save_briefing({"analysis": a, "status": "revisado"}, b.id)
            st.success("Revisão salva.")
            st.rerun()

        with st.expander("Gerar a análise de novo (usa os mesmos dados coletados, sem gastar Ahrefs/Serper)"):
            extra = st.text_area("Orientação extra para a IA", key="regen_notes")
            if st.button("Gerar de novo"):
                with st.spinner("Analisando..."):
                    try:
                        new = bp.analyze(cd, b.focus_keyword, b.topic, raw, (raw.get("notes", "") + "\n" + extra).strip())
                        db.save_briefing({"analysis": new, "status": "rascunho"}, b.id)
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

    # ---------- 3. estrutura
    with tabs[2]:
        est = a.get("estrutura", {})
        with st.form("estrutura"):
            title = st.text_input("Title", est.get("title", ""))
            desc = st.text_area("Description", est.get("description", ""), height=80)
            url = st.text_input("URL", est.get("url", ""))
            st.markdown("**Heading tags** (edite, adicione ou remova linhas; nível H1 a H4)")
            hdf = st.data_editor(_headings_df(est.get("headings", [])), num_rows="dynamic", width="stretch",
                                 column_config={"Nível": st.column_config.SelectboxColumn(options=["H1", "H2", "H3", "H4"], width="small"),
                                                "Texto": st.column_config.TextColumn(width="large")},
                                 key="h_ed", height=520)
            save_est = st.form_submit_button("Salvar estrutura", type="primary")
        st.caption(f"Title: {len(title)}/60 · Description: {len(desc)}/155")
        if save_est:
            a["estrutura"] = {"title": title.strip(), "description": desc.strip(), "url": url.strip(),
                              "headings": _df_headings(hdf)}
            db.save_briefing({"analysis": a, "status": "revisado"}, b.id)
            st.success("Estrutura salva.")
            st.rerun()
        st.subheader("Checagens")
        show_checks(validate.check_briefing(b.focus_keyword, a))

    # ---------- 4. exportar
    with tabs[3]:
        html = render.briefing_html(cd, b.focus_keyword, raw, a)
        if b.gdoc_url:
            st.markdown(f"Último documento criado: [abrir]({b.gdoc_url})")
        export_buttons(slug_title(b.focus_keyword, "Análise para produção de conteúdo", client.name), html, f"b{b.id}",
                       on_success=lambda u: db.save_briefing({"gdoc_url": u}, b.id))
        with st.expander("Pré-visualizar documento"):
            st.html(html)

    # ---------- 5. texto
    with tabs[4]:
        page_content(b, cd, a)


def page_content(b, cd, a):
    if not a.get("estrutura"):
        st.info("Finalize a estrutura antes de gerar o texto.")
        return
    key = f"body_{b.id}"
    contents = db.list_contents(b.id)
    if key not in st.session_state:
        st.session_state[key] = contents[0].body_markdown if contents else ""

    c1, c2 = st.columns([1, 2])
    size = c1.selectbox("Tamanho alvo", ["800 a 1200", "1200 a 1800", "1800 a 2500", "2500 a 3500"], index=1)
    extra = c2.text_input("Instruções adicionais (opcional)", placeholder="ex.: citar a linha X, evitar falar de preço")
    tags = st.toggle("Mostrar as tags (<h2>…</h2>) nos títulos do documento", value=True)
    if st.button("Gerar texto" if not st.session_state[key] else "Gerar texto de novo", type="primary"):
        with st.spinner("Escrevendo o texto..."):
            try:
                st.session_state[key] = cp.generate(cd, b.focus_keyword, a, extra, size)
                reason = llm.LAST_FINISH.get("reason", "")
                st.session_state[f"finish_{b.id}"] = llm.FINISH_LABELS.get(reason, "")
                db.save_content({"briefing_id": b.id, "user_id": auth.current_user()["id"],
                                 "body_markdown": st.session_state[key]})
                db.save_briefing({"status": "texto_gerado"}, b.id)
                st.rerun()
            except Exception as ex:
                st.error(str(ex))

    body = st.session_state[key]
    if not body:
        return
    if st.session_state.get(f"finish_{b.id}"):
        st.warning(f"O texto pode estar incompleto: {st.session_state[f'finish_{b.id}']}. "
                   "Confira as checagens ao lado e, se faltar alguma seção, use \"Reescrever uma seção\" "
                   "ou gere de novo.")
    left, right = st.columns([3, 2])
    with left:
        edited = st.text_area("Texto (markdown, editável)", body, height=600)
        if edited != body and st.button("Salvar edição"):
            st.session_state[key] = edited
            db.save_content({"briefing_id": b.id, "user_id": auth.current_user()["id"], "body_markdown": edited})
            st.rerun()
    with right:
        st.markdown("**Checagens do texto**")
        show_checks(validate.check_content(b.focus_keyword, a, body))
        heads = re.findall(r"^#{1,4} (.+)$", body, re.M)
        with st.expander("Reescrever uma seção"):
            sec = st.selectbox("Seção", heads)
            instr = st.text_input("O que mudar", placeholder="ex.: mais curto, incluir uma tabela comparativa")
            if st.button("Reescrever seção") and instr:
                with st.spinner("Reescrevendo..."):
                    st.session_state[key] = cp.rewrite_section(cd, b.focus_keyword, a, body, sec, instr)
                    db.save_content({"briefing_id": b.id, "user_id": auth.current_user()["id"],
                                     "body_markdown": st.session_state[key]})
                    st.rerun()
    st.divider()
    html = render.content_html(b.focus_keyword, a, body, show_tags=tags)
    export_buttons(slug_title(b.focus_keyword, "Conteúdo | Produção de Conteúdo de Blog", cd["name"]), html, f"c{b.id}")
    with st.expander("Pré-visualizar documento"):
        st.html(html)


def page_history():
    st.title("Análises")
    clients = {c.id: c.name for c in db.list_clients()}
    flt = st.selectbox("Cliente", [None] + list(clients), format_func=lambda x: "Todos" if x is None else clients[x])
    rows = db.list_briefings(flt)
    if not rows:
        st.info("Nenhuma análise ainda.")
        return
    labels = {"rascunho": "🟡 Rascunho", "revisado": "🔵 Revisado", "texto_gerado": "🟢 Texto gerado"}
    for b in rows:
        c1, c2, c3, c4 = st.columns([3, 2, 1.4, 1])
        c1.markdown(f"**{b.focus_keyword}**  \n<span class='pa-muted'>{b.topic or ''}</span>", unsafe_allow_html=True)
        c2.write(clients.get(b.client_id, "-"))
        c3.write(f"{labels.get(b.status, b.status)}  \n{b.created_at:%d/%m/%Y}")
        if c4.button("Abrir", key=f"open_{b.id}"):
            go("briefing", briefing_id=b.id)


def page_clients():
    st.title("Clientes")
    clients = db.list_clients()
    opts = [None] + clients
    sel = st.selectbox("Editar cliente", opts, format_func=lambda c: "+ Novo cliente" if c is None else c.name)
    c = client_dict(sel) if sel else {}
    with st.form("cliente"):
        c1, c2, c3 = st.columns([2, 2, 1])
        name = c1.text_input("Nome", c.get("name", ""))
        domain = c2.text_input("Domínio", c.get("domain", ""), placeholder="madesa.com")
        country = c3.text_input("País (código)", c.get("country", "br"))
        c4, c5 = st.columns(2)
        sitemap_url = c4.text_input("URL do sitemap (opcional)", c.get("sitemap_url", ""),
                                    help="Se vazio, o app procura no robots.txt e em /sitemap.xml")
        blog_path = c5.text_input("Caminho do blog (opcional)", c.get("blog_path", ""), placeholder="/blog")
        brand = st.text_area("Contexto da marca", c.get("brand_context", ""), height=100,
                             placeholder="O que vende, público, diferenciais, linhas de produto")
        tone = st.text_area("Tom de voz e regras de escrita", c.get("tone_of_voice", ""), height=100)
        comp = st.text_area("Concorrentes diretos (um por linha)", c.get("competitors", ""), height=80)
        prio = st.text_area("Links prioritários (um por linha)", c.get("priority_links", ""), height=80,
                            help="Categorias ou páginas que sempre devem ser consideradas nos links internos")
        forb = st.text_area("Termos proibidos (um por linha)", c.get("forbidden_terms", ""), height=60)
        ok = st.form_submit_button("Salvar cliente", type="primary")
    if ok:
        if not name or not domain:
            st.error("Nome e domínio são obrigatórios.")
            return
        domain = re.sub(r"^https?://(www\.)?", "", domain.strip()).strip("/")
        db.save_client({"name": name.strip(), "domain": domain, "country": country.strip().lower() or "br",
                        "sitemap_url": sitemap_url.strip(), "blog_path": blog_path.strip(), "brand_context": brand,
                        "tone_of_voice": tone, "competitors": comp, "priority_links": prio, "forbidden_terms": forb},
                       sel.id if sel else None)
        st.success("Cliente salvo.")
        st.rerun()


def page_users():
    st.title("Usuários")
    me = auth.current_user()
    with st.expander("Trocar minha senha"):
        with st.form("pw"):
            p1 = st.text_input("Nova senha", type="password")
            p2 = st.text_input("Repita a nova senha", type="password")
            if st.form_submit_button("Salvar"):
                if len(p1) < 8 or p1 != p2:
                    st.error("As senhas precisam ser iguais e ter pelo menos 8 caracteres.")
                else:
                    auth.change_password(me["id"], p1)
                    st.success("Senha alterada.")
    if not me["is_admin"]:
        return
    with st.form("novo_user"):
        st.markdown("**Novo usuário**")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        email = c1.text_input("Email")
        name = c2.text_input("Nome")
        pw = c3.text_input("Senha inicial", type="password")
        adm = c4.checkbox("Admin")
        if st.form_submit_button("Criar", type="primary"):
            try:
                auth.create_user(email, name, pw, adm)
                st.success("Usuário criado.")
            except Exception as ex:
                st.error(str(ex))
    for u in auth.list_users():
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.write(f"{u.name or ''} · {u.email}{' · admin' if u.is_admin else ''}")
        c2.write("ativo" if u.active else "desativado")
        if u.id != me["id"] and c3.button("Desativar" if u.active else "Reativar", key=f"u{u.id}"):
            auth.set_active(u.id, not u.active)
            st.rerun()


# ------------------------------------------------------------------ main

def main():
    if not auth.current_user():
        auth.login_screen()
        return
    me = auth.current_user()
    pages = {"nova": "➕ Nova análise", "historico": "🗂️ Análises", "clientes": "🏢 Clientes", "usuarios": "👤 Usuários"}
    page = st.session_state.get("page", "nova")
    with st.sidebar:
        st.markdown(f"## {config.APP_NAME}")
        st.caption(f"{me['name']}")
        for k, label in pages.items():
            if st.button(label, key=f"nav_{k}", width="stretch",
                         type="primary" if page == k or (page == "briefing" and k == "historico") else "secondary"):
                go(k)
        st.divider()
        st.caption(f"Keywords: {config.KEYWORD_PROVIDER} · IA: {config.LLM_PROVIDER}")
        if st.button("Sair", width="stretch"):
            auth.logout()

    {"nova": page_new, "historico": page_history, "clientes": page_clients,
     "usuarios": page_users, "briefing": page_briefing}.get(page, page_new)()


main()
