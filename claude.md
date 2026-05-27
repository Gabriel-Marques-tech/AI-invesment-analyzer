# CLAUDE.md — Agente Inteligente de Ofertas Primárias Imobiliárias
**Parceiro:** Banco BTG Pactual  
**Stack:** Python · LangGraph · LangChain · Neo4j Aura · Groq · Streamlit  
**Padrão de agente:** Supervisor multi-agente  

---

## Contexto do Projeto

O BTG Pactual atua como distribuidor e coordenador de investimentos imobiliários estruturados — principalmente CRI (Certificado de Recebíveis Imobiliários), CRA e FIIs. Outros bancos e corretoras (XP, Itaú BBA, Bradesco BBI, entre outros) também distribuem produtos similares no mesmo mercado.

**O problema:** O time do BTG não consegue acompanhar em tempo real o que os concorrentes estão ofertando — a que taxa, com qual indexador, para qual emissor. A análise ainda depende de leitura manual e fragmentada de documentos públicos.

**A solução:** Um sistema de monitoramento contínuo com agentes de IA que coletam dados públicos da CVM e ANBIMA, armazenam em um grafo Neo4j, comparam ofertas do mercado e geram insights competitivos para o BTG — de forma automática, sem intervenção humana.

**Diferencial principal:** O sistema organiza os dados pela perspectiva do distribuidor (quem está ofertando o quê, a que taxa), não do produto. Isso não existe em nenhuma plataforma atual do mercado.

---

## Stack Técnica

```
langchain==0.3.25
langchain-community==0.3.23
langchain-groq==0.2.4
langgraph==0.2.28
neo4j==5.28.1
streamlit==1.45.1
apscheduler==3.10.4
requests==2.32.3
pdfplumber==0.11.4
python-dotenv==1.0.1
pandas==2.2.3
plotly==5.24.1
```

**LLM:** Groq — modelo `llama-3.1-70b-versatile` (gratuito, suporta tool calling)  
**Banco de dados:** Neo4j Aura (free tier — 1 instância gratuita em aura.neo4j.io)  
**Monitoramento:** APScheduler rodando em background dentro do Streamlit  

---

## Variáveis de Ambiente

Criar arquivo `.env` na raiz do projeto:

```env
GROQ_API_KEY=sua_chave_groq_aqui
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=sua_senha_aura_aqui
COLETA_INTERVALO_MINUTOS=30
```

**Como obter as chaves:**
- Groq: cadastro gratuito em console.groq.com → API Keys → Create API Key
- Neo4j Aura: cadastro gratuito em aura.neo4j.io → New Instance → Free → salvar URI, user e password

---

## Estrutura de Arquivos

```
btg-oferta-primaria/
├── .env
├── requirements.txt
├── CLAUDE.md
│
├── collectors/
│   ├── __init__.py
│   ├── cvm_collector.py          # endpoints REST do portal SRE da CVM
│   └── anbima_collector.py       # API pública da ANBIMA Data
│
├── graph/
│   ├── __init__.py
│   ├── neo4j_client.py           # conexão e operações com Neo4j Aura
│   ├── schema.py                 # criação dos constraints e índices
│   └── queries.py                # queries Cypher reutilizáveis
│
├── agents/
│   ├── __init__.py
│   ├── supervisor.py             # orquestrador LangGraph — supervisor pattern
│   ├── collector_agent.py        # agente responsável por buscar dados novos
│   ├── analyst_agent.py          # agente responsável por comparar e analisar
│   └── recommender_agent.py      # agente responsável por gerar insights BTG
│
├── tools/
│   ├── __init__.py
│   ├── cvm_tools.py              # LangChain tools que chamam o cvm_collector
│   ├── neo4j_tools.py            # LangChain tools que fazem queries no grafo
│   └── market_tools.py           # LangChain tools de análise e comparação
│
├── scheduler/
│   ├── __init__.py
│   └── monitor.py                # APScheduler — roda coleta em background
│
└── app.py                        # Streamlit — dashboard + chat do analista
```

---

## Fontes de Dados Públicas

### CVM SRE — Portal de Ofertas Públicas

O portal `web.cvm.gov.br/sre-publico-cvm` é um frontend AngularJS que consome endpoints REST internos. Não usar Selenium — chamar os endpoints diretamente.

**URL base:** `https://web.cvm.gov.br/sre-publico-cvm/rest`

#### Endpoint 1 — Listar ofertas (principal)
```
POST /sitePublico/pesquisar/detalhado
Content-Type: application/json

Body:
{
  "tipoOferta": "PUBLICA",
  "situacao": "EM_ANDAMENTO",
  "categoria": "CRI",        # ou CRA, FII, DEBENTURE
  "pagina": 1,
  "quantidadePorPagina": 50
}

Retorna: lista de ofertas com idRequerimento, emissor, coordenador, volume, datas, status
```

#### Endpoint 2 — Detalhes da oferta
```
GET /sitePublico/pesquisar/requerimento/{idRequerimento}

Retorna: características do ativo, participantes, documentos associados
```

#### Endpoint 3 — Taxa e bookbuilding (CRÍTICO para o projeto)
```
GET /sitePublico/pesquisar/infOferta/{idRequerimento}

Retorna: taxa_final, taxa_minima, taxa_maxima, demanda_total, 
         volume_alocado, data_bookbuilding, indexador
```

#### Endpoint 4 — Participantes e distribuidores
```
GET /sitePublico/pesquisar/participantes/{idRequerimento}

Retorna: lista de coordenadores, distribuidores, agente fiduciário
         — campo mais importante: papel de cada banco na operação
```

#### Endpoint 5 — Download de PDF (opcional)
```
GET /download/{uuid}

O uuid vem dentro do retorno do endpoint de requerimento,
no campo documentos[].valor
Usar pdfplumber para extrair texto se necessário
```

**Categorias disponíveis para filtrar:**
`CRI`, `CRA`, `FII`, `DEBENTURE`, `FIDC`, `CDB`, `LCI`, `LCA`

**Implementação do collector CVM:**
```python
import requests

BASE_URL = "https://web.cvm.gov.br/sre-publico-cvm/rest"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://web.cvm.gov.br/sre-publico-cvm/",
    "Origin": "https://web.cvm.gov.br"
}

def listar_ofertas(categoria="CRI", pagina=1):
    body = {
        "tipoOferta": "PUBLICA",
        "situacao": "EM_ANDAMENTO", 
        "categoria": categoria,
        "pagina": pagina,
        "quantidadePorPagina": 50
    }
    resp = requests.post(f"{BASE_URL}/sitePublico/pesquisar/detalhado", 
                         json=body, headers=HEADERS)
    return resp.json()

def buscar_info_oferta(id_requerimento):
    resp = requests.get(f"{BASE_URL}/sitePublico/pesquisar/infOferta/{id_requerimento}",
                        headers=HEADERS)
    return resp.json()

def buscar_participantes(id_requerimento):
    resp = requests.get(f"{BASE_URL}/sitePublico/pesquisar/participantes/{id_requerimento}",
                        headers=HEADERS)
    return resp.json()
```

### ANBIMA Data API

**URL base:** `https://data.anbima.com.br/api`

```
GET /cri/series?page=0&pageSize=50
# Lista CRIs com taxa indicativa, indexador, emissor, prazo

GET /cri/{codigoIsin}/taxas-indicativas
# Taxa de compra, venda e indicativa para um CRI específico

GET /fii?page=0&pageSize=50  
# Lista FIIs com DY, P/VP, patrimônio líquido

GET /mercado/indicadores
# IPCA implícito, CDI, taxa Selic atual
```

A API da ANBIMA é pública e não exige autenticação para os endpoints básicos.

---

## Schema do Neo4j

### Nós (nodes)

```cypher
// Criar constraints e índices ao inicializar
CREATE CONSTRAINT oferta_id IF NOT EXISTS 
  FOR (o:Oferta) REQUIRE o.id_requerimento IS UNIQUE;

CREATE CONSTRAINT banco_nome IF NOT EXISTS 
  FOR (b:Banco) REQUIRE b.nome IS UNIQUE;

CREATE CONSTRAINT emissor_cnpj IF NOT EXISTS 
  FOR (e:Emissor) REQUIRE e.cnpj IS UNIQUE;

CREATE CONSTRAINT indexador_nome IF NOT EXISTS 
  FOR (i:Indexador) REQUIRE i.nome IS UNIQUE;
```

```cypher
// Nó Oferta — representa uma emissão específica
(:Oferta {
  id_requerimento: string,      // chave primária CVM
  tipo: string,                 // CRI, CRA, FII, DEBENTURE
  status: string,               // EM_ANDAMENTO, ENCERRADA
  taxa_final: float,            // ex: 8.5 (significa IPCA + 8.5%)
  taxa_minima: float,
  taxa_maxima: float,
  volume_total: float,          // em reais
  data_registro: date,
  data_encerramento: date,
  prazo_anos: float,
  rating: string,               // AAA, AA+, etc
  coletado_em: datetime         // timestamp da última coleta
})

// Nó Banco — distribuidores e coordenadores
(:Banco {
  nome: string,                 // "BTG Pactual", "XP Investimentos"
  tipo: string                  // COORDENADOR_LIDER, DISTRIBUIDOR, AMBOS
})

// Nó Emissor — empresa que emite o ativo
(:Emissor {
  cnpj: string,
  nome: string,
  setor: string                 // LOGISTICA, LAJES, RESIDENCIAL, AGRO
})

// Nó Indexador — referência da taxa
(:Indexador {
  nome: string                  // IPCA, CDI, PREFIXADO, IGPM
})

// Nó Alerta — gerado pelo agente quando detecta variação relevante
(:Alerta {
  id: string,
  tipo: string,                 // NOVA_OFERTA, VARIACAO_TAXA, GAP_COMPETITIVO
  descricao: string,
  criticidade: string,          // ALTA, MEDIA, BAIXA
  criado_em: datetime,
  visualizado: boolean
})
```

### Relacionamentos

```cypher
// Banco distribui uma Oferta
(:Banco)-[:DISTRIBUI {papel: "COORDENADOR_LIDER"}]->(:Oferta)
(:Banco)-[:DISTRIBUI {papel: "DISTRIBUIDOR"}]->(:Oferta)

// Emissor emitiu a Oferta
(:Emissor)-[:EMITIU]->(:Oferta)

// Oferta usa um Indexador
(:Oferta)-[:INDEXADA_POR]->(:Indexador)

// Alerta está relacionado a uma Oferta
(:Alerta)-[:REFERE_SE_A]->(:Oferta)
```

### Queries Cypher úteis

```cypher
// Ofertas que concorrentes têm e BTG não distribui
MATCH (b:Banco)-[:DISTRIBUI]->(o:Oferta)-[:INDEXADA_POR]->(i:Indexador)
WHERE b.nome <> "BTG Pactual"
AND NOT (:Banco {nome: "BTG Pactual"})-[:DISTRIBUI]->(o)
AND o.status = "EM_ANDAMENTO"
RETURN o.tipo, o.taxa_final, i.nome, b.nome, o.volume_total
ORDER BY o.taxa_final DESC

// Taxa média do mercado por indexador
MATCH (o:Oferta)-[:INDEXADA_POR]->(i:Indexador)
WHERE o.status = "EM_ANDAMENTO" AND o.taxa_final IS NOT NULL
RETURN i.nome, avg(o.taxa_final) as taxa_media, count(o) as qtd_ofertas

// Posição do BTG vs mercado
MATCH (btg:Banco {nome: "BTG Pactual"})-[:DISTRIBUI]->(o:Oferta)-[:INDEXADA_POR]->(i:Indexador)
WITH i.nome as indexador, avg(o.taxa_final) as media_btg
MATCH (o2:Oferta)-[:INDEXADA_POR]->(:Indexador {nome: indexador})
WHERE o2.status = "EM_ANDAMENTO"
RETURN indexador, media_btg, avg(o2.taxa_final) as media_mercado,
       media_btg - avg(o2.taxa_final) as diferenca_bps
```

---

## Arquitetura Multi-Agente — LangGraph Supervisor

### Visão Geral

```
Analista BTG faz pergunta
        ↓
   [SUPERVISOR]
   LLM decide qual agente acionar
        ↓
   ┌────────────────────────────────┐
   │                                │
[COLETOR]          [ANALISTA]    [RECOMENDADOR]
busca dados        compara        gera insights
CVM + ANBIMA       no Neo4j       para BTG
popula Neo4j       calcula gaps   gera alertas
        │                                │
        └────────────────────────────────┘
                        ↓
              Resposta ao analista
```

### Implementação do Supervisor

```python
# agents/supervisor.py
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from typing import TypedDict, Literal

llm = ChatGroq(model="llama-3.1-70b-versatile", temperature=0)

class State(TypedDict):
    messages: list
    next_agent: str
    context: dict

def supervisor_node(state: State):
    """
    O supervisor lê a mensagem do analista e decide qual agente chamar.
    Retorna: "coletor", "analista", "recomendador" ou "FINISH"
    """
    system = """Você é o supervisor de um sistema de análise de mercado imobiliário.
    
    Agentes disponíveis:
    - coletor: busca dados novos da CVM e ANBIMA, atualiza o banco de dados
    - analista: compara taxas, calcula gaps competitivos, consulta o Neo4j
    - recomendador: gera insights e recomendações estratégicas para o BTG
    
    Decida qual agente deve responder à mensagem do usuário.
    Responda APENAS com o nome do agente ou FINISH se a tarefa está completa.
    """
    # ... implementação do roteamento
    pass

def build_graph():
    graph = StateGraph(State)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("coletor", collector_agent_node)
    graph.add_node("analista", analyst_agent_node)
    graph.add_node("recomendador", recommender_agent_node)
    
    graph.set_entry_point("supervisor")
    
    graph.add_conditional_edges(
        "supervisor",
        lambda s: s["next_agent"],
        {
            "coletor": "coletor",
            "analista": "analista", 
            "recomendador": "recomendador",
            "FINISH": END
        }
    )
    
    # Após cada agente, volta ao supervisor
    for agent in ["coletor", "analista", "recomendador"]:
        graph.add_edge(agent, "supervisor")
    
    return graph.compile()
```

### Agente Coletor

**Responsabilidade:** Buscar dados novos da CVM e ANBIMA e popular o Neo4j.

**Tools disponíveis:**
- `buscar_ofertas_cvm(categoria, pagina)` — chama POST /detalhado
- `buscar_info_oferta_cvm(id_requerimento)` — chama GET /infOferta
- `buscar_participantes_cvm(id_requerimento)` — chama GET /participantes
- `buscar_cris_anbima(pagina)` — chama API ANBIMA
- `salvar_oferta_neo4j(dados_oferta)` — persiste no grafo
- `oferta_ja_existe(id_requerimento)` — verifica duplicata

**Prompt do agente:**
```
Você é o agente coletor de dados de mercado imobiliário brasileiro.
Sua única responsabilidade é buscar ofertas públicas atualizadas 
da CVM e ANBIMA e salvar no banco de dados Neo4j.

Ao coletar, sempre busque na seguinte ordem de prioridade:
1. FII (prioridade máxima)
2. CRI
3. CRA
Para cada oferta, colete obrigatoriamente: taxa_final, indexador, 
volume, participantes (quem distribui).
Evite duplicatas verificando se o id_requerimento já existe.
```

### Agente Analista

**Responsabilidade:** Consultar o Neo4j e responder perguntas analíticas sobre o mercado.

**Tools disponíveis:**
- `query_grafo(cypher_query)` — executa Cypher no Neo4j Aura
- `calcular_media_mercado(indexador)` — média de taxa por indexador
- `gap_btg_vs_mercado(indexador)` — diferença da posição BTG vs média
- `ofertas_sem_btg()` — ofertas que concorrentes têm e BTG não distribui
- `historico_taxa_emissor(cnpj_emissor)` — evolução de taxas de um emissor

**Prompt do agente:**
```
Você é o agente analista de mercado imobiliário do BTG Pactual.
Você tem acesso a um banco de grafos Neo4j com todas as ofertas 
públicas de CRI, CRA e FII do mercado brasileiro.

Responda perguntas analíticas usando as ferramentas disponíveis.
Sempre contextualize os números: diga se uma taxa está acima ou 
abaixo da média do mercado e o quanto.
Use linguagem objetiva e direta para profissionais de finanças.
```

### Agente Recomendador

**Responsabilidade:** Gerar insights estratégicos e alertas para o BTG.

**Tools disponíveis:**
- `gerar_alerta_neo4j(tipo, descricao, criticidade, id_oferta)` — salva alerta
- `listar_alertas_pendentes()` — alertas não visualizados
- `gaps_competitivos_detalhados()` — análise completa de oportunidades
- `recomendar_posicionamento(indexador)` — sugestão de taxa para nova oferta BTG

**Prompt do agente:**
```
Você é o agente estratégico do BTG Pactual para investimentos imobiliários.
Seu papel é transformar dados de mercado em recomendações acionáveis.

Ao analisar, sempre responda: o que isso significa para o BTG?
Identifique: onde o BTG está perdendo mercado, onde pode ganhar,
e quais ofertas de concorrentes representam ameaça.
Gere alertas quando detectar variações de taxa acima de 50bps
ou quando surgir oferta relevante que o BTG não distribui.
```

---

## Monitoramento Contínuo — APScheduler

```python
# scheduler/monitor.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import os

def criar_scheduler(grafo_langgraph):
    """
    Inicia o scheduler em background.
    O job de coleta roda a cada COLETA_INTERVALO_MINUTOS minutos.
    """
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    
    intervalo = int(os.getenv("COLETA_INTERVALO_MINUTOS", 30))
    
    scheduler.add_job(
        func=executar_coleta,
        trigger=IntervalTrigger(minutes=intervalo),
        args=[grafo_langgraph],
        id="coleta_mercado",
        name="Coleta CVM + ANBIMA",
        replace_existing=True
    )
    
    scheduler.start()
    return scheduler

def executar_coleta(grafo):
    """
    Dispara o agente coletor via LangGraph.
    Roda em background — não bloqueia o Streamlit.
    """
    try:
        grafo.invoke({
            "messages": [("user", "Execute coleta completa priorizando FII, depois CRI e CRA, da CVM e ANBIMA.")],
            "next_agent": "coletor",
            "context": {}
        })
    except Exception as e:
        print(f"[SCHEDULER] Erro na coleta: {e}")
```

**Importante:** Inicializar o scheduler em `app.py` usando `st.session_state` para garantir que rode apenas uma vez:

```python
# app.py
if "scheduler_iniciado" not in st.session_state:
    st.session_state.scheduler = criar_scheduler(grafo)
    st.session_state.scheduler_iniciado = True
```

---

## Dashboard Streamlit — app.py

### Estrutura das abas

```python
import streamlit as st

st.set_page_config(
    page_title="BTG · Monitor de Mercado Imobiliário",
    page_icon="📊",
    layout="wide"
)

aba1, aba2, aba3, aba4 = st.tabs([
    "📊 Mercado agora",
    "⚡ BTG vs concorrentes", 
    "🔔 Alertas",
    "💬 Pergunte ao agente"
])
```

### Aba 1 — Mercado agora
- Tabela de todas as ofertas em andamento (CRI, CRA, FII)
- Filtros: tipo, indexador, banco distribuidor, taxa mínima
- Cards de resumo: total de ofertas, taxa média IPCA+, taxa média CDI+
- Gráfico Plotly: distribuição de taxas por indexador

### Aba 2 — BTG vs concorrentes
- Tabela comparativa: média BTG vs média mercado por indexador
- Destaque: ofertas que concorrentes têm e BTG não distribui
- Gráfico de posicionamento: BTG na curva de taxas do mercado

### Aba 3 — Alertas
- Lista de alertas gerados pelo agente recomendador
- Filtro por criticidade (ALTA, MEDIA, BAIXA)
- Botão para marcar como visualizado

### Aba 4 — Chat com o agente
```python
with aba4:
    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []
    
    for msg in st.session_state.mensagens:
        st.chat_message(msg["role"]).write(msg["content"])
    
    pergunta = st.chat_input("Pergunte sobre o mercado...")
    
    if pergunta:
        st.session_state.mensagens.append({"role": "user", "content": pergunta})
        
        with st.spinner("Analisando..."):
            resultado = grafo.invoke({
                "messages": [("user", pergunta)],
                "next_agent": "supervisor",
                "context": {}
            })
        
        resposta = resultado["messages"][-1].content
        st.session_state.mensagens.append({"role": "assistant", "content": resposta})
        st.rerun()
```

---

## Ordem de Implementação

Implementar nessa sequência exata para garantir que cada camada funciona antes de construir a próxima:

**1. Infraestrutura base** (graph/ + .env)
- Conectar ao Neo4j Aura e verificar conexão
- Criar constraints e índices do schema
- Testar queries Cypher básicas

**2. Coletores** (collectors/)
- Implementar e testar `cvm_collector.py` isoladamente
- Implementar e testar `anbima_collector.py` isoladamente
- Validar que os dados retornam com os campos necessários

**3. Tools LangChain** (tools/)
- Criar as tools wrappando os coletores
- Criar as tools de query no Neo4j
- Testar cada tool individualmente com `tool.invoke({...})`

**4. Agentes** (agents/)
- Implementar cada agente isoladamente e testar
- Montar o supervisor e o grafo LangGraph
- Testar o fluxo completo com uma pergunta simples

**5. Scheduler** (scheduler/)
- Implementar e testar o APScheduler
- Verificar que a coleta roda e popula o Neo4j corretamente

**6. Dashboard** (app.py)
- Implementar as 4 abas do Streamlit
- Integrar com o grafo LangGraph
- Integrar com o scheduler

---

## Como Executar

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis de ambiente
cp .env.example .env
# editar .env com as chaves

# Inicializar schema do Neo4j (rodar uma vez)
python -c "from graph.schema import criar_schema; criar_schema()"

# Rodar coleta inicial (popular o banco antes de abrir o dashboard)
python -c "from collectors.cvm_collector import coletar_tudo; coletar_tudo()"

# Iniciar o dashboard
streamlit run app.py
```

---

## Restrições e Decisões de Escopo

- **PDFs:** Usar apenas quando os endpoints estruturados não trouxerem taxa ou prazo. O endpoint `/infOferta` cobre a maioria dos casos sem precisar de PDF.
- **Vector store:** Não implementar nesta versão. Os dados são estruturados e o Neo4j resolve as queries necessárias.
- **Autenticação:** Sem login na v1 — o dashboard é interno para o time do BTG.
- **Categorias prioritárias:** Focar em FII primeiro. CRI e CRA como segunda prioridade.
- **Histórico:** Manter todas as ofertas no Neo4j mesmo as encerradas — útil para análise de tendência.
- **Erro de API:** Se CVM ou ANBIMA retornar erro, logar e continuar. Não interromper o scheduler.

---

## Contexto dos Documentos de Referência

O projeto tem três documentos de apoio que devem ser consultados:

1. **TAPI BTG** — briefing oficial do projeto com objetivos e tecnologias sugeridas
2. **Tutorial CVM SRE** — documenta os endpoints REST internos do portal SRE da CVM e como consumi-los sem Selenium
3. **Análise de FII** — glossário de variáveis dos fundos imobiliários (P/VP, DY, vacância, taxa de administração) para contextualizar as análises do agente

Os documentos estão disponíveis como PDFs no projeto do Claude.