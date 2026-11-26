"""Monta o HTML dos dois documentos no padrão da agência. O mesmo HTML vira Google Doc
(conversão nativa do Drive) e serve de download quando o Drive não estiver configurado."""
from __future__ import annotations

import html
import re

import markdown as md

CSS = """
body{font-family:Arial,Helvetica,sans-serif;font-size:11pt;line-height:1.5;color:#111}
h1{font-size:20pt} h2{font-size:16pt} h3{font-size:13pt} h4{font-size:11.5pt}
table{border-collapse:collapse;width:100%} td,th{border:1px solid #999;padding:6px;vertical-align:top;font-size:10pt}
th{background:#f1f1f1;font-weight:bold} blockquote{margin-left:12pt;font-style:italic}
"""

e = lambda s: html.escape(str(s or ""))


def _ul(items) -> str:
    items = [i for i in (items or []) if str(i).strip()]
    return "<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>" if items else "<p><i>Sem dados.</i></p>"


def _table(headers, rows) -> str:
    th = "".join(f"<th>{e(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{th}</tr>{trs}</table>"


def headings_tree(headings, show_tags: bool = True) -> str:
    """Lista plana [{level, text}] -> lista aninhada no formato '<h2> Texto'."""
    out, depth = [], 0
    base = min((h["level"] for h in headings), default=1)
    for h in headings:
        lvl = h["level"] - base + 1
        while depth < lvl:
            out.append("<ul>"); depth += 1
        while depth > lvl:
            out.append("</ul>"); depth -= 1
        label = f"&lt;h{h['level']}&gt; {e(h['text'])}" if show_tags else e(h["text"])
        out.append(f"<li>{label}</li>")
    out.append("</ul>" * depth)
    return "".join(out) or "<p><i>Não foi possível ler os headings desta página.</i></p>"


def _k(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(s.split())


def _fmt_num(v):
    return f"{v:,}".replace(",", ".") if isinstance(v, (int, float)) else "-"


def briefing_html(client: dict, focus: str, raw: dict, a: dict) -> str:
    kw = raw.get("keywords", {})
    serp = raw.get("serp", {})
    cand = {_k(c["keyword"]): c for c in kw.get("candidates", [])}
    for c in (kw.get("focus") or []) + (kw.get("extra") or []):  # secundárias do analista e da IA
        cand.setdefault(_k(c.get("keyword", "")), c)
    fm = (kw.get("focus") or [{}])[0] if kw.get("focus") else {}
    p = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>",
         "<h1>Análise para produção de conteúdo</h1>", "<h2>Análise do cenário</h2>",
         "<h3>Palavra-chave foco</h3>", f"<p>{e(focus)}</p>"]
    if fm:
        p.append(f"<p><i>Volume: {_fmt_num(fm.get('volume'))} | KD: {_fmt_num(fm.get('difficulty'))} | "
                 f"Traffic potential: {_fmt_num(fm.get('traffic_potential'))} | Fonte: {e(kw.get('provider'))}</i></p>")

    p.append("<h3>Palavras-chave secundárias</h3>")
    rows = []
    for k in a.get("secondary_keywords", []):
        c = cand.get(_k(k), {})
        rows.append([e(k), _fmt_num(c.get("volume")), _fmt_num(c.get("difficulty"))])
    p.append(_table(["Palavra-chave", "Volume", "KD"], rows) if rows else _ul([]))
    if any(r[1] in ("-", "0") for r in rows):
        p.append("<p><i>Termos com volume 0 ou \"-\" não têm demanda medida pelo Ahrefs. "
                 "Avalie se vale manter como secundária ou usar só como subtema.</i></p>")
    if a.get("semantic_terms"):
        p.append("<p><b>Termos para trabalhar semanticamente:</b> " + e(", ".join(a["semantic_terms"])) + "</p>")

    p.append("<h2>Análise da SERP</h2><h3>Visão de IA da SERP</h3>")
    aio = raw.get("ai_overview") or ""
    p.append("".join(f"<p>{e(x)}</p>" for x in aio.split("\n") if x.strip()) or "<p><i>A SERP não exibiu Visão de IA no momento da coleta.</i></p>")
    p.append("<h3>PAA</h3>")
    if serp.get("paa"):
        if raw.get("paa_source") == "manual":
            p.append("<p><i>PAA informado manualmente pelo analista.</i></p>")
        p.append(_ul(serp.get("paa")))
    else:
        p.append("<p><i>A SERP não exibiu PAA no momento da coleta.</i></p>")
    questions = [c["keyword"] for c in kw.get("candidates", []) if c.get("source") == "perguntas"][:10]
    if questions:
        p.append("<h4>Perguntas com volume de busca (Ahrefs)</h4>")
        p.append(_table(["Pergunta", "Volume"], [[e(c["keyword"]), _fmt_num(c.get("volume"))]
                                                 for c in kw.get("candidates", []) if c.get("source") == "perguntas"][:10]))
    if serp.get("related_searches"):
        p.append("<h3>Buscas relacionadas</h3>" + _ul(serp.get("related_searches")))

    p.append("<h3>10 primeiros resultados da SERP</h3>")
    p.append(_table(["Posição", "Title", "Description", "URL"],
                    [[e(o["position"]), e(o["title"]), e(o["description"]), f"<a href='{e(o['url'])}'>{e(o['url'])}</a>"]
                     for o in serp.get("organic", [])]))

    p.append("<h3>Heading tags</h3>")
    for c in raw.get("competitors", []):
        p.append(f"<h4>[{e(c.get('position'))}] {e(c.get('domain'))}</h4>")
        facts = []
        if c.get("word_count"):
            facts.append(f"{_fmt_num(c['word_count'])} palavras")
        for key, label in (("tables", "tabela(s)"), ("lists", "lista(s)"), ("images", "imagem(ns)"), ("videos", "vídeo(s)")):
            if c.get(key):
                facts.append(f"{c[key]} {label}")
        if c.get("has_faq_schema"):
            facts.append("FAQ schema")
        if c.get("via"):
            facts.append("lido via leitor externo")
        if c.get("published") or c.get("modified"):
            facts.append(f"publicado {c.get('published') or '-'} / atualizado {c.get('modified') or '-'}")
        if facts:
            p.append(f"<p><i>{e(' | '.join(facts))}</i></p>")
        if c.get("status") != "ok":
            p.append(f"<p><i>{e(c.get('error') or 'Página não lida.')}</i></p>")
        else:
            p.append(headings_tree([h for h in c.get("headings", []) if not h.get("boilerplate")]))

    al = a.get("alerta_serp") or {}
    if al.get("alerta"):
        p.append("<h3>Alerta de intenção da SERP</h3>")
        p.append(f"<p><b>Tipo de página dominante:</b> {e(al.get('tipo_de_pagina_dominante'))}</p>")
        p.append(f"<p>{e(al.get('alerta'))}</p>")
        if al.get("keyword_alternativa"):
            p.append(f"<p><b>Alternativa sugerida:</b> {e(al.get('keyword_alternativa'))}</p>")
    p.append("<h3>Leitura estratégica do cenário</h3>")
    p += [f"<p>{e(x)}</p>" for x in str(a.get("leitura_estrategica", "")).split("\n") if x.strip()]
    if a.get("posicionamento"):
        p.append(f"<blockquote>{e(a['posicionamento'])}</blockquote>")

    p.append("<h3>Características dos principais conteúdos</h3><h4>Formato e estrutura</h4>")
    p.append(_table(["Concorrente", "Característica principal", "Limitação percebida"],
                    [[e(c.get("concorrente")), e(c.get("caracteristica")), e(c.get("limitacao"))]
                     for c in a.get("concorrentes", [])]))
    if a.get("concorrente_destaque"):
        p.append(f"<p>{e(a['concorrente_destaque'])}</p>")
    if a.get("formatos"):
        n = len(a["formatos"])
        label = "1 formato principal" if n == 1 else f"{n} formatos principais"
        p.append(f"<p>Os conteúdos que aparecem na SERP seguem basicamente <b>{label}</b>:</p><ul>")
        for f in a["formatos"]:
            p.append(f"<li>{e(f.get('nome'))}<ul><li>Estrutura:{_ul(f.get('estrutura'))}</li>"
                     f"<li>Características:{_ul(f.get('caracteristicas'))}</li></ul></li>")
        p.append("</ul>")
    if a.get("leitura_semantica"):
        p.append(f"<p>{e(a['leitura_semantica'])}</p>")

    p.append("<h4>Abordagem</h4><p>A abordagem predominante é:</p>" + _ul(a.get("abordagem_predominante")))
    if a.get("abordagem_recomendada"):
        p.append(f"<p>{e(a['abordagem_recomendada'])}</p>")
    p.append("<h4>Diferenciação, elementos visuais e recursos</h4><ul>")
    p += [f"<li><b>{e(r.get('recurso'))}</b>: {e(r.get('descricao'))}</li>" for r in a.get("recursos_visuais", [])]
    p.append("</ul>")

    it = a.get("intencao", {})
    p.append("<h3>Intenção de busca do usuário</h3>")
    p.append(f"<p>A intenção é predominantemente <b>{e(it.get('tipo'))}</b>.</p><p>{e(it.get('descricao'))}</p>")
    if it.get("o_que_busca"):
        p.append("<p>A pessoa provavelmente busca:</p>" + _ul(it.get("o_que_busca")))
    if it.get("orientacao_tom"):
        p.append(f"<p>{e(it['orientacao_tom'])}</p>")

    p.append("<h3>Principais oportunidades de otimização</h3>" + _ul(a.get("oportunidades")))

    lb = a.get("link_building", {})
    p.append("<h3>Estratégia de Link Building</h3>" + f"<p>{e(lb.get('resumo'))}</p><h4>Ativos linkáveis</h4><ol>")
    p += [f"<li><b>{e(x.get('titulo'))}</b><ul><li>{e(x.get('descricao'))}</li></ul></li>" for x in lb.get("ativos", [])]
    p.append("</ol>")

    if a.get("links_internos"):
        p.append("<h3>Links internos sugeridos</h3>")
        p.append(_table(["URL", "Âncora", "Onde usar"],
                        [[f"<a href='{e(l.get('url'))}'>{e(l.get('url'))}</a>", e(l.get("ancora")), e(l.get("onde"))]
                         for l in a["links_internos"]]))

    est = a.get("estrutura", {})
    p.append("<h1>Estrutura para otimização</h1>")
    p.append(f"<p><b>Title</b></p>{_ul([est.get('title')])}<p><b>Description</b></p>{_ul([est.get('description')])}"
             f"<p><b>URL</b></p>{_ul([est.get('url')])}<p><b>Heading tags</b></p>")
    p.append(headings_tree(est.get("headings", [])))
    p.append("</body></html>")
    return "".join(p)


def _tag_headings(body_html: str) -> str:
    """<h2>Texto</h2> -> <h2>&lt;h2&gt;Texto&lt;/h2&gt;</h2>, como no padrão de entrega."""
    return re.sub(r"<h([1-6])>(.*?)</h\1>",
                  lambda m: f"<h{m.group(1)}>&lt;h{m.group(1)}&gt;{m.group(2)}&lt;/h{m.group(1)}&gt;</h{m.group(1)}>",
                  body_html, flags=re.S)


def content_html(focus: str, analysis: dict, body_md: str, show_tags: bool = True) -> str:
    est = analysis.get("estrutura", {})
    line = "<p>" + "_" * 75 + "</p>"
    body = md.markdown(body_md, extensions=["tables", "sane_lists"])
    if show_tags:
        body = _tag_headings(body)
    return (f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{line}"
            f"<p><b>Palavra-chave foco:</b> {e(focus)}</p>"
            f"<p><b>Palavras-chave secundárias:</b> {e(', '.join(analysis.get('secondary_keywords', [])))}</p>"
            f"<p><b>Title:</b> {e(est.get('title'))}</p>"
            f"<p><b>Description:</b> {e(est.get('description'))}</p>"
            f"<p><b>URL:</b> {e(est.get('url'))}</p>{line}{body}</body></html>")
