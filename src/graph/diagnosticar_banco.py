"""Diagnóstico do estado real do grafo Neo4j.

Mostra exatamente quantos nós e relacionamentos existem, e onde estão as lacunas.
Útil para entender por que a UI mostra "None" em algumas colunas.
"""
import logging

from graph.neo4j_client import get_client

logger = logging.getLogger(__name__)


def diagnosticar() -> dict:
    cli = get_client()
    out: dict = {}

    # --- Contagens básicas ---
    contagens = cli.executar_leitura(
        """
        OPTIONAL MATCH (o:Oferta)         WITH count(o) AS n_oferta
        OPTIONAL MATCH (f:FundoFII)       WITH n_oferta, count(f) AS n_fundo
        OPTIONAL MATCH (e:Emissor)        WITH n_oferta, n_fundo, count(e) AS n_emissor
        OPTIONAL MATCH (b:Banco)          WITH n_oferta, n_fundo, n_emissor, count(b) AS n_banco
        OPTIONAL MATCH (a:Alerta)         WITH n_oferta, n_fundo, n_emissor, n_banco, count(a) AS n_alerta
        RETURN n_oferta, n_fundo, n_emissor, n_banco, n_alerta
        """
    )
    out["nos"] = contagens[0] if contagens else {}

    # --- Relacionamentos ---
    rels = cli.executar_leitura(
        """
        OPTIONAL MATCH ()-[r:DISTRIBUI]->()    WITH count(r) AS r_distribui
        OPTIONAL MATCH ()-[r:EMITIU]->()       WITH r_distribui, count(r) AS r_emitiu
        OPTIONAL MATCH ()-[r:EMITIDA_POR]->()  WITH r_distribui, r_emitiu, count(r) AS r_emitida_por
        OPTIONAL MATCH ()-[r:INDEXADA_POR]->() WITH r_distribui, r_emitiu, r_emitida_por, count(r) AS r_indexada
        RETURN r_distribui, r_emitiu, r_emitida_por, r_indexada
        """
    )
    out["relacionamentos"] = rels[0] if rels else {}

    # --- Cobertura de campos críticos no nó Oferta ---
    cob = cli.executar_leitura(
        """
        MATCH (o:Oferta) WHERE o.status = 'EM_ANDAMENTO'
        RETURN count(o) AS total,
               count(o.data_registro) AS com_data,
               count(o.volume_total) AS com_volume,
               count(o.preco_emissao_cota) AS com_preco_emissao,
               count(o.comissao_coord_distr_pct) AS com_comissao,
               count(o.nome_emissor) AS com_nome_emissor,
               count(o.numero_registro) AS com_numero_registro
        """
    )
    out["cobertura_oferta_em_andamento"] = cob[0] if cob else {}

    # --- Cobertura de FundoFII ---
    cob_fii = cli.executar_leitura(
        """
        MATCH (f:FundoFII)
        RETURN count(f) AS total,
               count(f.dy_12m) AS com_dy_12m,
               count(f.rendimento_cota_mes) AS com_rend_mes,
               count(f.patrimonio_liquido) AS com_pl,
               count(f.vp_cota) AS com_vp_cota,
               count(f.num_cotistas) AS com_cotistas,
               count(f.taxa_administracao) AS com_taxa_adm,
               count(f.tipo) AS com_tipo
        """
    )
    out["cobertura_fundo_fii"] = cob_fii[0] if cob_fii else {}

    # --- Amostra: 5 ofertas em andamento e o que têm ---
    amostra = cli.executar_leitura(
        """
        MATCH (o:Oferta) WHERE o.status = 'EM_ANDAMENTO'
        OPTIONAL MATCH (o)-[:EMITIDA_POR]->(f:FundoFII)
        OPTIONAL MATCH (e:Emissor)-[:EMITIU]->(o)
        RETURN o.id_requerimento AS id, o.tipo AS tipo,
               toString(o.data_registro) AS data,
               o.volume_total AS volume,
               o.comissao_coord_distr_pct AS com,
               o.preco_emissao_cota AS preco,
               e.cnpj AS emissor_cnpj,
               f.cnpj AS fundo_cnpj,
               f.dy_12m AS fii_dy,
               f.patrimonio_liquido AS fii_pl
        ORDER BY o.data_registro DESC
        LIMIT 5
        """
    )
    out["amostra_5_ofertas"] = amostra

    # --- FIIs com Oferta vinculada (verifica se reconciliação funcionou) ---
    fii_vinculados = cli.executar_leitura(
        """
        MATCH (o:Oferta)-[:EMITIDA_POR]->(f:FundoFII)
        WHERE o.status = 'EM_ANDAMENTO'
        RETURN count(DISTINCT o) AS ofertas_com_fundo,
               count(DISTINCT f) AS fundos_com_oferta
        """
    )
    out["fii_vinculados"] = fii_vinculados[0] if fii_vinculados else {}

    return out


def imprimir_relatorio() -> None:
    import json
    d = diagnosticar()
    print("\n" + "=" * 60)
    print("DIAGNÓSTICO DO GRAFO NEO4J")
    print("=" * 60)

    print("\n[Nós]")
    for k, v in d["nos"].items():
        print(f"  {k:20s}: {v}")

    print("\n[Relacionamentos]")
    for k, v in d["relacionamentos"].items():
        print(f"  {k:20s}: {v}")

    cob = d["cobertura_oferta_em_andamento"]
    total = cob.get("total", 0)
    print(f"\n[Cobertura :Oferta EM_ANDAMENTO] (total={total})")
    for k, v in cob.items():
        if k == "total":
            continue
        pct = (v / total * 100) if total else 0
        print(f"  {k:25s}: {v:5d}  ({pct:5.1f}%)")

    cob_f = d["cobertura_fundo_fii"]
    total_f = cob_f.get("total", 0)
    print(f"\n[Cobertura :FundoFII] (total={total_f})")
    for k, v in cob_f.items():
        if k == "total":
            continue
        pct = (v / total_f * 100) if total_f else 0
        print(f"  {k:25s}: {v:5d}  ({pct:5.1f}%)")

    print(f"\n[Vínculo Oferta↔FundoFII]")
    fv = d["fii_vinculados"]
    print(f"  Ofertas em andamento com FundoFII vinculado: {fv.get('ofertas_com_fundo', 0)}")
    print(f"  Fundos com Oferta em andamento vinculada:    {fv.get('fundos_com_oferta', 0)}")

    print(f"\n[Amostra de 5 ofertas EM_ANDAMENTO]")
    print(json.dumps(d["amostra_5_ofertas"], indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    imprimir_relatorio()
