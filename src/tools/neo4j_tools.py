"""LangChain tools de leitura do grafo Neo4j para o agente Analista."""
import logging
from typing import Optional

from langchain_core.tools import tool

from graph import queries
from graph.neo4j_client import get_client

logger = logging.getLogger(__name__)

QUERIES_PERMITIDAS_PREFIXOS = ("MATCH ", "OPTIONAL MATCH ", "WITH ", "CALL ", "RETURN ")


@tool
def query_cypher(cypher: str) -> list[dict]:
    """Executa Cypher de LEITURA no Neo4j. USE para QUALQUER cálculo customizado.

    Tem todas as agregações: avg, sum, count, min, max, stDev, percentileCont.
    Você pode (e DEVE) calcular médias, medianas, percentis, ponderações, etc.

    Schema:
      (:Oferta {id_requerimento, tipo, status, numero_registro, nome_emissor,
        volume_total, data_registro, data_encerramento, regime_distribuicao,
        publico_alvo, preco_emissao_cota, comissao_coord_distr_pct,
        custo_total_oferta_pct})
      (:FundoFII {ticker, cnpj, nome, tipo, patrimonio_liquido, vp_cota,
        num_cotistas, taxa_administracao, rendimento_cota_mes})
      (:Banco {nome, tipo}), (:Emissor {cnpj, nome, setor})
      (:Banco)-[:DISTRIBUI {papel}]->(:Oferta)
      (:Emissor)-[:EMITIU]->(:Oferta)
      (:Oferta)-[:EMITIDA_POR]->(:FundoFII)

    Restrições: só MATCH/WITH/RETURN/CALL/OPTIONAL MATCH. Escritas bloqueadas.

    Exemplos:
      # Volume médio FII:
      MATCH (o:Oferta) WHERE o.tipo='FII' AND o.status='EM_ANDAMENTO'
      RETURN avg(o.volume_total) AS m, count(o) AS n

      # Mediana de taxa adm dos FIIs Tijolo:
      MATCH (f:FundoFII {tipo:'Tijolo'}) WHERE f.taxa_administracao IS NOT NULL
      RETURN percentileCont(f.taxa_administracao, 0.5) AS mediana
    """
    cypher_norm = cypher.strip().upper()
    if not any(cypher_norm.startswith(p) for p in QUERIES_PERMITIDAS_PREFIXOS):
        return [{"erro": "Apenas queries de leitura são permitidas (MATCH/WITH/CALL/RETURN)."}]
    if any(w in cypher_norm for w in (" CREATE ", " MERGE ", " DELETE ", " SET ", " REMOVE ", " DROP ")):
        return [{"erro": "Operações de escrita não são permitidas nesta tool."}]
    try:
        return get_client().executar_leitura(cypher)
    except Exception as e:
        logger.error(f"query_cypher: {e}")
        return [{"erro": str(e)}]


@tool
def listar_ofertas_em_andamento(tipo: Optional[str] = None) -> list[dict]:
    """Lista ofertas com status EM_ANDAMENTO no grafo.

    Filtra por tipo opcional (FII, CRI, CRA, DEBENTURE). Retorna id, taxa,
    volume, indexador, emissor e distribuidores de cada oferta.
    """
    try:
        return queries.listar_ofertas_em_andamento(tipo=tipo)
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def taxa_media_por_indexador() -> list[dict]:
    """Calcula a taxa média e quantidade de ofertas por indexador (IPCA, CDI, etc.).

    Use para estabelecer o benchmark do mercado antes de comparar uma oferta específica.
    """
    try:
        return queries.taxa_media_por_indexador()
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def gap_btg_vs_mercado() -> list[dict]:
    """Compara a taxa média das ofertas distribuídas pelo BTG com a média do mercado por indexador.

    Retorna, por indexador: media_btg, media_mercado e diferenca_bps (positivo = BTG paga
    mais que mercado; negativo = BTG paga menos).
    """
    try:
        return queries.gap_btg_vs_mercado()
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def ofertas_que_btg_nao_distribui() -> list[dict]:
    """Lista ofertas em andamento que outros bancos distribuem mas o BTG não.

    Cada item representa uma potencial oportunidade competitiva perdida.
    Ordenado por taxa decrescente (ofertas com taxa mais alta primeiro).
    """
    try:
        return queries.ofertas_sem_btg()
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def historico_taxa_emissor(cnpj: str) -> list[dict]:
    """Histórico de ofertas de um emissor específico.

    Use para entender como a taxa de um emissor evoluiu ao longo do tempo —
    útil para precificar uma nova oferta do mesmo emissor.
    """
    try:
        return queries.historico_taxa_emissor(cnpj)
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def listar_fundos_fii_destaque(limite: int = 20) -> list[dict]:
    """Lista FIIs ordenados por P/VP mais próximo de 1.

    Conforme priorização do kickoff BTG: P/VP perto de 1 sinaliza fundo bem
    precificado (sem prêmio nem desconto significativo sobre patrimônio).
    """
    try:
        return queries.fundos_fii_destaque(limite=limite)
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def panorama_mercado() -> dict:
    """Retorna um resumo agregado do mercado de ofertas em andamento.

    Use SEMPRE quando a pergunta for ampla ('como está o mercado', 'me dê um overview',
    'o que tem rolando'). Retorna: total de ofertas, volume agregado, breakdown
    por tipo (FII/CRI/CRA com qtd, volume total, volume médio, máximo) e estatísticas
    dos FundoFII vinculados (PL médio, taxa adm média, rendimento mensal médio).
    """
    try:
        return queries.panorama_mercado()
    except Exception as e:
        return {"erro": str(e)}


@tool
def fii_destaque_por_metrica(metrica: str = "patrimonio_liquido", limite: int = 5) -> list[dict]:
    """Top N FIIs ordenados por uma métrica financeira (do informe mensal CVM).

    Use quando a pergunta for tipo "qual o maior FII", "FII com mais cotistas",
    "FII que rende mais", etc.

    Métricas válidas:
    - 'patrimonio_liquido' → maior PL
    - 'num_cotistas' → mais cotistas
    - 'vp_cota' → maior valor patrimonial por cota
    - 'rendimento_cota_mes' → maior rendimento mensal
    - 'taxa_administracao' → maior taxa de admin (atenção: maior = pior pro cotista)
    """
    try:
        return queries.fii_destaque_por_metrica(metrica=metrica, limite=limite)
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def ranking_distribuidores_tool(limite: int = 15) -> list[dict]:
    """Top N bancos por nº de ofertas em andamento + volume total distribuído.

    Use para perguntas tipo "quem é o maior distribuidor", "ranking de bancos",
    "principais coordenadores", "BTG está em que posição".
    """
    try:
        return queries.ranking_distribuidores(limite=limite)
    except Exception as e:
        return [{"erro": str(e)}]


NEO4J_TOOLS = [
    query_cypher,
    listar_ofertas_em_andamento,
    taxa_media_por_indexador,
    gap_btg_vs_mercado,
    ofertas_que_btg_nao_distribui,
    historico_taxa_emissor,
    listar_fundos_fii_destaque,
    panorama_mercado,
    fii_destaque_por_metrica,
    ranking_distribuidores_tool,
]
