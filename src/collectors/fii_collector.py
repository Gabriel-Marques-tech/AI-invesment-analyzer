"""Coletor de dados financeiros mensais de FIIs.

Fonte: https://dados.cvm.gov.br/dataset/fii-doc-inf_mensal
Anexo 39-I da Instrução CVM 571/2015 — Informe Mensal Estruturado.

O ZIP contém 3 CSVs por ano:
- inf_mensal_fii_geral_{ano}.csv          — cadastro (nome, CNPJ, segmento, administrador)
- inf_mensal_fii_complemento_{ano}.csv    — números financeiros (PL, VP/C, DY, cotistas, taxa adm)
- inf_mensal_fii_ativo_passivo_{ano}.csv  — composição da carteira (imóveis, CRI, ações)

Os 3 CSVs são unidos por (CNPJ_Fundo_Classe, Data_Referencia, Versao).
"""
import io
import logging
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

URL_BASE = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS"
CACHE_DIR = Path("/tmp/cvm_fii_inf_mensal")
CACHE_TTL_SEGUNDOS = 6 * 3600

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (BTG-Monitor-Imob/1.0)",
    "Accept": "application/zip, */*",
}

# Limiares para classificar tipo do FII pela composição da carteira
LIMIAR_TIPO_PURO = 0.70   # > 70% → tipo "puro"; senão híbrido


def _ano_default() -> int:
    """Retorna o ano com dados mais recentes (CVM publica com lag de alguns meses)."""
    hoje = datetime.now()
    # No início do ano os dados do ano anterior ainda são os mais ricos
    return hoje.year - 1 if hoje.month <= 3 else hoje.year - 1


def _path_zip(ano: int) -> Path:
    return CACHE_DIR / f"inf_mensal_fii_{ano}.zip"


def _cache_valido(path: Path) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < CACHE_TTL_SEGUNDOS


def baixar_zip(ano: Optional[int] = None, forcar: bool = False) -> Path:
    """Baixa o ZIP do ano informado; usa cache se fresco (<6h).

    Se o ano não vier, usa o último ano com dados típicos (ano corrente - 1).
    Em caso de 404, tenta automaticamente o ano anterior.
    """
    ano = ano or _ano_default()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for tentativa_ano in (ano, ano - 1):
        path = _path_zip(tentativa_ano)
        if not forcar and _cache_valido(path):
            logger.info(f"Usando ZIP em cache: {path}")
            return path
        url = f"{URL_BASE}/inf_mensal_fii_{tentativa_ano}.zip"
        logger.info(f"Baixando {url}...")
        resp = requests.get(url, headers=HEADERS_HTTP, timeout=180, stream=True)
        if resp.status_code == 404:
            logger.warning(f"Ano {tentativa_ano} não disponível, tentando anterior...")
            continue
        resp.raise_for_status()
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
        tmp.replace(path)
        logger.info(f"ZIP salvo em {path} ({path.stat().st_size / 1024:.0f} KB)")
        return path

    raise RuntimeError(f"Nenhum ZIP de FII encontrado para {ano} ou {ano-1}")


def _ler_csv_do_zip(zip_path: Path, nome_arquivo: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        # O nome real pode ser inf_mensal_fii_geral_2025.csv etc.
        candidatos = [n for n in zf.namelist() if nome_arquivo in n]
        if not candidatos:
            raise FileNotFoundError(f"{nome_arquivo} não encontrado em {zip_path.name}")
        with zf.open(candidatos[0]) as f:
            return pd.read_csv(f, sep=";", encoding="latin-1", low_memory=False)


def carregar_snapshot_atual(ano: Optional[int] = None) -> pd.DataFrame:
    """Carrega os 3 CSVs, junta-os e mantém só a Data_Referencia mais recente de cada FII.

    Retorna DataFrame com 1 linha por CNPJ_Fundo_Classe (o estado atual de cada FII).
    """
    zip_path = baixar_zip(ano=ano)

    df_geral = _ler_csv_do_zip(zip_path, "geral")
    df_comp  = _ler_csv_do_zip(zip_path, "complemento")
    df_ap    = _ler_csv_do_zip(zip_path, "ativo_passivo")

    # Mantém só a Data_Referencia mais recente de cada FII
    df_geral = df_geral.sort_values("Data_Referencia").drop_duplicates(
        "CNPJ_Fundo_Classe", keep="last"
    )
    df_comp = df_comp.sort_values("Data_Referencia").drop_duplicates(
        "CNPJ_Fundo_Classe", keep="last"
    )
    df_ap = df_ap.sort_values("Data_Referencia").drop_duplicates(
        "CNPJ_Fundo_Classe", keep="last"
    )

    # Merge dos 3 por CNPJ
    df = df_geral.merge(df_comp, on="CNPJ_Fundo_Classe", how="left",
                        suffixes=("", "_comp"))
    df = df.merge(df_ap, on="CNPJ_Fundo_Classe", how="left",
                  suffixes=("", "_ap"))
    logger.info(f"Snapshot consolidado: {len(df)} FIIs")
    return df


# ---------- Classificação de Tipo (Tijolo / Papel / Híbrido / FoF) ----------

COLUNAS_IMOVEIS = [
    "Direitos_Bens_Imoveis", "Terrenos", "Imoveis_Renda_Acabados",
    "Imoveis_Renda_Construcao", "Imoveis_Venda_Acabados", "Imoveis_Venda_Construcao",
]
COLUNAS_PAPEL = [
    "CRI", "CRI_CRA", "Letras_Hipotecarias", "LCI", "LCI_LCA", "LIG",
    "Cedulas_Debentures", "Debentures",
]
COLUNAS_COTAS_FUNDOS = ["FII", "FIP", "Fundo_Acoes", "Outras_Cotas_FI"]


def _soma_seguro(row: pd.Series, colunas: list[str]) -> float:
    total = 0.0
    for c in colunas:
        v = row.get(c)
        if v is not None and not pd.isna(v):
            try:
                total += float(v)
            except (ValueError, TypeError):
                pass
    return total


def inferir_tipo_fii(row: pd.Series) -> Optional[str]:
    """Classifica FII em Tijolo, Papel, Hibrido, FoF baseado na composição do ativo."""
    imoveis = _soma_seguro(row, COLUNAS_IMOVEIS)
    papel   = _soma_seguro(row, COLUNAS_PAPEL)
    cotas   = _soma_seguro(row, COLUNAS_COTAS_FUNDOS)
    total = imoveis + papel + cotas
    if total <= 0:
        return None
    if cotas / total > LIMIAR_TIPO_PURO:
        return "FoF"
    if imoveis / total > LIMIAR_TIPO_PURO:
        return "Tijolo"
    if papel / total > LIMIAR_TIPO_PURO:
        return "Papel"
    return "Hibrido"


# ---------- Mapeamento para upsert_fundo_fii ----------

def _safe_float(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v) -> Optional[int]:
    f = _safe_float(v)
    return int(f) if f is not None else None


def _safe_str(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def mapear_fundo_fii(row: pd.Series) -> dict:
    """Converte uma linha do snapshot consolidado para o dict do upsert_fundo_fii.

    Como não temos preço de mercado (B3), p_vp fica None.
    Como não temos vacância no mensal, fica None (vacância está no trimestral).
    """
    cnpj = _safe_str(row.get("CNPJ_Fundo_Classe"))
    # Usamos o CNPJ como ticker provisório (chave única do schema atual).
    # Pode ser substituído por ticker B3 numa onda futura.
    ticker_provisorio = cnpj.replace(".", "").replace("/", "").replace("-", "") if cnpj else None
    rentab_mes = _safe_float(row.get("Percentual_Rentabilidade_Efetiva_Mes"))
    vp_cota = _safe_float(row.get("Valor_Patrimonial_Cotas"))
    return {
        "ticker": ticker_provisorio,
        "cnpj": cnpj,
        "nome": _safe_str(row.get("Nome_Fundo_Classe")),
        "tipo": inferir_tipo_fii(row),
        "preco_cota": None,
        "vp_cota": vp_cota,
        "p_vp": None,
        "patrimonio_liquido": _safe_float(row.get("Patrimonio_Liquido")),
        "dy_12m": None,
        "rendimento_cota_mes": (
            rentab_mes * vp_cota if (rentab_mes is not None and vp_cota is not None) else None
        ),
        "vacancia_fisica": None,
        "vacancia_financeira": None,
        "num_imoveis": None,
        "taxa_administracao": _safe_float(row.get("Percentual_Despesas_Taxa_Administracao")),
        "taxa_gestao": None,
        "liquidez_media_diaria": None,
        "num_cotistas": _safe_int(row.get("Total_Numero_Cotistas")),
        "_segmento": _safe_str(row.get("Segmento_Atuacao")),
        "_mandato": _safe_str(row.get("Mandato")),
        "_administrador": _safe_str(row.get("Nome_Administrador")),
        "_isin": _safe_str(row.get("Codigo_ISIN")),
    }


# ---------- Sincronização no Neo4j ----------

def sincronizar_grafo(
    ano: Optional[int] = None,
    limite: Optional[int] = None,
    forcar_download: bool = False,
    fechar_conexao_no_fim: bool = True,
) -> dict:
    """Lê o informe mensal, classifica cada FII e persiste no Neo4j.

    Vincula cada :FundoFII com a(s) :Oferta(s) que têm o mesmo CNPJ no emissor.
    """
    import time
    from graph import queries  # import tardio para evitar ciclo
    from graph.neo4j_client import get_client

    if forcar_download:
        baixar_zip(ano=ano, forcar=True)

    df = carregar_snapshot_atual(ano=ano)
    if limite:
        df = df.head(limite)

    inseridos = 0
    relacionados = 0
    erros = 0
    t_inicio = time.time()

    for _, row in df.iterrows():
        try:
            dados = mapear_fundo_fii(row)
            if not dados.get("cnpj") or not dados.get("ticker"):
                continue
            queries.upsert_fundo_fii(dados)
            inseridos += 1
            # Relaciona com ofertas já no grafo que têm esse CNPJ no emissor
            cnpj_oferta = dados["cnpj"]
            res = get_client().executar_escrita(
                """
                MATCH (e:Emissor {cnpj: $cnpj})-[:EMITIU]->(o:Oferta)
                MATCH (f:FundoFII {ticker: $ticker})
                MERGE (o)-[:EMITIDA_POR]->(f)
                RETURN count(o) AS qtd
                """,
                {"cnpj": cnpj_oferta, "ticker": dados["ticker"]},
            )
            if res:
                relacionados += res[0]["qtd"]
            if inseridos % 50 == 0:
                elapsed = time.time() - t_inicio
                rps = inseridos / elapsed if elapsed else 0
                logger.info(
                    f"  progresso: {inseridos} FIIs | {elapsed:.0f}s | {rps:.1f} FIIs/s"
                )
        except Exception as e:
            erros += 1
            logger.warning(f"Falha em {row.get('CNPJ_Fundo_Classe')}: {e}")

    total_t = time.time() - t_inicio
    logger.info(
        f"FIIs concluído em {total_t:.1f}s: inseridos={inseridos}, "
        f"relacionamentos={relacionados}, erros={erros}"
    )

    if fechar_conexao_no_fim:
        try:
            get_client().fechar()
            logger.info("Conexão Neo4j fechada.")
        except Exception as e:
            logger.warning(f"Erro ao fechar conexão Neo4j: {e}")

    return {
        "fundos_fii_inseridos": inseridos,
        "relacionamentos_oferta_fundo": relacionados,
        "erros": erros,
        "total_csv": len(df),
        "tempo_segundos": round(total_t, 1),
    }


def diagnosticar(ano: Optional[int] = None) -> dict:
    """Smoke test: baixa, lê e mostra contagens."""
    out: dict = {}
    try:
        path = baixar_zip(ano=ano)
        out["zip_disponivel"] = True
        out["zip_tamanho_kb"] = round(path.stat().st_size / 1024, 1)
        df = carregar_snapshot_atual(ano=ano)
        out["total_fiis"] = len(df)
        if "Segmento_Atuacao" in df.columns:
            top_seg = df["Segmento_Atuacao"].value_counts().head(5).to_dict()
            out["top_segmentos"] = top_seg
        # Distribuição inferida de tipos
        tipos = df.apply(inferir_tipo_fii, axis=1).value_counts(dropna=False).to_dict()
        out["distribuicao_tipos"] = {str(k): int(v) for k, v in tipos.items()}
    except Exception as e:
        out["erro"] = str(e)
    return out


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(diagnosticar(), indent=2, ensure_ascii=False))
