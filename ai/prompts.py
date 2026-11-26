"""Prompts da análise (briefing) e do texto. Escritos a partir do padrão dos documentos da agência:
"Análise para produção de conteúdo" e "Produção de Conteúdo de Blog"."""
from __future__ import annotations

import json

ANALYSIS_SYSTEM = """Você é um analista sênior de SEO de conteúdo de uma agência brasileira.
Sua tarefa é transformar dados reais coletados (palavras-chave com volume, SERP, PAA, Visão de IA,
headings e características das páginas concorrentes, sitemap do cliente) em uma análise estratégica
para orientar a produção de um conteúdo de blog.

Regras:
- Baseie TODA a análise nos dados fornecidos. Não invente concorrentes, volumes, datas ou headings.
- Quando um dado estiver ausente (ex.: página não lida), diga que não foi possível avaliar.
- Escreva em português do Brasil, em tom profissional e direto, como um documento interno de agência.
- Não use travessão (—). Use vírgula, dois-pontos ou ponto.
- A estrutura de headings sugerida deve ser específica para a palavra-chave foco e superar a SERP:
  cobrir a intenção principal, responder as PAA, aproveitar as secundárias e incluir FAQ quando fizer sentido.
- Os H2 devem, sempre que natural, ser perguntas ou frases com termos de busca reais.
- Title com até 60 caracteres, description entre 120 e 155 caracteres, URL curta em slug com a keyword foco.
- Os links internos só podem usar URLs da lista de candidatas do sitemap ou dos links prioritários do cliente.
- Devolva somente JSON válido no formato pedido."""

ANALYSIS_SCHEMA = {
    "secondary_keywords": ["10 palavras-chave secundárias escolhidas da lista de candidatas, mais relevantes para a pauta"],
    "semantic_terms": ["termos de maior volume que devem ser trabalhados semanticamente no texto"],
    "leitura_estrategica": "2 a 4 parágrafos: padrão da SERP, pontos fortes, pontos fracos e a oportunidade do cliente",
    "posicionamento": "uma frase entre aspas com o posicionamento recomendado para o conteúdo",
    "concorrentes": [{"concorrente": "nome do site", "caracteristica": "característica principal", "limitacao": "limitação percebida"}],
    "concorrente_destaque": "parágrafo sobre o(s) concorrente(s) mais relevante(s) em estrutura e por quê",
    "formatos": [{"nome": "nome do formato", "estrutura": ["etapas"], "caracteristicas": ["características"]}],
    "leitura_semantica": "uma frase sobre o quanto a SERP resolve bem a intenção",
    "abordagem_predominante": ["itens da abordagem que os concorrentes usam"],
    "abordagem_recomendada": "parágrafo com a abordagem recomendada para o cliente, com um exemplo concreto",
    "recursos_visuais": [{"recurso": "nome", "descricao": "como aplicar"}],
    "intencao": {
        "tipo": "ex.: informacional com viés inspiracional e comercial indireto",
        "descricao": "parágrafo explicando a intenção",
        "o_que_busca": ["o que a pessoa provavelmente busca"],
        "orientacao_tom": "como a conversão deve aparecer no texto",
    },
    "oportunidades": ["oportunidades de otimização, objetivas e acionáveis"],
    "link_building": {
        "resumo": "parágrafo com a estratégia de link building para a pauta",
        "ativos": [{"titulo": "ativo linkável", "descricao": "descrição"}],
    },
    "estrutura": {
        "title": "title tag",
        "description": "meta description",
        "url": "/slug-da-url/",
        "headings": [{"level": 1, "text": "H1"}, {"level": 2, "text": "H2"}, {"level": 3, "text": "H3"}],
    },
    "links_internos": [{"url": "URL do cliente", "ancora": "texto âncora sugerido", "onde": "em qual seção usar"}],
    "faq": ["perguntas para o bloco de dúvidas frequentes"],
}


def _kw_table(rows, limit=60):
    out = []
    for r in rows[:limit]:
        out.append({k: r.get(k) for k in ("keyword", "volume", "difficulty", "intents", "parent_topic", "source")})
    return out


def _competitor_digest(pages):
    digest = []
    for p in pages:
        digest.append({
            "posicao": p.get("position"),
            "dominio": p.get("domain"),
            "url": p.get("url"),
            "title_serp": p.get("serp_title"),
            "status_leitura": p.get("status"),
            "palavras": p.get("word_count"),
            "tabelas": p.get("tables"), "listas": p.get("lists"), "imagens": p.get("images"),
            "videos": p.get("videos"), "faq_schema": p.get("has_faq_schema"),
            "publicado": p.get("published"), "atualizado": p.get("modified"),
            "anos_no_title_h1": p.get("years_mentioned"),
            "headings": [f"H{h['level']} {h['text']}" for h in p.get("headings", []) if not h.get("boilerplate")][:45],
            "trecho": (p.get("excerpt") or "")[:900],
        })
    return digest


def analysis_prompt(client: dict, focus: str, topic: str, raw: dict, notes: str = "") -> str:
    kw = raw.get("keywords", {})
    serp = raw.get("serp", {})
    data = {
        "cliente": {
            "nome": client.get("name"), "dominio": client.get("domain"),
            "contexto_da_marca": client.get("brand_context"),
            "concorrentes_diretos": client.get("competitors"),
        },
        "palavra_chave_foco": focus,
        "metricas_keyword_foco": kw.get("focus"),
        "pauta_ou_titulo_de_trabalho": topic or "(não informada, defina a partir da keyword foco)",
        "secundarias_obrigatorias_do_analista": raw.get("manual_secondary", []),
        "candidatas_a_secundarias": _kw_table(kw.get("candidates", [])),
        "serp_top10": [{k: o.get(k) for k in ("position", "title", "description", "url", "date")}
                       for o in serp.get("organic", [])],
        "paa": serp.get("paa", []),
        "buscas_relacionadas": serp.get("related_searches", []),
        "visao_de_ia": raw.get("ai_overview") or serp.get("ai_overview") or "(não exibida ou não capturada)",
        "concorrentes_lidos": _competitor_digest(raw.get("competitors", [])),
        "links_internos_candidatos": raw.get("internal_candidates", []),
        "links_prioritarios_do_cliente": [l for l in (client.get("priority_links") or "").splitlines() if l.strip()],
        "observacoes_do_analista": notes,
    }
    return (
        "Dados coletados para a análise:\n"
        f"{json.dumps(data, ensure_ascii=False, indent=1)}\n\n"
        "Gere a análise no seguinte formato JSON (as descrições indicam o que vai em cada campo):\n"
        f"{json.dumps(ANALYSIS_SCHEMA, ensure_ascii=False, indent=1)}\n\n"
        "Se o analista informou secundárias obrigatórias, inclua todas em secondary_keywords."
    )


CONTENT_SYSTEM = """Você é redator(a) sênior de SEO de uma agência brasileira e escreve conteúdos de blog
que ranqueiam e convertem, a partir de um briefing aprovado por um analista.

Regras de escrita:
- Siga a estrutura de headings do briefing na ordem. Pode ajustar a redação de um heading para ficar mais natural,
  mas não remova seções nem crie seções fora do escopo.
- Use a palavra-chave foco no H1, nos primeiros 100 palavras da introdução e de forma natural ao longo do texto.
- Distribua as palavras-chave secundárias de forma natural, destacando em negrito a primeira ocorrência de cada uma.
- Use negrito também nas frases mais importantes de cada seção, sem exagero.
- Parágrafos curtos (2 a 4 frases), linguagem clara, segunda pessoa (você), sem enrolação.
- Use listas e tabelas quando o briefing indicar ou quando facilitarem a leitura.
- Insira os links internos sugeridos como links markdown, com âncora natural, na seção indicada.
- A conversão aparece de forma leve ao longo do texto e ganha força na seção final de CTA da marca.
- Não invente dados de produto, preços, prazos ou estatísticas. Medidas e referências técnicas só quando
  forem referências amplamente aceitas no mercado, e sempre como faixa aproximada.
- Não use travessão (—).
- Escreva em português do Brasil.

Formato de saída: somente markdown do corpo do texto, começando pelo H1 (#), com H2 (##), H3 (###) e H4 (####).
Não inclua title, description, URL ou lista de palavras-chave (eles já vão no cabeçalho do documento)."""


def content_prompt(client: dict, focus: str, analysis: dict, extra_instructions: str = "",
                   target_words: str = "1200 a 1800") -> str:
    est = analysis.get("estrutura", {})
    headings = "\n".join(f"{'  ' * (h['level'] - 1)}H{h['level']}: {h['text']}" for h in est.get("headings", []))
    links = "\n".join(f"- {l.get('url')} | âncora: {l.get('ancora')} | onde: {l.get('onde')}"
                      for l in analysis.get("links_internos", []))
    return f"""Cliente: {client.get('name')} ({client.get('domain')})
Contexto da marca: {client.get('brand_context') or '(não informado)'}
Tom de voz e regras do cliente: {client.get('tone_of_voice') or '(seguir o padrão geral)'}
Termos proibidos: {client.get('forbidden_terms') or '(nenhum)'}

Palavra-chave foco: {focus}
Palavras-chave secundárias: {', '.join(analysis.get('secondary_keywords', []))}
Termos semânticos para trabalhar: {', '.join(analysis.get('semantic_terms', []))}

Intenção de busca: {analysis.get('intencao', {}).get('tipo', '')}
{analysis.get('intencao', {}).get('descricao', '')}
Orientação de tom e conversão: {analysis.get('intencao', {}).get('orientacao_tom', '')}

Posicionamento do conteúdo: {analysis.get('posicionamento', '')}
Abordagem recomendada: {analysis.get('abordagem_recomendada', '')}

Recursos a incluir no texto:
{chr(10).join('- ' + r.get('recurso', '') + ': ' + r.get('descricao', '') for r in analysis.get('recursos_visuais', []))}

Oportunidades de otimização:
{chr(10).join('- ' + o for o in analysis.get('oportunidades', []))}

Estrutura de headings aprovada:
{headings}

Links internos:
{links or '(nenhum)'}

Tamanho alvo: {target_words} palavras.
{('Instruções adicionais do analista: ' + extra_instructions) if extra_instructions else ''}

Escreva o texto completo."""
