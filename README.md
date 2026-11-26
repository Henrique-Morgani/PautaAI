# PautaAI

Automatiza a "Análise para produção de conteúdo" que hoje o analista monta à mão e, depois da revisão,
gera o texto do blog a partir dela. Os dois saem como Google Docs no padrão da agência.

## Fluxo

1. **Nova análise**: cliente + palavra-chave foco (pauta, secundárias obrigatórias e observações são opcionais).
2. **Coleta automática**
   - Ahrefs: métricas da foco, termos correspondentes, perguntas e termos relacionados (candidatas a secundárias com volume e KD)
   - Serper: top 10, PAA, buscas relacionadas e Visão de IA (quando vier; se não vier, o analista cola o texto)
   - Robô: abre cada concorrente e lê headings (sem lixo de template como "Compartilhe" e "Posts recentes"),
     número de palavras, tabelas, listas, imagens, vídeos, FAQ schema e datas de publicação/atualização
   - Sitemap do cliente: URLs candidatas a link interno (categorias e posts têm prioridade)
3. **Análise da IA** com base só nos dados coletados: secundárias, leitura estratégica, posicionamento,
   tabela de concorrentes, formatos, abordagem, recursos visuais, intenção, oportunidades, link building,
   links internos, title, description, URL e estrutura de headings.
4. **Revisão do analista**: tudo editável, com checagens automáticas (tamanho do title/description,
   keyword no title/H1/URL, H1 único, hierarquia, secundárias nos headings). Dá para gerar a análise
   de novo sem gastar Ahrefs/Serper.
5. **Exportar briefing** para Google Docs.
6. **Gerar texto** a partir do briefing revisado, com checagens (keyword nas primeiras 100 palavras,
   secundárias usadas, links internos, travessões), edição, reescrita de uma seção e exportação para Google Docs.

## Publicação (tudo separado do DizemAI)

1. **GitHub**: crie um repositório novo (ex.: `PautaAI`) e suba esta pasta.
2. **Neon**: crie um projeto novo (região São Paulo) e copie a connection string. As tabelas são criadas sozinhas.
3. **Google Docs**
   - No Google Cloud, crie um projeto, ative a **Google Drive API** e crie uma **conta de serviço** (baixe a chave JSON).
   - Crie (ou use) um **Drive compartilhado**, adicione o email da conta de serviço como membro com papel
     **Editor de conteúdo** e crie uma pasta para os documentos. O ID da pasta é o trecho final da URL.
   - Precisa ser Drive compartilhado: contas de serviço não têm espaço próprio no Meu Drive.
   - Sem essa configuração o app funciona igual, mas oferece o download do documento em vez de criar o Doc.
4. **Streamlit Cloud**: New app, aponte para o repositório e `app.py`, e cole em Secrets o conteúdo de
   `.streamlit/secrets.toml.example` preenchido.
5. No primeiro acesso, entre com o email/senha do bloco `[admin]`. Os outros usuários são criados na tela **Usuários**.

## Trocar Ahrefs por Semrush

Toda a aplicação usa a interface `KeywordProvider` (`providers/keywords.py`). Para migrar, implemente
`SemrushProvider` (o mapeamento de endpoints já está documentado no arquivo) e troque
`KEYWORD_PROVIDER = "semrush"` nos secrets. Nada mais muda.

## Trocar a IA

`LLM_PROVIDER = "gemini"` (padrão) ou `"anthropic"`, com o modelo definido em `[gemini] model` ou `[anthropic] model`.

## Consumo por análise

- Serper: 1 crédito
- Ahrefs: 4 chamadas (overview, termos correspondentes, perguntas, relacionados), até 50 linhas cada.
  As units do Ahrefs variam com o número de linhas e campos; ajuste `limit` em `collect_keyword_universe` se precisar economizar.
- IA: 1 chamada para a análise e 1 para o texto (mais 1 por reescrita de seção)

## Rodar local e testes

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # preencha
streamlit run app.py
python -m pytest -q tests    # testes com APIs simuladas, não gastam créditos
```

Sem `DATABASE_URL`, o app usa um SQLite local (`pautaai_local.db`).

## Estrutura

```
app.py                  interface (Streamlit)
core/                   configuração, banco, login
providers/              keywords (Ahrefs/Semrush), SERP (Serper), crawler, sitemap
ai/                     camada de IA e prompts
pipeline/               coleta + análise, geração do texto, checagens
export/                 HTML no padrão dos documentos e criação do Google Doc
tests/                  testes ponta a ponta com dados simulados
```
