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
    """Executa uma query Cypher de LEITURA no grafo Neo4j.

    Use para perguntas analíticas customizadas. A query deve começar com MATCH,
    OPTIONAL MATCH, WITH, CALL ou RETURN — escritas (CREATE, MERGE, DELETE, SET)
    são bloqueadas para proteger o banco.

    Schema do grafo:
    - (:Oferta {id_requerimento, tipo, status, taxa_final, volume_total, data_registro})
    - (:Banco {nome, tipo})
    - (:Emissor {cnpj, nome, setor})
    - (:Indexador {nome})
    - (:FundoFII {ticker, nome, tipo, p_vp, dy_12m, vacancia_fisica, taxa_administracao})
    - (:Banco)-[:DISTRIBUI {papel}]->(:Oferta)
    - (:Emissor)-[:EMITIU]->(:Oferta)
    - (:Oferta)-[:INDEXADA_POR]->(:Indexador)
    - (:Oferta)-[:EMITIDA_POR]->(:FundoFII)
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


NEO4J_TOOLS = [
    query_cypher,
    listar_ofertas_em_andamento,
    taxa_media_por_indexador,
    gap_btg_vs_mercado,
    ofertas_que_btg_nao_distribui,
    historico_taxa_emissor,
    listar_fundos_fii_destaque,
]
