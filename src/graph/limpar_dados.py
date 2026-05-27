"""Utilitário para zerar nós do banco Neo4j (mantém schema/constraints).

Use quando o grafo estiver com dados inválidos (ex: alucinações do LLM)
e precisar de uma base limpa antes da próxima coleta.

Uso:
    .venv/bin/python -m graph.limpar_dados            # apaga tudo
    .venv/bin/python -m graph.limpar_dados --apenas-fake  # só ofertas obviamente fake
"""
import argparse
import logging
import sys

from graph.neo4j_client import Neo4jClient, get_client

logger = logging.getLogger(__name__)

LABELS = ["Oferta", "Banco", "Emissor", "Indexador", "FundoFII", "Alerta"]


def contar_nos(cliente: Neo4jClient) -> dict[str, int]:
    out = {}
    for label in LABELS:
        res = cliente.executar_leitura(f"MATCH (n:{label}) RETURN count(n) AS c")
        out[label] = res[0]["c"] if res else 0
    return out


def limpar_tudo(cliente: Neo4jClient) -> dict[str, int]:
    apagados: dict[str, int] = {}
    for label in LABELS:
        res = cliente.executar_escrita(
            f"MATCH (n:{label}) WITH n, count(*) AS _ DETACH DELETE n RETURN count(_) AS apagados"
        )
        # res pode vir vazio se label não existir
        apagados[label] = res[0]["apagados"] if res else 0
    return apagados


def limpar_apenas_fake(cliente: Neo4jClient) -> dict[str, int]:
    """Apaga ofertas com indícios óbvios de dados inventados pelo LLM.

    Critério: id_requerimento curto demais (<6 chars) OU emissor com nome genérico
    tipo 'Emissor 1', 'Teste', etc. Cascateia para Emissor/Banco órfãos.
    """
    cliente.executar_escrita(
        """
        MATCH (o:Oferta)
        WHERE size(o.id_requerimento) < 6
           OR o.id_requerimento IN ['123456','789012','345678','999999','111111']
        DETACH DELETE o
        """
    )
    cliente.executar_escrita(
        """
        MATCH (e:Emissor)
        WHERE e.nome =~ '(?i)emissor\\s*\\d+|exemplo|teste|fake|mock'
          AND NOT (e)-[:EMITIU]->(:Oferta)
        DETACH DELETE e
        """
    )
    cliente.executar_escrita(
        """
        MATCH (b:Banco)
        WHERE NOT (b)-[:DISTRIBUI]->(:Oferta)
        DETACH DELETE b
        """
    )
    cliente.executar_escrita(
        """
        MATCH (i:Indexador)
        WHERE NOT (:Oferta)-[:INDEXADA_POR]->(i)
        DETACH DELETE i
        """
    )
    return contar_nos(cliente)


def main() -> None:
    parser = argparse.ArgumentParser(description="Limpa nós do grafo Neo4j.")
    parser.add_argument(
        "--apenas-fake", action="store_true",
        help="Apaga apenas ofertas com indícios de dados inventados pelo LLM."
    )
    parser.add_argument(
        "--sim", action="store_true",
        help="Pula a confirmação interativa.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cliente = get_client()
    if not cliente.verificar_conexao():
        sys.exit("Erro: não foi possível conectar ao Neo4j.")

    antes = contar_nos(cliente)
    print("Estado atual do grafo:")
    for label, qtd in antes.items():
        print(f"  :{label}  {qtd}")

    if sum(antes.values()) == 0:
        print("\nGrafo já está vazio. Nada a fazer.")
        return

    modo = "ofertas suspeitas de serem fake" if args.apenas_fake else "TODOS os nós"
    if not args.sim:
        resp = input(f"\nApagar {modo}? Digite 'sim' para confirmar: ").strip().lower()
        if resp != "sim":
            print("Cancelado.")
            return

    if args.apenas_fake:
        depois = limpar_apenas_fake(cliente)
        print("\nLimpeza de dados suspeitos concluída.")
    else:
        limpar_tudo(cliente)
        depois = contar_nos(cliente)
        print("\nLimpeza total concluída.")

    print("Estado após limpeza:")
    for label, qtd in depois.items():
        print(f"  :{label}  {qtd}")


if __name__ == "__main__":
    main()
