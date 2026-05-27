"""LangChain tools de análise comparativa e geração de alertas para o agente Recomendador."""
import logging
from typing import Optional

from langchain_core.tools import tool

from graph import queries

logger = logging.getLogger(__name__)

VARIACAO_TAXA_BPS_ALERTA = 50.0


@tool
def gerar_alerta(
    tipo: str,
    descricao: str,
    criticidade: str = "MEDIA",
    id_oferta: Optional[str] = None,
) -> dict:
    """Persiste um alerta no Neo4j para revisão posterior do time BTG.

    Use quando detectar: nova oferta relevante que o BTG não distribui (NOVA_OFERTA),
    variação de taxa acima de 50bps em um mesmo emissor (VARIACAO_TAXA), ou um gap
    competitivo claro (GAP_COMPETITIVO). criticidade deve ser ALTA, MEDIA ou BAIXA.
    id_oferta é opcional; se fornecido, vincula o alerta àquela oferta no grafo.
    """
    try:
        alerta_id = queries.criar_alerta(
            tipo=tipo, descricao=descricao, criticidade=criticidade, id_oferta=id_oferta
        )
        return {"id": alerta_id, "tipo": tipo, "criticidade": criticidade}
    except Exception as e:
        logger.error(f"gerar_alerta: {e}")
        return {"erro": str(e)}


@tool
def listar_alertas_pendentes(criticidade: Optional[str] = None) -> list[dict]:
    """Lista alertas ainda não visualizados pelo time BTG.

    Filtra por criticidade opcional (ALTA, MEDIA, BAIXA). Ordenado do mais
    recente para o mais antigo.
    """
    try:
        return queries.listar_alertas_pendentes(criticidade=criticidade)
    except Exception as e:
        return [{"erro": str(e)}]


@tool
def detectar_gaps_competitivos() -> dict:
    """Análise consolidada da posição BTG vs mercado.

    Combina: ofertas que concorrentes têm e BTG não, gap de taxa por indexador,
    e quais bancos lideram em cada categoria. Retorna um briefing acionável.
    """
    try:
        sem_btg = queries.ofertas_sem_btg()
        gap = queries.gap_btg_vs_mercado()
        criticos = [
            g for g in gap
            if g.get("diferenca_bps") is not None
            and abs(g["diferenca_bps"]) >= VARIACAO_TAXA_BPS_ALERTA
        ]
        return {
            "ofertas_sem_btg": sem_btg[:10],
            "qtd_total_sem_btg": len(sem_btg),
            "gaps_por_indexador": gap,
            "gaps_criticos": criticos,
            "limiar_bps": VARIACAO_TAXA_BPS_ALERTA,
        }
    except Exception as e:
        logger.error(f"detectar_gaps_competitivos: {e}")
        return {"erro": str(e)}


@tool
def recomendar_posicionamento_taxa(indexador: str) -> dict:
    """Sugere faixa de taxa para uma nova oferta BTG num determinado indexador.

    Baseado na média de mercado atual ± 1 desvio padrão (estimado a partir das
    ofertas em andamento). Use quando o time BTG estiver estruturando uma nova emissão.
    """
    try:
        medias = queries.taxa_media_por_indexador()
        alvo = next((m for m in medias if m["indexador"] == indexador.upper().strip()), None)
        if not alvo:
            return {
                "indexador": indexador,
                "erro": f"Sem dados suficientes para {indexador} no grafo.",
                "disponiveis": [m["indexador"] for m in medias],
            }
        media = alvo["taxa_media"]
        return {
            "indexador": indexador.upper(),
            "taxa_media_mercado": media,
            "faixa_recomendada": {"min": round(media - 0.3, 2), "max": round(media + 0.3, 2)},
            "qtd_referencias": alvo["qtd_ofertas"],
            "observacao": "Faixa baseada em média do mercado ± 30bps. Ajuste pelo risco do emissor.",
        }
    except Exception as e:
        return {"erro": str(e)}


MARKET_TOOLS = [
    gerar_alerta,
    listar_alertas_pendentes,
    detectar_gaps_competitivos,
    recomendar_posicionamento_taxa,
]
