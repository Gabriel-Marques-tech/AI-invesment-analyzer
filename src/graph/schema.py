import logging
from typing import Optional

from graph.neo4j_client import Neo4jClient, get_client

logger = logging.getLogger(__name__)


CONSTRAINTS = [
    "CREATE CONSTRAINT oferta_id IF NOT EXISTS FOR (o:Oferta) REQUIRE o.id_requerimento IS UNIQUE",
    "CREATE CONSTRAINT banco_nome IF NOT EXISTS FOR (b:Banco) REQUIRE b.nome IS UNIQUE",
    "CREATE CONSTRAINT emissor_cnpj IF NOT EXISTS FOR (e:Emissor) REQUIRE e.cnpj IS UNIQUE",
    "CREATE CONSTRAINT indexador_nome IF NOT EXISTS FOR (i:Indexador) REQUIRE i.nome IS UNIQUE",
    "CREATE CONSTRAINT alerta_id IF NOT EXISTS FOR (a:Alerta) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT fundo_fii_ticker IF NOT EXISTS FOR (f:FundoFII) REQUIRE f.ticker IS UNIQUE",
]

INDICES = [
    "CREATE INDEX oferta_status IF NOT EXISTS FOR (o:Oferta) ON (o.status)",
    "CREATE INDEX oferta_tipo IF NOT EXISTS FOR (o:Oferta) ON (o.tipo)",
    "CREATE INDEX oferta_data_registro IF NOT EXISTS FOR (o:Oferta) ON (o.data_registro)",
    "CREATE INDEX alerta_visualizado IF NOT EXISTS FOR (a:Alerta) ON (a.visualizado)",
    "CREATE INDEX alerta_criticidade IF NOT EXISTS FOR (a:Alerta) ON (a.criticidade)",
    "CREATE INDEX fundo_fii_tipo IF NOT EXISTS FOR (f:FundoFII) ON (f.tipo)",
    "CREATE INDEX emissor_setor IF NOT EXISTS FOR (e:Emissor) ON (e.setor)",
]

LABELS_PARA_LIMPAR = ["Oferta", "Banco", "Emissor", "Indexador", "Alerta", "FundoFII"]


def criar_schema(cliente: Optional[Neo4jClient] = None) -> dict:
    cliente = cliente or get_client()
    resultados = {"constraints": 0, "indices": 0, "erros": []}

    for stmt in CONSTRAINTS:
        try:
            cliente.executar_escrita(stmt)
            resultados["constraints"] += 1
        except Exception as e:
            resultados["erros"].append(f"{stmt[:60]}... → {e}")
            logger.warning(f"Constraint falhou: {e}")

    for stmt in INDICES:
        try:
            cliente.executar_escrita(stmt)
            resultados["indices"] += 1
        except Exception as e:
            resultados["erros"].append(f"{stmt[:60]}... → {e}")
            logger.warning(f"Índice falhou: {e}")

    logger.info(
        f"Schema aplicado: {resultados['constraints']} constraints, "
        f"{resultados['indices']} índices, {len(resultados['erros'])} erros"
    )
    return resultados


def dropar_schema(cliente: Optional[Neo4jClient] = None, apagar_dados: bool = False) -> None:
    cliente = cliente or get_client()

    if apagar_dados:
        for label in LABELS_PARA_LIMPAR:
            cliente.executar_escrita(f"MATCH (n:{label}) DETACH DELETE n")
            logger.info(f"Nós :{label} apagados")

    constraints = cliente.executar_leitura("SHOW CONSTRAINTS YIELD name")
    for c in constraints:
        cliente.executar_escrita(f"DROP CONSTRAINT {c['name']} IF EXISTS")

    indices = cliente.executar_leitura("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP'")
    for i in indices:
        cliente.executar_escrita(f"DROP INDEX {i['name']} IF EXISTS")

    logger.info("Schema dropado")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cliente = get_client()
    if not cliente.verificar_conexao():
        raise SystemExit("Não foi possível conectar ao Neo4j. Verifique credenciais no .env.")
    res = criar_schema(cliente)
    print(f"Constraints criadas: {res['constraints']}")
    print(f"Índices criados:     {res['indices']}")
    if res["erros"]:
        print("Erros:")
        for e in res["erros"]:
            print(f"  - {e}")
