"""Coletor de ofertas públicas via CVM Dados Abertos.

Fonte: https://dados.cvm.gov.br/dataset/oferta-distrib (atualizado diariamente)

Decisão de arquitetura (26/05/2026):
- O portal SRE (`/sre-publico-cvm/rest/sitePublico/pesquisar/*`) está retornando
  500 em toda a área `/pesquisar/*`. Trocamos para o dataset público
  `oferta_resolucao_160.csv` (RCVM 160, modelo atual desde 2023).
- O CSV NÃO contém taxa final nem indexador da oferta — esse dado fica nos
  prospectos. Os campos `taxa_*` da Oferta no Neo4j ficam None por enquanto.
- Análises possíveis: volume, distribuidor, emissor, datas, status, regime.
"""
import io
import logging
import os
import time
import zipfile
from pathlib import Path
from typing import Iterator, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

URL_ZIP_OFERTAS = (
    "https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/oferta_distribuicao.zip"
)
CSV_RESOLUCAO_160 = "oferta_resolucao_160.csv"
CSV_DISTRIBUICAO = "oferta_distribuicao.csv"

CACHE_DIR = Path("/tmp/cvm_dados_abertos")
CACHE_ZIP = CACHE_DIR / "oferta_distribuicao.zip"
CACHE_TTL_SEGUNDOS = 6 * 3600  # 6 horas

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (BTG-Monitor-Imob/1.0)",
    "Accept": "application/zip, */*",
}

# Mapeamento Valor_Mobiliario (CVM) → tipo interno do nosso schema
MAP_VALOR_MOBILIARIO = {
    "Cotas de FII": "FII",
    "Cotas de FIAGRO - FII": "FII",
    "Certificados de Recebíveis Imobiliários": "CRI",
    "Certificados de Recebíveis": "CRI",
    "Certificados de Recebíveis do Agronegócio": "CRA",
    "Cotas de FIAGRO - CRA": "CRA",
    "Debêntures": "DEBENTURE",
    "Cotas de FIDC": "FIDC",
    "Cotas de FIP": "FIP",
    "Cotas de FIAGRO - FIDC": "FIDC",
    "Notas Comerciais": "NOTA_COMERCIAL",
    "Ações": "ACAO",
}

# Status considerados "em andamento" (oferta ativa no mercado)
STATUS_ATIVOS = {"Registro Concedido", "Aguardando Bookbuilding", "Oferta Suspensa"}

# Mapeamento Status_Requerimento (CVM) → status interno
MAP_STATUS = {
    "Registro Concedido": "EM_ANDAMENTO",
    "Aguardando Bookbuilding": "EM_ANDAMENTO",
    "Oferta Suspensa": "SUSPENSA",
    "Oferta Encerrada": "ENCERRADA",
    "Oferta Revogada": "REVOGADA",
    "Registro Caducado": "CADUCADA",
    "Requerimento Expirado": "EXPIRADA",
}

CATEGORIAS_PRIORITARIAS = ["FII", "CRI", "CRA"]


# ---------- Download e cache ----------

def _cache_valido() -> bool:
    if not CACHE_ZIP.exists():
        return False
    idade = time.time() - CACHE_ZIP.stat().st_mtime
    return idade < CACHE_TTL_SEGUNDOS


def baixar_zip(forcar: bool = False) -> Path:
    """Baixa o ZIP de ofertas; usa cache se fresco (<6h)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not forcar and _cache_valido():
        logger.info(f"Usando ZIP em cache: {CACHE_ZIP}")
        return CACHE_ZIP

    logger.info(f"Baixando {URL_ZIP_OFERTAS}...")
    resp = requests.get(URL_ZIP_OFERTAS, headers=HEADERS_HTTP, timeout=120, stream=True)
    resp.raise_for_status()
    tmp = CACHE_ZIP.with_suffix(".tmp")
    with tmp.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
    tmp.replace(CACHE_ZIP)
    logger.info(f"ZIP salvo em {CACHE_ZIP} ({CACHE_ZIP.stat().st_size / 1024:.0f} KB)")
    return CACHE_ZIP


def _ler_csv_do_zip(nome_csv: str) -> pd.DataFrame:
    caminho = baixar_zip()
    with zipfile.ZipFile(caminho) as zf:
        with zf.open(nome_csv) as f:
            return pd.read_csv(f, sep=";", encoding="latin-1", low_memory=False)


# ---------- Leitura e filtro ----------

def carregar_ofertas_rcvm160(somente_ativas: bool = True) -> pd.DataFrame:
    """Carrega o CSV principal (RCVM 160, modelo atual desde 2023)."""
    df = _ler_csv_do_zip(CSV_RESOLUCAO_160)
    if somente_ativas:
        df = df[df["Status_Requerimento"].isin(STATUS_ATIVOS)].copy()
    return df


def filtrar_por_categoria(df: pd.DataFrame, categoria: str) -> pd.DataFrame:
    """Filtra um DataFrame pela categoria interna (FII, CRI, CRA, etc.)."""
    cat = categoria.upper().strip()
    valores_cvm = [k for k, v in MAP_VALOR_MOBILIARIO.items() if v == cat]
    if not valores_cvm:
        return df.iloc[0:0]
    return df[df["Valor_Mobiliario"].isin(valores_cvm)].copy()


# ---------- Mapeamento → schema Neo4j ----------

def _categoria_interna(valor_mobiliario: Optional[str]) -> Optional[str]:
    if not valor_mobiliario or pd.isna(valor_mobiliario):
        return None
    return MAP_VALOR_MOBILIARIO.get(valor_mobiliario, valor_mobiliario.upper())


def _data_iso(valor) -> Optional[str]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    s = str(valor).strip()
    if not s or s.lower() in ("nat", "nan"):
        return None
    # CSV vem como "2026-05-25" — já ISO
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # Fallback "dd/mm/yyyy"
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
    return None


def _to_float(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_str(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def mapear_oferta(row: pd.Series) -> dict:
    """Converte uma linha do oferta_resolucao_160.csv para o dict do upsert_oferta."""
    tipo = _categoria_interna(_safe_str(row.get("Valor_Mobiliario")))
    status_cvm = _safe_str(row.get("Status_Requerimento"))

    # Para ofertas em "Aguardando Bookbuilding", Data_Registro e Valor_Total ainda
    # não foram preenchidos pela CVM — caímos no Data_requerimento como fallback.
    data_registro = _data_iso(row.get("Data_Registro")) or _data_iso(row.get("Data_requerimento"))
    volume = _to_float(row.get("Valor_Total_Registrado"))
    if not volume:
        volume = None  # 0.0 vira None — significa "ainda não definido pelo bookbuilding"

    return {
        "id_requerimento": str(int(row["Numero_Requerimento"]))
            if not pd.isna(row.get("Numero_Requerimento")) else None,
        "numero_registro": _safe_str(row.get("Numero_Processo")),
        "tipo": tipo,
        "status": MAP_STATUS.get(status_cvm or "", status_cvm),
        "nome_emissor": _safe_str(row.get("Nome_Emissor")),
        "volume_total": volume,
        "data_registro": data_registro,
        "data_encerramento": _data_iso(row.get("Data_Encerramento")),
        # campos extras (informativos; o upsert ignora os que não conhece)
        "tipo_requerimento": _safe_str(row.get("Tipo_requerimento")),
        "regime_distribuicao": _safe_str(row.get("Regime_distribuicao")),
        "publico_alvo": _safe_str(row.get("Publico_alvo")),
        "mercado_negociacao": _safe_str(row.get("Mercado_negociacao")),
        # relações
        "_emissor_cnpj": _safe_str(row.get("CNPJ_Emissor")),
        "_emissor_nome": _safe_str(row.get("Nome_Emissor")),
        "_lider_nome": _safe_str(row.get("Nome_Lider")),
        "_lider_cnpj": _safe_str(row.get("CNPJ_Lider")),
        "_administrador": _safe_str(row.get("Administrador")),
        "_gestor": _safe_str(row.get("Gestor")),
    }


# ---------- Persistência no Neo4j ----------

def sincronizar_grafo(
    categorias: Optional[list[str]] = None,
    limite: Optional[int] = None,
    forcar_download: bool = False,
    fechar_conexao_no_fim: bool = True,
) -> dict:
    """Baixa o CSV, filtra ofertas ativas das categorias prioritárias e persiste no Neo4j.

    Retorna estatísticas de inserção por categoria.
    """
    import time
    from graph import queries  # import tardio para evitar ciclo
    from graph.neo4j_client import get_client

    if forcar_download:
        baixar_zip(forcar=True)

    categorias = categorias or CATEGORIAS_PRIORITARIAS
    df = carregar_ofertas_rcvm160(somente_ativas=True)
    logger.info(f"Total de ofertas ativas no CSV: {len(df)}")

    stats: dict[str, int] = {c: 0 for c in categorias}
    erros = 0
    processadas = 0
    t_inicio = time.time()

    for cat in categorias:
        sub = filtrar_por_categoria(df, cat)
        if limite:
            sub = sub.head(limite)
        logger.info(f"[{cat}] {len(sub)} ofertas para processar")
        for _, row in sub.iterrows():
            try:
                dados = mapear_oferta(row)
                if not dados.get("id_requerimento"):
                    continue
                queries.upsert_oferta(dados)
                if dados.get("_emissor_cnpj") and dados.get("_emissor_nome"):
                    queries.upsert_emissor(
                        cnpj=dados["_emissor_cnpj"], nome=dados["_emissor_nome"]
                    )
                    queries.relacionar_emissor_oferta(
                        cnpj=dados["_emissor_cnpj"],
                        id_requerimento=dados["id_requerimento"],
                    )
                if dados.get("_lider_nome"):
                    queries.upsert_banco(dados["_lider_nome"], tipo="COORDENADOR_LIDER")
                    queries.relacionar_banco_oferta(
                        banco_nome=dados["_lider_nome"],
                        id_requerimento=dados["id_requerimento"],
                        papel="COORDENADOR_LIDER",
                    )
                stats[cat] += 1
                processadas += 1
                if processadas % 25 == 0:
                    elapsed = time.time() - t_inicio
                    rps = processadas / elapsed if elapsed else 0
                    logger.info(
                        f"  progresso: {processadas} ofertas | "
                        f"{elapsed:.0f}s | {rps:.1f} ofertas/s"
                    )
            except Exception as e:
                erros += 1
                logger.warning(f"Falha ao persistir oferta {row.get('Numero_Requerimento')}: {e}")

    total_t = time.time() - t_inicio
    logger.info(
        f"Sincronização concluída em {total_t:.1f}s: {stats}, erros={erros}"
    )

    if fechar_conexao_no_fim:
        try:
            get_client().fechar()
            logger.info("Conexão Neo4j fechada.")
        except Exception as e:
            logger.warning(f"Erro ao fechar conexão Neo4j: {e}")

    return {
        "inseridos_por_categoria": stats,
        "erros": erros,
        "total_ativas_csv": len(df),
        "tempo_segundos": round(total_t, 1),
    }


# ---------- Iteradores convenientes ----------

def listar_ofertas_ativas(
    categoria: Optional[str] = None, limite: int = 50
) -> list[dict]:
    """Retorna as ofertas ativas (sem persistir) como lista de dicts já mapeados.

    Útil para o agente conferir o que existe antes de chamar sincronizar_grafo.
    """
    df = carregar_ofertas_rcvm160(somente_ativas=True)
    if categoria:
        df = filtrar_por_categoria(df, categoria)
    df = df.sort_values("Data_Registro", ascending=False).head(limite)
    return [mapear_oferta(r) for _, r in df.iterrows()]


def buscar_detalhes_oferta(id_requerimento: str | int) -> Optional[dict]:
    """Recupera uma oferta específica do CSV pelo Numero_Requerimento."""
    df = carregar_ofertas_rcvm160(somente_ativas=False)
    try:
        alvo = df[df["Numero_Requerimento"] == int(id_requerimento)]
    except (ValueError, TypeError):
        return None
    if alvo.empty:
        return None
    return mapear_oferta(alvo.iloc[0])


def diagnosticar() -> dict:
    """Smoke test: confirma que o download funciona e mostra contagens por categoria."""
    out: dict = {}
    try:
        path = baixar_zip()
        out["zip_disponivel"] = True
        out["zip_tamanho_kb"] = round(path.stat().st_size / 1024, 1)
    except Exception as e:
        return {"zip_disponivel": False, "erro": str(e)}

    try:
        df = carregar_ofertas_rcvm160(somente_ativas=True)
        out["total_ativas"] = len(df)
        out["por_categoria"] = {
            cat: int(filtrar_por_categoria(df, cat).shape[0])
            for cat in CATEGORIAS_PRIORITARIAS
        }
    except Exception as e:
        out["erro_leitura"] = str(e)
    return out


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(diagnosticar(), indent=2, ensure_ascii=False))
