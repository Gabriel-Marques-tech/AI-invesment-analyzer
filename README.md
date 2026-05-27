# BTG Monitor — Ofertas Primárias Imobiliárias

Sistema multi-agente que monitora ofertas primárias do mercado imobiliário brasileiro
(CRI, CRA, FII) a partir de dados públicos da CVM, organiza tudo num grafo Neo4j e
gera insights competitivos para o BTG Pactual.

> Parceiro: **Banco BTG Pactual**
> Stack: **Python · LangGraph · LangChain · Neo4j Aura · Groq · Streamlit · pandas · plotly**
> Padrão de agente: **Supervisor multi-agente**

---

## Sumário

1. [Visão geral](#visão-geral)
2. [Arquitetura](#arquitetura)
3. [Estrutura de pastas](#estrutura-de-pastas)
4. [Stack técnica](#stack-técnica)
5. [Setup](#setup)
6. [Como rodar](#como-rodar)
7. [Pipeline de coleta](#pipeline-de-coleta)
8. [Aba a aba do dashboard](#aba-a-aba-do-dashboard)
9. [Fontes de dados](#fontes-de-dados)
10. [Schema do Neo4j](#schema-do-neo4j)
11. [Limitações conhecidas](#limitações-conhecidas)
12. [Decisões de design](#decisões-de-design)
13. [Troubleshooting](#troubleshooting)

---

## Visão geral

O BTG Pactual atua como distribuidor e coordenador de investimentos imobiliários
estruturados (CRI, CRA, FIIs). O time não tinha visibilidade em tempo real do que
os concorrentes (XP, Itaú BBA, Bradesco BBI, Santander) estavam ofertando — quais
ativos, a que volume, para qual público.

Este projeto resolve isso com três pilares:

1. **Coleta automática** de ofertas e dados financeiros de fundos diretamente da
   CVM (sem scraping HTML, sem Selenium) — fontes oficiais atualizadas diariamente.
2. **Grafo Neo4j** que organiza ofertas, emissores, distribuidores e fundos com
   relacionamentos explícitos — permite análises competitivas em segundos.
3. **Agentes IA** que respondem perguntas analíticas, comparam BTG com mercado
   e geram alertas baseados em regras de negócio.

O **diferencial**: o sistema organiza os dados pela perspectiva do *distribuidor*
(quem está ofertando o quê, com quem, a que volume), não do produto isolado.

---

## Arquitetura

### Fluxo de dados

```
   CVM Dados Abertos                             Neo4j Aura
   (oferta-distrib +                            (grafo do mercado)
    inf_mensal_fii)                                    ▲
          │                                            │
          ▼                                            │
   ┌──────────────────┐    ┌─────────────────────┐    │
   │  Collectors      │───▶│  graph/queries.py   │────┘
   │  cvm_collector   │    │  (upsert + Cypher)  │
   │  fii_collector   │    └─────────────────────┘
   │  prospecto_      │                                 ▲
   │  parser          │                                 │
   └──────────────────┘                                 │
          ▲                                             │
          │ POST /documentosPublicados                  │
          │ + download/{uuid}                           │
          ▼                                             │
   Portal SRE (PDF dos                                  │
   prospectos)                                          │
                                                        │
   ┌──────────────────────────────────────────┐         │
   │  Agentes (LangGraph)                     │─────────┘
   │  ┌─────────────┐                         │
   │  │ Supervisor  │ ── decide → Coletor /   │
   │  └─────────────┘            Analista /   │
   │                             Recomendador │
   └──────────────────────────────────────────┘
          ▲                                    
          │                                    
   ┌──────────────────────────────────────────┐
   │  Streamlit (app.py)                      │
   │  - 4 abas: Mercado / BTG vs / Alertas /  │
   │    Chat com agente                       │
   │  - Scheduler em background (APScheduler) │
   └──────────────────────────────────────────┘
```

### Padrão supervisor multi-agente

O usuário faz uma pergunta → o **Supervisor** lê e decide qual agente acionar:

| Agente | Responsabilidade | Ferramentas principais |
|---|---|---|
| **Coletor** | Atualiza o grafo com dados novos da CVM | `sincronizar_ofertas_cvm`, `sincronizar_fundos_fii_cvm`, `enriquecer_fees_ofertas_fii` |
| **Analista** | Responde perguntas analíticas (somente leitura) | `panorama_mercado`, `gap_btg_vs_mercado`, `ranking_distribuidores_tool`, `fii_destaque_por_metrica`, `query_cypher` |
| **Recomendador** | Gera insights estratégicos e alertas | `gerar_alerta`, `detectar_gaps_competitivos`, `recomendar_posicionamento_taxa` |

Após cada agente responder, o controle volta ao Supervisor — ele decide se aciona
outro agente ou termina (`FINISH`). Limitado a 4 iterações por pergunta.

### Anti-alucinação

Como agentes LLM tendem a inventar dados quando a fonte falha, há 3 camadas
de proteção:

1. **Validação `_parece_fake`** em `tools/cvm_tools.py` — rejeita IDs como
   `123456`, `id_requerimento_retornado`, nomes como `Emissor 1`.
2. **Prompt restritivo** do coletor — "NUNCA invente dados; se a fonte retornar
   vazio, responda 'sem dados novos' e PARE".
3. **Heurística de tipo** — IDs aceitos só se forem numéricos puros ou com `/`/`-`
   (formato CVM/SRE/...).

---

## Estrutura de pastas

```
BTG/
├── app.py                  Entry point Streamlit (adiciona src/ ao path)
├── run.py                  Helper para rodar módulos do src/ standalone
├── pyproject.toml          Configuração do src layout
├── requirements.txt
├── .env.example            Template de variáveis (copie para .env)
├── .streamlit/
│   └── config.toml         Tema BTG (azul marinho)
├── docs/                   PDFs de referência (CLAUDE.md, briefing, glossário)
├── claude.md               Briefing original do projeto
└── src/
    ├── agents/
    │   ├── supervisor.py           Orquestrador LangGraph
    │   ├── common.py               LLM compartilhado + loop ReAct + retry
    │   ├── collector_agent.py      Coletor: dispara sincronização
    │   ├── analyst_agent.py        Analista: queries Cypher + tools
    │   └── recommender_agent.py    Recomendador: gera alertas
    │
    ├── collectors/
    │   ├── cvm_collector.py        Ofertas (oferta-distrib.zip)
    │   ├── fii_collector.py        Informe mensal de FII (DY, PL, cotistas)
    │   ├── prospecto_parser.py     Extrai fees de prospectos PDF
    │   └── anbima_collector.py     Stub (ANBIMA exige cadastro, desativado v1)
    │
    ├── graph/
    │   ├── neo4j_client.py         Singleton de conexão Neo4j Aura
    │   ├── schema.py               Constraints e índices
    │   ├── queries.py              26 queries: upserts + analíticas + alertas
    │   ├── limpar_dados.py         Script: zera nós (--apenas-fake ou total)
    │   └── diagnosticar_banco.py   Script: relatório de cobertura do grafo
    │
    ├── tools/
    │   ├── cvm_tools.py            9 tools de coleta para LangChain
    │   ├── neo4j_tools.py          10 tools de leitura (analíticas)
    │   └── market_tools.py         4 tools de mercado (alertas, posicionamento)
    │
    └── scheduler/
        └── monitor.py              APScheduler em background
```

---

## Stack técnica

```
langchain==0.3.25
langchain-community==0.3.23
langchain-groq==0.2.4
langgraph==0.2.28
neo4j==5.28.1
streamlit==1.45.1
apscheduler==3.10.4
requests==2.32.3
python-dotenv==1.0.1
pandas>=2.3,<4        (Python 3.14 não tem wheel 2.x)
plotly==5.24.1
pypdf                  (extração de texto dos prospectos)
zstandard>=0.25       (dep transitiva — forçada para wheel 3.14)
```

**LLM**: Groq `llama-3.3-70b-versatile` (gratuito, suporta tool calling).
**Banco**: Neo4j Aura free tier (1 instância).
**Monitoramento**: APScheduler rodando em background dentro do Streamlit.

---

## Setup

### 1. Pré-requisitos

- **Python 3.11+** (testado em 3.14.4)
- **Conta Neo4j Aura free** — `aura.neo4j.io`
- **API key Groq** — `console.groq.com/keys`

### 2. Clonar e criar ambiente

```bash
cd btg-monitor
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 3. Configurar credenciais

```bash
cp .env.example .env
# editar .env com suas chaves:
#   GROQ_API_KEY=...
#   NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
#   NEO4J_USER=neo4j
#   NEO4J_PASSWORD=...
#   COLETA_INTERVALO_MINUTOS=30   (opcional, default 30)
#   GROQ_MODEL=llama-3.3-70b-versatile   (opcional)
#   GROQ_TEMPERATURE=0.1                  (opcional)
```

### 4. Inicializar schema do Neo4j

Cria constraints (6) e índices (7) — só precisa rodar uma vez:

```bash
.venv/bin/python run.py graph.schema
```

### 5. Coletar dados iniciais

Roda na ordem:

```bash
# Onda 1: ofertas em andamento (~375)
.venv/bin/python run.py collectors.cvm_collector

# Onda 2: dados financeiros dos FIIs (~1.347)
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
import logging; logging.basicConfig(level=logging.INFO)
from collectors.fii_collector import sincronizar_grafo
print(sincronizar_grafo())
"

# Onda 3 (opcional, ~15min): fees dos prospectos PDF
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
import logging; logging.basicConfig(level=logging.INFO)
from collectors.prospecto_parser import enriquecer_ofertas_fii_com_fees
print(enriquecer_ofertas_fii_com_fees())
"
```

---

## Como rodar

### Dashboard Streamlit

```bash
.venv/bin/streamlit run app.py
```

Abre em `http://localhost:8501`. O scheduler de coleta automática inicia junto e
roda a cada 30 minutos por padrão.

### Scripts standalone

```bash
# Diagnóstico do grafo (quantas ofertas, quanta cobertura)
.venv/bin/python run.py graph.diagnosticar_banco

# Limpar ofertas inventadas pelo LLM
.venv/bin/python run.py graph.limpar_dados --apenas-fake

# Limpar tudo
.venv/bin/python run.py graph.limpar_dados
```

---

## Pipeline de coleta

```
┌─────────────────────────────────────────────────────────────┐
│ Onda 1: Ofertas (1× por dia, idempotente)                  │
│                                                             │
│  dados.cvm.gov.br/dataset/oferta-distrib                   │
│            │                                                │
│            ▼                                                │
│  oferta_distribuicao.zip (~5 MB, cache 6h)                 │
│            │                                                │
│            ▼                                                │
│  oferta_resolucao_160.csv (13.197 linhas)                  │
│            │ filtro: Status_Requerimento ∈                  │
│            │ {Registro Concedido, Aguardando Bookbuilding,│
│            │  Oferta Suspensa}                              │
│            ▼                                                │
│  ~1.643 ofertas ativas → upsert no Neo4j                   │
│  + Emissor + Banco líder + relacionamentos                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Onda 2: FundoFII (mensal, novo informe sai a cada mês)     │
│                                                             │
│  dados.cvm.gov.br/dataset/fii-doc-inf_mensal               │
│            │                                                │
│            ▼                                                │
│  inf_mensal_fii_2025.zip (~1.5 MB, cache 6h)               │
│            │                                                │
│            ▼                                                │
│  3 CSVs: geral + complemento + ativo_passivo               │
│            │ snapshot mais recente por CNPJ                 │
│            ▼                                                │
│  ~1.347 FIIs com:                                          │
│  - PL, VP/Cota, nº cotistas, taxa adm, rendimento mensal   │
│  - Tipo inferido: Tijolo (687) / Papel (192) /             │
│    FoF (173) / Híbrido (49)                                │
│  + relacionamento (:Oferta)-[:EMITIDA_POR]->(:FundoFII)    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Onda 3 (opcional): Fees dos prospectos                     │
│                                                             │
│  Para cada Oferta FII em andamento:                         │
│            │                                                │
│            ▼                                                │
│  GET /sre-publico-cvm/rest/sitePublico/pesquisar/          │
│      documentosPublicados/{id}                              │
│            │                                                │
│            ▼                                                │
│  Acha "Prospecto Definitivo"                                │
│            │                                                │
│            ▼                                                │
│  GET /sre-publico-cvm/rest/download/{uuid}                  │
│            │ pypdf extrai texto                             │
│            ▼                                                │
│  Regex captura:                                             │
│  - Comissão de Coordenação/Distribuição (R$ + %)           │
│  - Custo total da oferta                                    │
│  - Preço de emissão por cota                                │
│  - Custo unitário de distribuição                           │
│                                                             │
│  Taxa de sucesso: ~16% das ofertas têm prospecto            │
│  publicado na CVM. As outras 84% não dependem do código.    │
└─────────────────────────────────────────────────────────────┘
```

---

## Aba a aba do dashboard

### Mercado agora

**Cards**: Ofertas filtradas · Volume total registrado · Comissão média (n=N) ·
FIIs com dados financeiros.

**Filtros**:
- Tipo (FII / CRI / CRA / Debênture / Todos)
- Cobertura mínima:
  - **Cadastral** — só registro CVM
  - **Fundo** — tem dados do informe mensal vinculado
  - **Prospecto** — tem fee extraído do PDF
  - **Completo** — prospecto + informe mensal

**Tabela** com 18 colunas configuráveis: ID, Cobertura, Nº Registro, Tipo, Tipo FII,
Emissor, Volume, Data, Distribuidores (com papéis LIDER/DISTRIB), Preço Emissão,
Comissão Distr., Regime, Público, Rent. mês, VP/Cota, PL Fundo, Taxa Adm, Cotistas.

**Panorama visual** (4 painéis):
1. Donut: distribuição de ofertas por tipo
2. Barras: volume total por tipo (R$ bi)
3. Histograma: distribuição de volume por oferta (R$ mi, clipped no p95)
4. Stacked bar: público-alvo por tipo

**Ranking de distribuidores líderes** (top 15) — barras horizontais.

### BTG vs concorrentes

**Cards**: Ofertas BTG · Total mercado · Market share BTG (consolida 3 razões
sociais: Investment Banking, Serviços Financeiros DTVM, BTG Pactual).

**Posicionamento por tipo de ativo**: tabela com qtd BTG, qtd total, share %,
volume médio BTG, volume médio mercado.

**Ranking de distribuidores**: top 15 com volume agregado.

**Ofertas por distribuidor**: filtre por banco (XP, Santander, Itaú, ou nome
custom) e veja todas as ofertas que aquele banco distribui.

**Comparador de ofertas**: selecione 2 ofertas (filtradas por tipo) e veja
lado-a-lado todos os 16 atributos (regime, público, fees, PL, cotistas, etc.).

**Oportunidades**: ofertas grandes onde o BTG não está como distribuidor,
ordenadas por volume.

### Alertas

**Detecção automática** — 4 regras de negócio:
- **R1**: Oferta > R$ 500 mi onde BTG não está → ALTA
- **R2**: FII com PL > R$ 1 bi sem BTG → MEDIA
- **R3**: Market share BTG < 5% numa categoria com ≥20 ofertas → MEDIA
- **R4**: Comissão de oferta > 1% (acima da mediana) → BAIXA

Idempotente: pode rodar 10× que não duplica (`MERGE` no `(:Alerta {tipo, chave})`).

**Criação manual** — formulário com tipo, criticidade, descrição e id_oferta opcional.

**Lista** filtrável por criticidade, com botão "Marcar como visualizado".

### Pergunte ao agente

Chat com input fixo no rodapé da viewport (responsivo à sidebar). O supervisor
roteia para Analista / Coletor / Recomendador conforme a pergunta.

Exemplos que funcionam:
- "Qual o volume médio das ofertas FII em andamento?"
- "Quem é o maior distribuidor por volume?"
- "Compare BTG e XP no mercado de FII"
- "Qual a mediana de taxa de administração dos FIIs Tijolo?"
- "Crie um alerta sobre as ofertas acima de R$ 500 mi sem BTG"

---

## Fontes de dados

| Fonte | URL | Acesso | Atualização | Cobertura no projeto |
|---|---|---|---|---|
| **CVM Dados Abertos — oferta-distrib** | dados.cvm.gov.br/dataset/oferta-distrib | Público, sem auth | Diária | **Primária** — todas as ofertas |
| **CVM Dados Abertos — fii-doc-inf_mensal** | dados.cvm.gov.br/dataset/fii-doc-inf_mensal | Público, sem auth | Mensal | **Primária** — dados financeiros FII |
| **CVM Portal SRE (documentos)** | web.cvm.gov.br/sre-publico-cvm/rest/.../documentosPublicados/{id} | Público, sem auth | Conforme publicação | Prospectos PDF |
| **CVM Portal SRE (pesquisa)** | .../sitePublico/pesquisar/* | Público | — | **Fora do ar** desde 25/05/2026 — substituído por dados abertos |
| **ANBIMA Data API** | api.anbima.com.br/feed/precos-indices | OAuth (cadastro institucional) | Real-time | **Desativada na v1** — exige credenciais |

### O que NÃO está em dados abertos

- **Taxa final da oferta** e **indexador (IPCA/CDI)** — ficam só no prospecto PDF
  e na ANBIMA paga.
- **Vacância física/financeira** dos FIIs — está no Informe Trimestral
  (`fii-doc-inf_trimestral`), não no mensal. Não coletado na v1.
- **Cotação B3 e P/VP de mercado** — exige integração com B3 ou brapi.dev.
- **Fees de distribuição** — só extraído de prospectos PDF (cobertura ~16%).

---

## Schema do Neo4j

### Nós

```
(:Oferta {
  id_requerimento, numero_registro, tipo, status, nome_emissor,
  volume_total, data_registro, data_encerramento,
  regime_distribuicao, publico_alvo, mercado_negociacao,
  preco_emissao_cota, comissao_coord_distr_pct, custo_total_oferta_pct,
  taxa_final, taxa_minima, taxa_maxima,   // sempre null com fonte atual
  coletado_em
})

(:FundoFII {
  ticker, cnpj, nome, tipo,                              // Tijolo/Papel/Híbrido/FoF
  patrimonio_liquido, vp_cota, num_cotistas,
  taxa_administracao, rendimento_cota_mes,
  coletado_em
})

(:Banco {nome, tipo})
(:Emissor {cnpj, nome, setor})
(:Indexador {nome})              // vazio com fonte atual
(:Alerta {id, tipo, descricao, criticidade, criado_em, visualizado, chave})
```

### Relacionamentos

```
(:Banco)-[:DISTRIBUI {papel: 'COORDENADOR_LIDER' | 'DISTRIBUIDOR'}]->(:Oferta)
(:Emissor)-[:EMITIU]->(:Oferta)
(:Oferta)-[:EMITIDA_POR]->(:FundoFII)
(:Oferta)-[:INDEXADA_POR]->(:Indexador)
(:Alerta)-[:REFERE_SE_A]->(:Oferta)
```

### Constraints

```cypher
CREATE CONSTRAINT oferta_id ON (o:Oferta) REQUIRE o.id_requerimento IS UNIQUE
CREATE CONSTRAINT fundo_fii_ticker ON (f:FundoFII) REQUIRE f.ticker IS UNIQUE
CREATE CONSTRAINT banco_nome ON (b:Banco) REQUIRE b.nome IS UNIQUE
CREATE CONSTRAINT emissor_cnpj ON (e:Emissor) REQUIRE e.cnpj IS UNIQUE
CREATE CONSTRAINT indexador_nome ON (i:Indexador) REQUIRE i.nome IS UNIQUE
CREATE CONSTRAINT alerta_id ON (a:Alerta) REQUIRE a.id IS UNIQUE
```

Todos os upserts usam `MERGE` — pipeline pode rodar 100× sem duplicar.

---

## Limitações conhecidas

### 1. Taxa e indexador da oferta

A CVM **não publica** taxa final nem indexador (IPCA/CDI) em dados abertos.
Esses campos no nó `:Oferta` ficam `null` para CRI/CRA. Para FII de papel, dá
para inferir parcialmente via informe mensal, mas não para ofertas primárias.

**Quem precisa disso**: ANBIMA Data API (paga) tem 100% das taxas e indexadores
em tempo real. Quando o BTG fornecer credenciais ANBIMA, basta plugar no
`anbima_collector.py` (stub pronto).

### 2. Vacância dos FIIs

Está no Informe Trimestral Estruturado (`fii-doc-inf_trimestral`), não coletado
na v1. Adicionar é ~2h de trabalho seguindo o mesmo padrão do `fii_collector.py`.

### 3. P/VP de mercado

Exige cotação B3 da cota. Pode ser plugada via `brapi.dev` (gratuita, sem auth,
60 req/min). Mantida fora da v1 por foco em dados regulatórios.

### 4. Parser de fees em prospecto PDF

Taxa de sucesso observada em amostra real:
- 27 / 166 ofertas FII têm dado parcial ou completo (~16%)
- 138 / 166 não têm prospecto publicado na CVM (limitação da fonte)
- 1 erro de regex

Pra subir para ~30%, precisaria adicionar variantes de regex (ex: "Honorários
de Distribuição") ou fallback com LLM para o texto da seção relevante.

### 5. CVM SRE pesquisa (endpoint `/pesquisar/*`)

Esteve fora do ar em 25-26/05/2026 (500 em todos os POSTs). O projeto migrou
para CVM Dados Abertos como fonte primária. O coletor de prospectos
(`prospecto_parser.py`) ainda usa `/documentosPublicados/{id}` que funciona
via GET — endpoint diferente, não afetado.

---

## Decisões de design

### Por que LangGraph e não outro framework?

LangGraph oferece o padrão "supervisor" nativamente (já testado pela Anthropic e
publicado como referência), com state graph explícito e controle de iteração.
Para 3 agentes especializados era a escolha mais direta sem reinventar.

### Onde o LangChain entra

LangGraph é construído em cima do LangChain — o projeto usa as duas bibliotecas
em camadas complementares:

- **`langchain_core.tools.tool`** — decorador que transforma funções Python em
  ferramentas tipadas para o LLM. Todas as 23 tools (em `tools/cvm_tools.py`,
  `tools/neo4j_tools.py`, `tools/market_tools.py`) são definidas assim.
- **`langchain_core.messages`** — tipos `HumanMessage`, `AIMessage`,
  `SystemMessage`, `ToolMessage` que circulam no state graph dos agentes.
- **`langchain_groq.ChatGroq`** — cliente do Groq que implementa a interface
  `BaseChatModel` do LangChain, com suporte nativo a tool calling.
- **`langgraph.graph.StateGraph`** — o orquestrador do supervisor em si, que
  consome os tipos acima.

Em resumo: LangChain fornece as *primitivas* (tools, mensagens, cliente LLM) e
LangGraph fornece a *orquestração* multi-agente.

### Por que Neo4j e não um vector store (LangChain)?

A alternativa óbvia em projetos com LangChain seria um vector store
(FAISS, Chroma, PGVector) indexando os PDFs e CSVs da CVM como embeddings, com
recuperação por similaridade semântica. Não serve aqui por três motivos:

1. **O domínio é estruturado, não textual.** Oferta tem N distribuidores,
   distribuidor tem N ofertas, emissor aparece em várias ofertas, FII tem várias
   emissões. São relacionamentos explícitos com cardinalidade — não parágrafos
   para fazer match por cosseno.
2. **As perguntas são analíticas, não semânticas.** "Quais ofertas o BTG não
   distribui mas a XP sim", "ranking de distribuidores por volume agregado",
   "market share por tipo de ativo" — são agregações e travessias de grafo
   resolvidas em milissegundos com Cypher. Um vector store retornaria os top-k
   chunks "parecidos com a pergunta", sem garantia de completude nem de cálculo
   correto.
3. **Anti-alucinação fica trivial num grafo.** Toda oferta tem um
   `id_requerimento` único com constraint no Neo4j. Se o LLM inventa um ID, o
   `MERGE` falha ou a query devolve vazio — o erro é detectável. Num vector
   store, dados inventados pelo LLM seriam indexados como qualquer outro
   embedding e voltariam como resposta válida.

Vector store entraria se o produto passasse a indexar **prospectos inteiros**
para Q&A semântico ("o que esse prospecto diz sobre lock-up?"). Aí seria
complementar ao Neo4j, não substituto.


---

## Troubleshooting

### "GROQ_API_KEY ausente"
Edite `.env` e adicione `GROQ_API_KEY=gsk_...`. Gere uma chave em
`console.groq.com/keys` (gratuito).

### "Não foi possível conectar ao Neo4j"
Verifique `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` no `.env`. Instâncias free
da Aura pausam após ~3 dias sem uso — acesse o painel e clique em "Resume".

### Chat retorna "Failed to call a function" (Groq 400)
O Llama 3.3 às vezes gera tool calls em formato não-padrão. O `loop_react` já
tem retry com hint — se persistir, suba `GROQ_TEMPERATURE` para `0.2` no `.env`.

### Dados antigos aparecendo após sincronizar
Cache do Streamlit retém por 60s. Clique em **Atualizar dados** na sidebar
ou aguarde 1 minuto.

### Aba "Mercado agora" vazia
Rode o pipeline de coleta (seção [Setup](#5-coletar-dados-iniciais)) e
clique em **Atualizar dados**.

### "BTG vs concorrentes" mostra 0% de share
Indica que nenhum nó `:Banco` com nome contendo "BTG PACTUAL" está vinculado
às ofertas. Re-rode a Onda 1 — o coletor cria 3 nós distintos do grupo BTG
e a query `gap_btg_vs_mercado` consolida via `CONTAINS 'BTG PACTUAL'`.

### Histograma vazio
Verifique que a coluna `volume` não está toda `null`. Ofertas em "Aguardando
Bookbuilding" têm volume null até o registro ser concedido — o histograma só
inclui as com volume > 0.

### Dados fake no banco (LLM inventou)
```bash
.venv/bin/python run.py graph.limpar_dados --apenas-fake
```
Apaga ofertas com IDs como `123456`, emissores genéricos como "Emissor 1", etc.

---


