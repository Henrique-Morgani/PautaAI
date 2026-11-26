"""Prompts da análise (briefing) e do texto. Escritos a partir do padrão dos documentos da agência:
"Análise para produção de conteúdo" e "Produção de Conteúdo de Blog"."""
from __future__ import annotations

import json

ANALYSIS_SYSTEM = """Você é um analista sênior de SEO de conteúdo de uma agência brasileira.
Sua tarefa é transformar dados reais coletados (palavras-chave com volume, SERP, PAA, Visão de IA,
headings e características das páginas concorrentes, sitemap do cliente) em uma análise estratégica
que um redator consiga executar sem precisar perguntar nada.

Regras gerais:
- Baseie TODA a análise nos dados fornecidos. Não invente concorrentes, volumes, datas ou headings.
- Quando um dado estiver ausente (ex.: página não lida), diga que não foi possível avaliar.
- Português do Brasil, tom profissional e direto, como documento interno de agência. Não use travessão (—).
- Siga SEMPRE o contexto e as regras do cliente (tom de voz, padrão de title, marcas que não podem ser
  citadas, termos proibidos). Elas valem para title, description, headings, links internos e recomendações.

Palavras-chave secundárias:
- Escolha 8 a 12 termos que abram SUBTEMAS diferentes da pauta (ex.: tipos, medidas, para quem, quando trocar,
  como escolher, comparações, perguntas). Use as candidatas com volume como base.
- Não repita variações da mesma busca: plural/singular, com ou sem acento, "de"/"para", masculino/feminino
  só entram juntos se cada um virar uma seção própria. Entre variações, fique com a de maior volume.
- Inclua todas as secundárias obrigatórias do analista.

Intenção e SERP:
- Classifique o tipo de página que domina o top 10 (artigo de blog, página de categoria, página de produto,
  marketplace, vídeo, institucional) usando o campo tipo_pagina_estimado e os headings.
- Se a SERP for dominada por páginas que não são artigos (ex.: categorias de e-commerce), registre um alerta
  em alerta_serp: explique o risco de um post de blog não ranquear e sugira o caminho (variação informacional
  da keyword com volume, ou usar o conteúdo como texto de apoio da categoria).
- Se uma variação da keyword foco tiver volume muito maior, aponte isso no alerta.

Canibalização:
- Se houver itens em conteudos_do_cliente_sobre_o_mesmo_tema (ou posts nos links candidatos cujo assunto seja
  o mesmo da pauta), preencha alerta_canibalizacao: diga qual URL já cobre o tema e recomende o caminho
  (atualizar e ampliar o post existente, ou diferenciar a pauta com outro ângulo e outra keyword).
- Nunca use como link interno um post do cliente que trate do MESMO tema da pauta.

Termos semânticos: 10 a 20 termos específicos tirados das candidatas com volume e dos headings dos concorrentes
(ex.: "pisada pronada", "drop", "entressola"). Não use palavras soltas genéricas como "tênis" ou "corrida".

Oportunidades de otimização:
- Cada item deve ser uma instrução executável e específica, com o termo, o local e o exemplo
  (ex.: "Usar 'X' no H1 e nos primeiros 100 caracteres da introdução", "Responder a PAA 'Y' em um bloco de 40 a 60
  palavras logo abaixo do H2 Z", "Alt text: 'tênis de corrida para iniciantes na esteira'").
- Inclua: uso da keyword foco (H1, introdução, H2), termos semânticos com volume, resposta às PAA,
  links internos para categorias, alt text com exemplos, FAQ, atualização de ano quando fizer sentido.

Recursos visuais: específicos da pauta, com nome e conteúdo (ex.: "Tabela: tipo de pisada x tipo de tênis
indicado"). Não sugira recursos genéricos como "vídeos explicativos" ou "infográficos" sem dizer o conteúdo.

Link building (estratégia EXTERNA, para conquistar links de outros sites):
- Os ativos linkáveis são materiais que portais, jornalistas e blogs teriam motivo para citar e linkar:
  checklists, guias, tabelas de referência, mini estudos com dados de busca, calculadoras, pautas para imprensa.
- Para cada ativo, diga que tipo de site linkaria e por quê.
- NUNCA use links internos, páginas de produto ou categorias do cliente como ativos linkáveis.

Links internos (separados do link building):
- Use só URLs da lista de candidatas do sitemap ou dos links prioritários do cliente.
- Priorize categorias e posts do blog. Páginas de produto só se não houver categoria equivalente
  (produto sai de linha e o link quebra).
- Respeite as marcas que o cliente não permite citar.

Estrutura:
- Específica para a keyword foco, superando a SERP: cobre a intenção, responde às PAA, aproveita as secundárias.
- H2 preferencialmente em forma de pergunta ou com termos de busca reais.
- Title com NO MÁXIMO 60 caracteres contando o sufixo da marca (ex.: "| Blog Decathlon"). Primeira letra maiúscula,
  o resto em minúsculas, exceto nomes próprios. Description entre 120 e 155 caracteres. Conte os caracteres.
- Title, description, headings, termos semânticos e textos sempre em português correto, COM acentos
  ("tênis", "você", "distância"), mesmo que a palavra-chave da ferramenta venha sem acento.
- Não crie heading para "Índice" ou "Sumário": o índice é texto, não heading.
- URL curta em slug com a keyword foco.
- Termine com o H2 de dúvidas frequentes e as perguntas do FAQ como H3 logo abaixo dele.
- As perguntas do FAQ não podem repetir assuntos que já têm H2 ou H3 próprio no texto: use o FAQ para
  dúvidas complementares (PAA e perguntas do Ahrefs que não viraram seção).
- Palavras-chave e termos semânticos em letras minúsculas, como as pessoas buscam.

A seção "formatos" descreve como os CONCORRENTES estruturam suas páginas, não as regras de escrita do cliente.

Devolva somente JSON válido no formato pedido."""

ANALYSIS_SCHEMA = {
    "secondary_keywords": ["10 palavras-chave secundárias escolhidas da lista de candidatas, mais relevantes para a pauta"],
    "semantic_terms": ["termos de maior volume que devem ser trabalhados semanticamente no texto"],
    "alerta_serp": {
        "tipo_de_pagina_dominante": "ex.: páginas de categoria de e-commerce",
        "compativel_com_post_de_blog": True,
        "alerta": "vazio se não houver risco; senão, explique o risco e o caminho recomendado",
        "keyword_alternativa": "variação informacional sugerida com volume, ou vazio",
    },
    "alerta_canibalizacao": {"url_existente": "URL do cliente que já cobre o tema, ou vazio",
                             "recomendacao": "o que fazer: atualizar o post existente ou diferenciar a pauta"},
    "leitura_estrategica": "2 a 4 parágrafos: padrão da SERP, pontos fortes, pontos fracos e a oportunidade do cliente",
    "posicionamento": "uma frase entre aspas com o posicionamento recomendado para o conteúdo",
    "concorrentes": [{"concorrente": "nome do site", "caracteristica": "característica principal", "limitacao": "limitação percebida"}],
    "concorrente_destaque": "parágrafo sobre o(s) concorrente(s) mais relevante(s) em estrutura e por quê",
    "formatos": [{"nome": "formato de página usado pelos CONCORRENTES da SERP (ex.: página de categoria com guia de compra embutido; artigo checklist)", "estrutura": ["como esses concorrentes organizam a página"], "caracteristicas": ["características e limitações observadas nos concorrentes"]}],
    "leitura_semantica": "uma frase sobre o quanto a SERP resolve bem a intenção",
    "abordagem_predominante": ["itens da abordagem que os concorrentes usam"],
    "abordagem_recomendada": "parágrafo com a abordagem recomendada para o cliente, com um exemplo concreto",
    "recursos_visuais": [{"recurso": "nome específico do recurso", "descricao": "o conteúdo exato e onde entra no texto"}],
    "intencao": {
        "tipo": "ex.: informacional com viés inspiracional e comercial indireto",
        "descricao": "parágrafo explicando a intenção",
        "o_que_busca": ["o que a pessoa provavelmente busca"],
        "orientacao_tom": "como a conversão deve aparecer no texto",
    },
    "oportunidades": ["instruções executáveis: o que fazer, com qual termo, em qual lugar, com exemplo"],
    "link_building": {
        "resumo": "parágrafo com a estratégia EXTERNA de link building para a pauta (que tipo de sites e por quê)",
        "ativos": [{"titulo": "ativo linkável (material citável por outros sites)", "descricao": "o que é, que tipo de site linkaria e por quê"}],
    },
    "estrutura": {
        "title": "title tag",
        "description": "meta description",
        "url": "/slug-da-url/",
        "headings": [{"level": 1, "text": "H1"}, {"level": 2, "text": "H2"}, {"level": 3, "text": "H3"}],
    },
    "links_internos": [{"url": "URL do cliente", "ancora": "texto âncora sugerido", "onde": "em qual seção usar"}],
    "faq": ["5 a 7 perguntas para o bloco de dúvidas frequentes, baseadas nas PAA e nas perguntas do Ahrefs"],
}


def _kw_table(rows, limit=60):
    out = []
    for r in rows[:limit]:
        out.append({k: r.get(k) for k in ("keyword", "volume", "difficulty", "intents", "parent_topic", "source")})
    return out


def page_type(url: str, title: str = "") -> str:
    import re
    from urllib.parse import urlparse
    u = urlparse(url or "")
    path, host = u.path.lower(), u.netloc.lower()
    if any(x in host for x in ("youtube.", "tiktok.", "instagram.", "facebook.", "pinterest.")):
        return "rede social / vídeo"
    if any(x in host for x in ("mercadolivre", "amazon.", "shopee", "magazineluiza", "americanas", "aliexpress")):
        return "marketplace"
    if re.search(r"/(blog|blogs|artigos?|dicas|central-de-dicas|noticias?|revista|guia|post)/", path) or host.startswith("blog."):
        return "artigo"
    if re.search(r"(/p$|/p/|/produto/|/product/|-\d{6,}/?$)", path):
        return "produto"
    if path in ("", "/"):
        return "home"
    return "categoria ou listagem"


def _competitor_digest(pages):
    digest = []
    for p in pages:
        digest.append({
            "posicao": p.get("position"),
            "tipo_pagina_estimado": page_type(p.get("url", "")),
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
            "tom_de_voz_e_regras": client.get("tone_of_voice"),
            "termos_proibidos": client.get("forbidden_terms"),
            "concorrentes_diretos": client.get("competitors"),
        },
        "palavra_chave_foco": focus,
        "metricas_keyword_foco": kw.get("focus"),
        "pauta_ou_titulo_de_trabalho": topic or "(não informada, defina a partir da keyword foco)",
        "secundarias_obrigatorias_do_analista": raw.get("manual_secondary", []),
        "candidatas_a_secundarias": _kw_table(kw.get("candidates", [])),
        "serp_top10": [{k: o.get(k) for k in ("position", "title", "description", "url", "date")}
                       for o in serp.get("organic", [])],
        "paa": serp.get("paa", []) or raw.get("paa_manual", []),
        "perguntas_ahrefs": [c.get("keyword") for c in kw.get("candidates", []) if c.get("source") == "perguntas"][:15],
        "buscas_relacionadas": serp.get("related_searches", []),
        "visao_de_ia": raw.get("ai_overview") or serp.get("ai_overview") or "(não exibida ou não capturada)",
        "concorrentes_lidos": _competitor_digest(raw.get("competitors", [])),
        "links_internos_candidatos": raw.get("internal_candidates", []),
        "conteudos_do_cliente_sobre_o_mesmo_tema": raw.get("existing_content", []),
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
