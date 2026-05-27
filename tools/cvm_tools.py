"""LangChain tools de coleta da CVM (Dados Abertos)."""
import logging
import re
from typing import Optional

from langchain_core.tools import tool

from collectors import cvm_collector, fii_collector, prospecto_parser
from graph import queries

logger = logging.getLogger(__name__)

# IDs que são claramente exemplos/fake — agente coletor não deve inventar isso.
_IDS_OBVIAMENTE_FAKE = {
    "123456", "789012", "345678", "999999", "111111", "000000",
    "12345", "54321", "0", "1", "id", "exemplo", "test", "teste", "none", "null",
}

_PADROES_PLACEHOLDER = re.compile(
    r"(retornado|retornada|placeholder|exemplo|example|sample|"
    r"variable|valor|value|field|campo|aqui|here|todo|fixme|"
    r"id_requerimento|id_oferta|nome_emissor|emissor_nome)",
    re.IGNORECASE,
)


def _parece_fake(id_requerimento: str, emissor_nome: Optional[str]) -> Optional[str]:
    if not id_requerimento or not isinstance(id_requerimento, str):
        return "id_requerimento vazio ou inválido"
    s = id_requerimento.strip()
    if s.lower() in _IDS_OBVIAMENTE_FAKE:
        return f"id_requerimento '{s}' é um valor de exemplo"
    if len(s) < 3:
        return f"id_requerimento '{s}' é curto demais para ser real"
    if _PADROES_PLACEHOLDER.search(s):
        return (f"id_requerimento '{s}' parece um placeholder/nome de variável, "
                f"não um valor real da CVM")
    return None


@tool
def sincronizar_ofertas_cvm(
    categorias: Optional[list[str]] = None,
    limite: Optional[int] = None,
    forcar_download: bool = False,
) -> dict:
    """Sincroniza ofertas ativas da CVM Dados Abertos para o Neo4j.

    Esta é a ÚNICA tool que escreve no grafo. Baixa o dataset oficial
    (oferta_distribuicao.zip de dados.cvm.gov.br, atualizado diariamente),
    filtra ofertas com status ativo (Registro Concedido, Aguardando Bookbuilding,
    Oferta Suspensa) e persiste cada uma com seu emissor e coordenador líder.

    Args:
        categorias: lista entre ["FII", "CRI", "CRA", "DEBENTURE", "FIDC"].
                    Default: ["FII", "CRI", "CRA"].
        limite: número máximo de ofertas por categoria. Default: todas.
        forcar_download: se True, ignora cache local de 6h e baixa do zero.

    Retorna {"inseridos_por_categoria": {...}, "erros": int, "total_ativas_csv": int}.
    """
    try:
        return cvm_collector.sincronizar_grafo(
            categorias=categorias, limite=limite, forcar_download=forcar_download
        )
    except Exception as e:
        logger.exception(f"sincronizar_ofertas_cvm: {e}")
        return {"erro": str(e)}


@tool
def listar_ofertas_ativas_cvm(
    categoria: Optional[str] = None, limite: int = 20
) -> list[dict]:
    """Lista ofertas ativas do CSV da CVM (sem persistir no grafo).

    Útil para inspeção antes de sincronizar. Retorna até `limite` ofertas
    mais recentes, opcionalmente filtradas por categoria (FII, CRI, CRA, etc.).
    Cada item traz: id_requerimento, numero_registro, tipo, status, nome_emissor,
    volume_total, data_registro e info de líder/emissor.
    """
    try:
        return cvm_collector.listar_ofertas_ativas(categoria=categoria, limite=limite)
    except Exception as e:
        logger.exception(f"listar_ofertas_ativas_cvm: {e}")
        return [{"erro": str(e)}]


@tool
def buscar_oferta_cvm(id_requerimento: str) -> dict:
    """Busca uma oferta específica no CSV pelo Numero_Requerimento.

    Use quando o usuário citar um id concreto. Retorna o dicionário completo
    da oferta ou {"erro": "..."} se não encontrar.
    """
    try:
        resultado = cvm_collector.buscar_detalhes_oferta(id_requerimento)
        return resultado or {"erro": f"Oferta {id_requerimento} não encontrada no CSV"}
    except Exception as e:
        return {"erro": str(e)}


@tool
def diagnosticar_fonte_cvm() -> dict:
    """Roda um smoke test: confirma que o ZIP é baixável e mostra contagens por categoria.

    Use no início se suspeitar que a fonte está indisponível.
    """
    try:
        return cvm_collector.diagnosticar()
    except Exception as e:
        return {"erro": str(e)}


@tool
def oferta_ja_existe_no_grafo(id_requerimento: str) -> bool:
    """Verifica se uma oferta já foi salva no Neo4j."""
    try:
        return queries.oferta_ja_existe(id_requerimento)
    except Exception as e:
        logger.error(f"oferta_ja_existe_no_grafo({id_requerimento}): {e}")
        return False


@tool
def sincronizar_fundos_fii_cvm(
    ano: Optional[int] = None, limite: Optional[int] = None, forcar_download: bool = False
) -> dict:
    """Sincroniza os dados financeiros dos FIIs (informe mensal) para o grafo.

    Fonte: CVM Dados Abertos `fii-doc-inf_mensal` (anexo 39-I, Instrução CVM 571).
    Cada FII vira um nó :FundoFII com: nome, CNPJ, tipo inferido (Tijolo/Papel/
    Híbrido/FoF), PL, VP/Cota, número de cotistas, taxa de administração, etc.

    Vincula automaticamente cada FundoFII com as Ofertas no grafo que tenham
    o mesmo CNPJ no Emissor.

    Args:
        ano: 2021..2025. Default: ano anterior (CVM publica com lag).
        limite: máximo de FIIs a processar. Default: todos (~3.000 ativos).
        forcar_download: ignora cache de 6h e rebaixa.

    Retorna {"fundos_fii_inseridos": int, "relacionamentos_oferta_fundo": int, ...}.
    """
    try:
        return fii_collector.sincronizar_grafo(
            ano=ano, limite=limite, forcar_download=forcar_download
        )
    except Exception as e:
        logger.exception(f"sincronizar_fundos_fii_cvm: {e}")
        return {"erro": str(e)}


@tool
def diagnosticar_fonte_fii(ano: Optional[int] = None) -> dict:
    """Smoke test do dataset de informe mensal de FII. Mostra contagem por segmento e tipo."""
    try:
        return fii_collector.diagnosticar(ano=ano)
    except Exception as e:
        return {"erro": str(e)}


@tool
def enriquecer_fees_ofertas_fii(
    limite: Optional[int] = None, somente_sem_fees: bool = True
) -> dict:
    """Para cada Oferta FII em andamento no grafo, baixa o prospecto PDF e extrai os fees.

    Extrai: Comissão de Coordenação/Distribuição (valor R$ e % sobre montante),
    Custo total da oferta, Preço de emissão por cota, Custo unitário de distribuição.

    Args:
        limite: máximo de ofertas a processar. Default: todas.
        somente_sem_fees: se True, pula ofertas que já têm fees no grafo.

    Retorna estatísticas: {"sucesso_total": int, "sucesso_parcial": int, "sem_prospecto": int, "erro": int}.

    AVISO: pode demorar (download de PDF + extração ~3-5s por oferta). Use com `limite`.
    """
    try:
        return prospecto_parser.enriquecer_ofertas_fii_com_fees(
            limite=limite, somente_sem_fees=somente_sem_fees
        )
    except Exception as e:
        logger.exception(f"enriquecer_fees_ofertas_fii: {e}")
        return {"erro": str(e)}


@tool
def extrair_fees_oferta_unica(id_requerimento: str) -> dict:
    """Extrai fees de UMA oferta FII específica (sem persistir).

    Útil para debugar ou conferir um caso específico antes de rodar enriquecimento em lote.
    """
    try:
        return prospecto_parser.extrair_fees_oferta(id_requerimento)
    except Exception as e:
        return {"erro": str(e)}


CVM_TOOLS = [
    sincronizar_ofertas_cvm,
    listar_ofertas_ativas_cvm,
    buscar_oferta_cvm,
    diagnosticar_fonte_cvm,
    oferta_ja_existe_no_grafo,
    sincronizar_fundos_fii_cvm,
    diagnosticar_fonte_fii,
    enriquecer_fees_ofertas_fii,
    extrair_fees_oferta_unica,
]
