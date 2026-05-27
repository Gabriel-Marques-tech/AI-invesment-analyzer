import os
import logging
from typing import Any, Iterable, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable, AuthError

load_dotenv()
logger = logging.getLogger(__name__)


class Neo4jClient:
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.uri = uri or os.getenv("NEO4J_URI")
        self.user = user or os.getenv("NEO4J_USER")
        self.password = password or os.getenv("NEO4J_PASSWORD")

        if not all([self.uri, self.user, self.password]):
            raise ValueError(
                "Credenciais Neo4j ausentes. Defina NEO4J_URI, NEO4J_USER e NEO4J_PASSWORD no .env"
            )

        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=3600,
            )
        return self._driver

    def verificar_conexao(self) -> bool:
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 AS ok").single()
                return result is not None and result["ok"] == 1
        except (ServiceUnavailable, AuthError) as e:
            logger.error(f"Falha ao conectar no Neo4j: {e}")
            return False

    def session(self) -> Session:
        return self.driver.session()

    def executar_escrita(self, cypher: str, parametros: Optional[dict] = None) -> list[dict]:
        with self.driver.session() as session:
            result = session.run(cypher, parametros or {})
            return [record.data() for record in result]

    def executar_leitura(self, cypher: str, parametros: Optional[dict] = None) -> list[dict]:
        with self.driver.session() as session:
            result = session.execute_read(
                lambda tx: list(tx.run(cypher, parametros or {}))
            )
            return [record.data() for record in result]

    def executar_lote(self, cypher: str, lote_parametros: Iterable[dict]) -> int:
        total = 0
        with self.driver.session() as session:
            for params in lote_parametros:
                session.run(cypher, params)
                total += 1
        return total

    def fechar(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.fechar()


_cliente_singleton: Optional[Neo4jClient] = None


def get_client() -> Neo4jClient:
    global _cliente_singleton
    if _cliente_singleton is None:
        _cliente_singleton = Neo4jClient()
    return _cliente_singleton
