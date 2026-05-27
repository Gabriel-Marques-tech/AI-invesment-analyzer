"""Queries Cypher reutilizáveis.

Toda persistência usa MERGE para idempotência — o coletor pode rodar
várias vezes sobre o mesmo idRequerimento sem criar duplicatas.
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

from graph.neo4j_client import Neo4jClient, get_client

logger = logging.getLogger(__name__)

BANCO_BTG = "BTG Pactual"
# Padrão para casamento case-insensitive: pega todas as razões sociais do BTG
# (Investment Banking, Serviços Financeiros DTVM, etc.)
PADRAO_BTG = "BTG PACTUAL"

_ALIAS_BANCOS = {
    "btg": BANCO_BTG,
    "btg pactual": BANCO_BTG,
    "banco btg pactual": BANCO_BTG,
    "banco btg pactual s.a.": BANCO_BTG,
    "banco btg pactual s/a": BANCO_BTG,
}


def normalizar_nome_banco(nome: str) -> str:
    if not nome:
        return ""
    chave = nome.strip().lower().rstrip(".")
    return _ALIAS_BANCOS.get(chave, nome.strip())


def upsert_oferta(dados: dict, cliente: Optional[Neo4jClient] = None) -> dict:
    cliente = cliente or get_client()
    cypher = """
    MERGE (o:Oferta {id_requerimento: $id_requerimento})
    SET o.tipo               = coalesce($tipo, o.tipo),
        o.status             = coalesce($status, o.status),
        o.numero_registro    = coalesce($numero_registro, o.numero_registro),
        o.nome_emissor       = coalesce($nome_emissor, o.nome_emissor),
        o.taxa_final         = coalesce($taxa_final, o.taxa_final),
        o.taxa_minima        = coalesce($taxa_minima, o.taxa_minima),
        o.taxa_maxima        = coalesce($taxa_maxima, o.taxa_maxima),
        o.volume_total       = coalesce($volume_total, o.volume_total),
        o.data_registro      = CASE WHEN $data_registro IS NULL THEN o.data_registro ELSE date($data_registro) END,
        o.data_encerramento  = CASE WHEN $data_encerramento IS NULL THEN o.data_encerramento ELSE date($data_encerramento) END,
        o.prazo_anos         = coalesce($prazo_anos, o.prazo_anos),
        o.rating             = coalesce($rating, o.rating),
        o.tipo_requerimento  = coalesce($tipo_requerimento, o.tipo_requerimento),
        o.regime_distribuicao = coalesce($regime_distribuicao, o.regime_distribuicao),
        o.publico_alvo       = coalesce($publico_alvo, o.publico_alvo),
        o.mercado_negociacao = coalesce($mercado_negociacao, o.mercado_negociacao),
        o.preco_emissao_cota = coalesce($preco_emissao_cota, o.preco_emissao_cota),
        o.custo_unitario_distr = coalesce($custo_unitario_distribuicao, o.custo_unitario_distr),
        o.comissao_coord_distr_valor = coalesce($comissao_coord_distr_valor, o.comissao_coord_distr_valor),
        o.comissao_coord_distr_pct = coalesce($comissao_coord_distr_pct, o.comissao_coord_distr_pct),
        o.custo_total_oferta_valor = coalesce($custo_total_oferta_valor, o.custo_total_oferta_valor),
        o.custo_total_oferta_pct = coalesce($custo_total_oferta_pct, o.custo_total_oferta_pct),
        o.coletado_em        = datetime()
    RETURN o.id_requerimento AS id, o.coletado_em AS coletado_em
    """
    res = cliente.executar_escrita(cypher, _normalizar_params(dados, [
        "id_requerimento", "tipo", "status", "numero_registro", "nome_emissor",
        "taxa_final", "taxa_minima", "taxa_maxima", "volume_total",
        "data_registro", "data_encerramento", "prazo_anos", "rating",
        "tipo_requerimento", "regime_distribuicao", "publico_alvo", "mercado_negociacao",
        "preco_emissao_cota", "custo_unitario_distribuicao",
        "comissao_coord_distr_valor", "comissao_coord_distr_pct",
        "custo_total_oferta_valor", "custo_total_oferta_pct",
    ]))
    return res[0] if res else {}


def upsert_banco(nome: str, tipo: Optional[str] = None, cliente: Optional[Neo4jClient] = None) -> dict:
    cliente = cliente or get_client()
    nome_norm = normalizar_nome_banco(nome)
    cypher = """
    MERGE (b:Banco {nome: $nome})
    SET b.tipo = coalesce($tipo, b.tipo)
    RETURN b.nome AS nome
    """
    res = cliente.executar_escrita(cypher, {"nome": nome_norm, "tipo": tipo})
    return res[0] if res else {}


def upsert_emissor(cnpj: str, nome: str, setor: Optional[str] = None, cliente: Optional[Neo4jClient] = None) -> dict:
    cliente = cliente or get_client()
    cypher = """
    MERGE (e:Emissor {cnpj: $cnpj})
    SET e.nome  = coalesce($nome, e.nome),
        e.setor = coalesce($setor, e.setor)
    RETURN e.cnpj AS cnpj
    """
    res = cliente.executar_escrita(cypher, {"cnpj": cnpj, "nome": nome, "setor": setor})
    return res[0] if res else {}


def upsert_indexador(nome: str, cliente: Optional[Neo4jClient] = None) -> dict:
    cliente = cliente or get_client()
    res = cliente.executar_escrita(
        "MERGE (i:Indexador {nome: $nome}) RETURN i.nome AS nome",
        {"nome": (nome or "").upper().strip()},
    )
    return res[0] if res else {}


def upsert_fundo_fii(dados: dict, cliente: Optional[Neo4jClient] = None) -> dict:
    cliente = cliente or get_client()
    cypher = """
    MERGE (f:FundoFII {ticker: $ticker})
    SET f.cnpj                    = coalesce($cnpj, f.cnpj),
        f.nome                    = coalesce($nome, f.nome),
        f.tipo                    = coalesce($tipo, f.tipo),
        f.preco_cota              = coalesce($preco_cota, f.preco_cota),
        f.vp_cota                 = coalesce($vp_cota, f.vp_cota),
        f.p_vp                    = coalesce($p_vp, f.p_vp),
        f.patrimonio_liquido      = coalesce($patrimonio_liquido, f.patrimonio_liquido),
        f.dy_12m                  = coalesce($dy_12m, f.dy_12m),
        f.rendimento_cota_mes     = coalesce($rendimento_cota_mes, f.rendimento_cota_mes),
        f.vacancia_fisica         = coalesce($vacancia_fisica, f.vacancia_fisica),
        f.vacancia_financeira     = coalesce($vacancia_financeira, f.vacancia_financeira),
        f.num_imoveis             = coalesce($num_imoveis, f.num_imoveis),
        f.taxa_administracao      = coalesce($taxa_administracao, f.taxa_administracao),
        f.taxa_gestao             = coalesce($taxa_gestao, f.taxa_gestao),
        f.liquidez_media_diaria   = coalesce($liquidez_media_diaria, f.liquidez_media_diaria),
        f.num_cotistas            = coalesce($num_cotistas, f.num_cotistas),
        f.coletado_em             = datetime()
    RETURN f.ticker AS ticker
    """
    params = _normalizar_params(dados, [
        "ticker", "cnpj", "nome", "tipo", "preco_cota", "vp_cota", "p_vp",
        "patrimonio_liquido", "dy_12m", "rendimento_cota_mes", "vacancia_fisica",
        "vacancia_financeira", "num_imoveis", "taxa_administracao", "taxa_gestao",
        "liquidez_media_diaria", "num_cotistas",
    ])
    res = cliente.executar_escrita(cypher, params)
    return res[0] if res else {}


def relacionar_banco_oferta(
    banco_nome: str, id_requerimento: str, papel: str, cliente: Optional[Neo4jClient] = None
) -> None:
    cliente = cliente or get_client()
    cliente.executar_escrita(
        """
        MATCH (b:Banco {nome: $banco})
        MATCH (o:Oferta {id_requerimento: $id})
        MERGE (b)-[r:DISTRIBUI]->(o)
        SET r.papel = $papel
        """,
        {"banco": normalizar_nome_banco(banco_nome), "id": id_requerimento, "papel": papel},
    )


def relacionar_emissor_oferta(cnpj: str, id_requerimento: str, cliente: Optional[Neo4jClient] = None) -> None:
    cliente = cliente or get_client()
    cliente.executar_escrita(
        """
        MATCH (e:Emissor {cnpj: $cnpj})
        MATCH (o:Oferta {id_requerimento: $id})
        MERGE (e)-[:EMITIU]->(o)
        """,
        {"cnpj": cnpj, "id": id_requerimento},
    )


def relacionar_oferta_indexador(
    id_requerimento: str, indexador: str, cliente: Optional[Neo4jClient] = None
) -> None:
    cliente = cliente or get_client()
    cliente.executar_escrita(
        """
        MATCH (o:Oferta {id_requerimento: $id})
        MATCH (i:Indexador {nome: $idx})
        MERGE (o)-[:INDEXADA_POR]->(i)
        """,
        {"id": id_requerimento, "idx": (indexador or "").upper().strip()},
    )


def relacionar_oferta_fundo_fii(
    id_requerimento: str, ticker: str, cliente: Optional[Neo4jClient] = None
) -> None:
    cliente = cliente or get_client()
    cliente.executar_escrita(
        """
        MATCH (o:Oferta {id_requerimento: $id})
        MATCH (f:FundoFII {ticker: $ticker})
        MERGE (o)-[:EMITIDA_POR]->(f)
        """,
        {"id": id_requerimento, "ticker": ticker.upper().strip()},
    )


def criar_alerta(
    tipo: str,
    descricao: str,
    criticidade: str,
    id_oferta: Optional[str] = None,
    cliente: Optional[Neo4jClient] = None,
) -> str:
    cliente = cliente or get_client()
    alerta_id = str(uuid.uuid4())
    cliente.executar_escrita(
        """
        CREATE (a:Alerta {
          id: $id, tipo: $tipo, descricao: $descricao,
          criticidade: $criticidade, criado_em: datetime(), visualizado: false
        })
        WITH a
        OPTIONAL MATCH (o:Oferta {id_requerimento: $id_oferta})
        FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | MERGE (a)-[:REFERE_SE_A]->(o))
        """,
        {
            "id": alerta_id,
            "tipo": tipo,
            "descricao": descricao,
            "criticidade": criticidade,
            "id_oferta": id_oferta,
        },
    )
    return alerta_id


def oferta_ja_existe(id_requerimento: str, cliente: Optional[Neo4jClient] = None) -> bool:
    cliente = cliente or get_client()
    res = cliente.executar_leitura(
        "MATCH (o:Oferta {id_requerimento: $id}) RETURN count(o) AS c",
        {"id": id_requerimento},
    )
    return bool(res and res[0]["c"] > 0)


def listar_ofertas_em_andamento(
    tipo: Optional[str] = None, cliente: Optional[Neo4jClient] = None
) -> list[dict]:
    cliente = cliente or get_client()
    where_tipo = "AND o.tipo = $tipo" if tipo else ""
    cypher = f"""
    MATCH (o:Oferta)
    OPTIONAL MATCH (o)-[:INDEXADA_POR]->(i:Indexador)
    OPTIONAL MATCH (e:Emissor)-[:EMITIU]->(o)
    OPTIONAL MATCH (b:Banco)-[r:DISTRIBUI]->(o)
    OPTIONAL MATCH (o)-[:EMITIDA_POR]->(f:FundoFII)
    WHERE o.status = 'EM_ANDAMENTO' {where_tipo}
    RETURN o.id_requerimento AS id, o.numero_registro AS numero_registro,
           o.tipo AS tipo, o.taxa_final AS taxa,
           o.volume_total AS volume, o.data_registro AS data_registro,
           i.nome AS indexador,
           coalesce(e.nome, o.nome_emissor) AS emissor,
           collect(DISTINCT {{banco: b.nome, papel: r.papel}}) AS distribuidores,
           o.preco_emissao_cota AS preco_emissao,
           o.comissao_coord_distr_pct AS comissao_pct,
           o.regime_distribuicao AS regime,
           o.publico_alvo AS publico_alvo,
           f.tipo AS fii_tipo,
           f.rendimento_cota_mes AS fii_rend_mes,
           f.patrimonio_liquido AS fii_pl,
           f.vp_cota AS fii_vp_cota,
           f.taxa_administracao AS fii_taxa_adm,
           f.num_cotistas AS fii_cotistas
    ORDER BY data_registro DESC
    """
    return cliente.executar_leitura(cypher, {"tipo": tipo})


def ofertas_sem_btg(cliente: Optional[Neo4jClient] = None) -> list[dict]:
    """Ofertas em andamento onde nenhum banco do grupo BTG figura como distribuidor.

    Casa BTG por padrão case-insensitive (pega Investment Banking, Serviços
    Financeiros DTVM, etc.). Ordenado por volume (oportunidades maiores primeiro).
    """
    cliente = cliente or get_client()
    cypher = """
    MATCH (o:Oferta)
    WHERE o.status = 'EM_ANDAMENTO'
      AND NOT EXISTS {
        MATCH (bb:Banco)-[:DISTRIBUI]->(o)
        WHERE toUpper(bb.nome) CONTAINS $padrao
      }
    OPTIONAL MATCH (b:Banco)-[:DISTRIBUI]->(o)
    OPTIONAL MATCH (e:Emissor)-[:EMITIU]->(o)
    RETURN o.id_requerimento AS id,
           o.numero_registro AS numero_registro,
           o.tipo AS tipo,
           coalesce(e.nome, o.nome_emissor) AS emissor,
           o.volume_total AS volume,
           collect(DISTINCT b.nome) AS distribuidores
    ORDER BY coalesce(volume, 0) DESC
    """
    return cliente.executar_leitura(cypher, {"padrao": PADRAO_BTG})


def taxa_media_por_indexador(cliente: Optional[Neo4jClient] = None) -> list[dict]:
    cliente = cliente or get_client()
    cypher = """
    MATCH (o:Oferta)-[:INDEXADA_POR]->(i:Indexador)
    WHERE o.status = 'EM_ANDAMENTO' AND o.taxa_final IS NOT NULL
    RETURN i.nome AS indexador,
           avg(o.taxa_final) AS taxa_media,
           count(o) AS qtd_ofertas
    ORDER BY qtd_ofertas DESC
    """
    return cliente.executar_leitura(cypher)


def gap_btg_vs_mercado(cliente: Optional[Neo4jClient] = None) -> list[dict]:
    """Compara o BTG com o mercado total, agrupado por tipo de ativo (FII/CRI/CRA).

    Sem taxa/indexador no dataset CVM, usamos volume médio e nº de ofertas
    como métricas de posicionamento competitivo.
    """
    cliente = cliente or get_client()
    cypher = """
    MATCH (o:Oferta) WHERE o.status = 'EM_ANDAMENTO'
    OPTIONAL MATCH (b:Banco)-[:DISTRIBUI]->(o)
    WITH o, toUpper(coalesce(b.nome, '')) AS banco_upper
    WITH o, max(CASE WHEN banco_upper CONTAINS $padrao THEN 1 ELSE 0 END) AS eh_btg
    WITH o.tipo AS tipo,
         sum(eh_btg) AS qtd_btg,
         count(o) AS qtd_total,
         avg(CASE WHEN eh_btg = 1 THEN o.volume_total END) AS vol_medio_btg,
         avg(o.volume_total) AS vol_medio_mercado
    RETURN tipo,
           qtd_btg,
           qtd_total,
           toFloat(qtd_btg) / qtd_total * 100 AS share_pct,
           vol_medio_btg,
           vol_medio_mercado
    ORDER BY qtd_total DESC
    """
    return cliente.executar_leitura(cypher, {"padrao": PADRAO_BTG})


def ofertas_por_distribuidor(
    banco_padrao: str, cliente: Optional[Neo4jClient] = None
) -> list[dict]:
    """Lista todas as ofertas EM_ANDAMENTO distribuídas por um banco.

    `banco_padrao` é casado case-insensitive contra `Banco.nome` via CONTAINS
    (ex: 'BTG PACTUAL' pega Investment Banking + DTVM; 'XP' pega XP Investimentos).
    """
    cliente = cliente or get_client()
    cypher = """
    MATCH (b:Banco)-[r:DISTRIBUI]->(o:Oferta)
    WHERE o.status = 'EM_ANDAMENTO'
      AND toUpper(b.nome) CONTAINS toUpper($padrao)
    OPTIONAL MATCH (e:Emissor)-[:EMITIU]->(o)
    OPTIONAL MATCH (o)-[:EMITIDA_POR]->(f:FundoFII)
    RETURN o.id_requerimento AS id,
           o.numero_registro AS numero_registro,
           o.tipo AS tipo,
           coalesce(e.nome, o.nome_emissor) AS emissor,
           o.volume_total AS volume,
           o.data_registro AS data,
           o.regime_distribuicao AS regime,
           o.publico_alvo AS publico,
           collect(DISTINCT {{banco: b.nome, papel: r.papel}}) AS papeis_banco,
           f.tipo AS fii_tipo,
           f.patrimonio_liquido AS fii_pl
    ORDER BY coalesce(volume, 0) DESC
    """.replace("{{", "{").replace("}}", "}")
    return cliente.executar_leitura(cypher, {"padrao": banco_padrao})


def listar_bancos_distribuidores(
    cliente: Optional[Neo4jClient] = None,
) -> list[dict]:
    """Lista todos os bancos que têm pelo menos 1 oferta EM_ANDAMENTO, ordenados por nº de ofertas.

    Útil para popular dropdowns de seleção de distribuidor.
    """
    cliente = cliente or get_client()
    cypher = """
    MATCH (b:Banco)-[:DISTRIBUI]->(o:Oferta)
    WHERE o.status = 'EM_ANDAMENTO'
    RETURN b.nome AS banco, count(DISTINCT o) AS qtd
    ORDER BY qtd DESC
    """
    return cliente.executar_leitura(cypher)


def ranking_distribuidores(
    limite: int = 15, cliente: Optional[Neo4jClient] = None
) -> list[dict]:
    """Top N bancos por nº de ofertas em andamento + volume total distribuído.

    Agrupa o grupo BTG (Investment Banking, DTVM, etc.) sob 'BTG Pactual'.
    """
    cliente = cliente or get_client()
    cypher = """
    MATCH (b:Banco)-[:DISTRIBUI]->(o:Oferta)
    WHERE o.status = 'EM_ANDAMENTO'
    WITH CASE WHEN toUpper(b.nome) CONTAINS $padrao THEN 'BTG Pactual'
              ELSE b.nome END AS banco,
         o
    RETURN banco,
           count(DISTINCT o) AS qtd_ofertas,
           sum(o.volume_total) AS volume_total
    ORDER BY qtd_ofertas DESC
    LIMIT $limite
    """
    return cliente.executar_leitura(cypher, {"padrao": PADRAO_BTG, "limite": limite})


def listar_alertas_pendentes(
    criticidade: Optional[str] = None, cliente: Optional[Neo4jClient] = None
) -> list[dict]:
    cliente = cliente or get_client()
    where_crit = "AND a.criticidade = $criticidade" if criticidade else ""
    cypher = f"""
    MATCH (a:Alerta)
    WHERE a.visualizado = false {where_crit}
    OPTIONAL MATCH (a)-[:REFERE_SE_A]->(o:Oferta)
    RETURN a.id AS id, a.tipo AS tipo, a.descricao AS descricao,
           a.criticidade AS criticidade, a.criado_em AS criado_em,
           o.id_requerimento AS id_oferta
    ORDER BY criado_em DESC
    """
    return cliente.executar_leitura(cypher, {"criticidade": criticidade})


def marcar_alerta_visualizado(alerta_id: str, cliente: Optional[Neo4jClient] = None) -> None:
    cliente = cliente or get_client()
    cliente.executar_escrita(
        "MATCH (a:Alerta {id: $id}) SET a.visualizado = true",
        {"id": alerta_id},
    )


def historico_taxa_emissor(cnpj: str, cliente: Optional[Neo4jClient] = None) -> list[dict]:
    cliente = cliente or get_client()
    cypher = """
    MATCH (e:Emissor {cnpj: $cnpj})-[:EMITIU]->(o:Oferta)-[:INDEXADA_POR]->(i:Indexador)
    WHERE o.taxa_final IS NOT NULL
    RETURN o.id_requerimento AS id, o.tipo AS tipo, o.taxa_final AS taxa,
           i.nome AS indexador, o.data_registro AS data, o.status AS status
    ORDER BY data DESC
    """
    return cliente.executar_leitura(cypher, {"cnpj": cnpj})


def fundos_fii_destaque(
    limite: int = 20, cliente: Optional[Neo4jClient] = None
) -> list[dict]:
    cliente = cliente or get_client()
    cypher = """
    MATCH (f:FundoFII)
    WHERE f.p_vp IS NOT NULL AND f.dy_12m IS NOT NULL
    RETURN f.ticker AS ticker, f.nome AS nome, f.tipo AS tipo,
           f.p_vp AS p_vp, f.dy_12m AS dy_12m,
           f.patrimonio_liquido AS pl, f.vacancia_fisica AS vacancia
    ORDER BY abs(p_vp - 1.0) ASC
    LIMIT $limite
    """
    return cliente.executar_leitura(cypher, {"limite": limite})


def _normalizar_params(dados: dict, chaves: list[str]) -> dict:
    """Garante que todas as chaves esperadas estejam presentes (None se ausente)."""
    return {k: dados.get(k) for k in chaves}
