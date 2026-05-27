"""Parser de prospectos PDF de ofertas FII — extrai fees e preço de emissão.

Pipeline:
1. Lista documentos da oferta via SRE (`/documentosPublicados/{id}` — esse endpoint
   continua funcionando mesmo com `/pesquisar/*` fora).
2. Identifica o "Prospecto Definitivo" e baixa via `/rest/download/{uuid}`.
3. Extrai texto com pypdf (Python puro, sem deps nativas).
4. Aplica regex calibrado para os padrões típicos de prospectos FII brasileiros.

Campos extraídos:
- comissao_coord_distr_valor     (R$ pago aos coordenadores/distribuidores)
- comissao_coord_distr_pct       (% sobre montante total da oferta)
- custo_total_oferta_valor       (R$, soma de todos os custos)
- custo_total_oferta_pct         (% sobre montante)
- preco_emissao_cota             (R$ por cota nova)
- custo_unitario_distribuicao    (R$ por cota, parte do preço que vai para fees)
"""
import logging
import re
import time
from pathlib import Path
from typing import Optional

import pypdf
import requests

logger = logging.getLogger(__name__)

URL_DOCS = (
    "https://web.cvm.gov.br/sre-publico-cvm/rest/sitePublico/pesquisar/documentosPublicados"
)
URL_DOWNLOAD = "https://web.cvm.gov.br/sre-publico-cvm/rest/download"

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (BTG-Monitor-Imob/1.0)",
    "Accept": "application/json, application/pdf, */*",
    "Referer": "https://web.cvm.gov.br/sre-publico-cvm/",
    "Origin": "https://web.cvm.gov.br",
}

CACHE_DIR = Path("/tmp/cvm_pdfs")
CACHE_TTL_SEGUNDOS = 30 * 24 * 3600  # 30 dias — prospectos não mudam após registro


# ---------- Download do prospecto ----------

def listar_documentos(id_requerimento: int | str) -> list[dict]:
    """Retorna a lista de documentos publicados de uma oferta."""
    r = requests.get(
        f"{URL_DOCS}/{id_requerimento}", headers=HEADERS_HTTP, timeout=20
    )
    r.raise_for_status()
    return r.json()


def encontrar_prospecto(documentos: list[dict]) -> Optional[dict]:
    """Retorna o documento 'Prospecto Definitivo' (preferido) ou o primeiro prospecto disponível."""
    if not documentos:
        return None
    preferencias = [
        lambda d: d.get("nome", "").lower() == "prospecto definitivo",
        lambda d: "prospecto" in d.get("nome", "").lower() and "definitivo" in d.get("nome", "").lower(),
        lambda d: "prospecto" in d.get("nome", "").lower(),
    ]
    for pref in preferencias:
        match = next((d for d in documentos if pref(d)), None)
        if match:
            return match
    return None


def baixar_pdf(uuid: str, id_requerimento: int | str) -> Path:
    """Baixa o PDF e cacheia em disco por 30 dias. Retorna o caminho local."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    caminho = CACHE_DIR / f"prospecto_{id_requerimento}.pdf"

    if caminho.exists():
        idade = time.time() - caminho.stat().st_mtime
        if idade < CACHE_TTL_SEGUNDOS:
            return caminho

    r = requests.get(
        f"{URL_DOWNLOAD}/{uuid}", headers=HEADERS_HTTP, timeout=120, stream=True
    )
    r.raise_for_status()
    tmp = caminho.with_suffix(".tmp")
    with tmp.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
    tmp.replace(caminho)
    logger.info(f"PDF salvo em {caminho} ({caminho.stat().st_size / 1024:.0f} KB)")
    return caminho


# ---------- Extração de texto ----------

def extrair_texto(pdf_path: Path, max_paginas: Optional[int] = 80) -> str:
    """Extrai texto do PDF. Limita por padrão a 80 páginas (fees ficam no início)."""
    reader = pypdf.PdfReader(str(pdf_path))
    n = len(reader.pages) if max_paginas is None else min(len(reader.pages), max_paginas)
    return "\n".join((reader.pages[i].extract_text() or "") for i in range(n))


# ---------- Parsing de fees ----------

# Formato típico no prospecto:
#   Comissão de Coordenação e Distribuição(2) (3) 2.100.000,00 0,700%
# (o "(2) (3)" entre o nome e o valor é nota de rodapé — precisa aceitar dígitos)
RE_COMISSAO = re.compile(
    r"Comiss[ãa]o\s+de\s+Coordena[çc][ãa]o\s+e\s+Distribui[çc][ãa]o"
    r"[^\n]{0,80}?"                       # nota de rodapé tipo "(2)(3)"
    r"R?\$?\s*(\d[\d.]*,\d{2})"           # valor R$ no padrão BR: 2.100.000,00
    r"\s+"
    r"(\d+[,.]?\d*)\s*%",                 # percentual: 0,700 ou 0.700
    re.IGNORECASE,
)

# Linha "Total ... R$ ... %" — buscamos só depois da Comissão, dentro da mesma tabela
RE_TOTAL_CUSTO = re.compile(
    r"\bTotal\s+(\d[\d.]*,\d{2})\s+(\d+[,.]?\d*)\s*%",
    re.IGNORECASE,
)

# "Preço de Emissão" — 2 padrões comuns:
#  (a) "Preço de Emissão de R$ 100,00"
#  (b) "R$ 100,00 ... ('Preço de Emissão')"  ← muito comum em prospectos
RE_PRECO_EMISSAO_A = re.compile(
    r"Pre[çc]o\s+de\s+Emiss[ãa]o"
    r"[^\n]{0,80}?R\$?\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
RE_PRECO_EMISSAO_B = re.compile(
    r"R\$?\s*(\d+(?:[.,]\d+)?)\s*"        # valor
    r"(?:\([^)]{0,40}\)\s*)?"             # parênteses opcionais com extenso
    r"(?:por\s+Cota[^\n]{0,40})?"
    r"\([\"“”']Pre[çc]o\s+de\s+Emiss[ãa]o[\"“”']\)",
    re.IGNORECASE,
)

# "Custo Unitário de Distribuição: R$ 0,80" — também tolera dígitos no meio (notas de rodapé)
RE_CUSTO_UNITARIO = re.compile(
    r"Custo\s+Unit[áa]rio\s+de\s+Distribui[çc][ãa]o"
    r"[^\n]{0,80}?R\$?\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _parse_numero_br(s: str) -> Optional[float]:
    """'2.100.000,00' → 2100000.0; '0,700' → 0.7. Tolerante a falhas."""
    if not s:
        return None
    s = s.strip().replace(" ", "")
    # Se tem ',' como separador decimal e '.' como milhar → padrão BR
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extrair_fees(texto: str) -> dict:
    """Aplica os regex no texto e retorna um dict com os campos extraídos (None se ausente)."""
    out: dict[str, Optional[float]] = {
        "comissao_coord_distr_valor": None,
        "comissao_coord_distr_pct": None,
        "custo_total_oferta_valor": None,
        "custo_total_oferta_pct": None,
        "preco_emissao_cota": None,
        "custo_unitario_distribuicao": None,
    }

    if m := RE_COMISSAO.search(texto):
        out["comissao_coord_distr_valor"] = _parse_numero_br(m.group(1))
        out["comissao_coord_distr_pct"] = _parse_numero_br(m.group(2))

    # Procura "Total" só APÓS a comissão para não pegar outros totais do PDF
    if out["comissao_coord_distr_valor"] is not None and (m := RE_COMISSAO.search(texto)):
        sub = texto[m.end(): m.end() + 1500]
        if mt := RE_TOTAL_CUSTO.search(sub):
            out["custo_total_oferta_valor"] = _parse_numero_br(mt.group(1))
            out["custo_total_oferta_pct"] = _parse_numero_br(mt.group(2))

    # Tenta os 2 padrões; B (com parênteses) é mais confiável quando existe
    m = RE_PRECO_EMISSAO_B.search(texto) or RE_PRECO_EMISSAO_A.search(texto)
    if m:
        out["preco_emissao_cota"] = _parse_numero_br(m.group(1))

    if m := RE_CUSTO_UNITARIO.search(texto):
        out["custo_unitario_distribuicao"] = _parse_numero_br(m.group(1))

    return out


# ---------- Orquestração ----------

def extrair_fees_oferta(id_requerimento: int | str) -> dict:
    """End-to-end: busca documentos, baixa prospecto, extrai fees.

    Retorna o dict de fees + metadados (status, nome_documento). Campos None
    indicam que aquele padrão não foi encontrado neste prospecto.
    """
    try:
        docs = listar_documentos(id_requerimento)
    except requests.HTTPError as e:
        return {"erro": f"falha ao listar documentos: {e}"}

    prospecto = encontrar_prospecto(docs)
    if not prospecto:
        return {"erro": "nenhum prospecto encontrado para esta oferta"}

    try:
        pdf_path = baixar_pdf(prospecto["valor"], id_requerimento)
    except Exception as e:
        return {"erro": f"falha ao baixar PDF: {e}"}

    try:
        texto = extrair_texto(pdf_path)
    except Exception as e:
        return {"erro": f"falha ao extrair texto: {e}"}

    fees = extrair_fees(texto)
    fees["_documento"] = prospecto.get("nome")
    fees["_data_documento"] = prospecto.get("data")
    fees["_paginas_lidas"] = 80  # max_paginas default
    return fees


def enriquecer_ofertas_fii_com_fees(
    limite: Optional[int] = None,
    somente_sem_fees: bool = True,
    fechar_conexao_no_fim: bool = True,
) -> dict:
    """Para cada Oferta FII em andamento no grafo, baixa o prospecto, extrai fees
    e faz upsert. Retorna estatísticas de sucesso/falha.

    Args:
        limite: máximo de ofertas a processar (None = todas).
        somente_sem_fees: se True, pula ofertas que já têm `comissao_coord_distr_pct`
            no grafo (idempotência sem retrabalho).
    """
    import time
    from graph import queries
    from graph.neo4j_client import get_client

    where_extra = "AND o.comissao_coord_distr_pct IS NULL" if somente_sem_fees else ""
    cypher = f"""
    MATCH (o:Oferta)
    WHERE o.tipo = 'FII' AND o.status = 'EM_ANDAMENTO' {where_extra}
    RETURN o.id_requerimento AS id
    ORDER BY o.data_registro DESC
    """
    if limite:
        cypher += f" LIMIT {int(limite)}"

    ids = [r["id"] for r in get_client().executar_leitura(cypher)]
    logger.info(f"Vai processar prospectos de {len(ids)} ofertas FII")

    stats = {"sucesso_total": 0, "sucesso_parcial": 0, "sem_prospecto": 0, "erro": 0}
    t_inicio = time.time()

    for i, id_req in enumerate(ids, 1):
        fees = extrair_fees_oferta(id_req)
        if "erro" in fees:
            stats["sem_prospecto" if "nenhum prospecto" in fees["erro"] else "erro"] += 1
            if i % 5 == 0:
                logger.info(f"  progresso: {i}/{len(ids)} ofertas processadas")
            continue
        # Considera sucesso total se pegou comissão E preço
        if fees.get("comissao_coord_distr_pct") and fees.get("preco_emissao_cota"):
            stats["sucesso_total"] += 1
        elif any(v is not None for k, v in fees.items() if not k.startswith("_")):
            stats["sucesso_parcial"] += 1
        else:
            stats["sem_prospecto"] += 1
            continue

        # Faz upsert apenas com os campos extraídos
        dados_oferta = {k: v for k, v in fees.items() if not k.startswith("_")}
        dados_oferta["id_requerimento"] = str(id_req)
        try:
            queries.upsert_oferta(dados_oferta)
        except Exception as e:
            logger.warning(f"upsert falhou para {id_req}: {e}")
            stats["erro"] += 1

        if i % 5 == 0:
            elapsed = time.time() - t_inicio
            logger.info(
                f"  progresso: {i}/{len(ids)} | {elapsed:.0f}s | "
                f"total={stats['sucesso_total']} parcial={stats['sucesso_parcial']} "
                f"sem_pdf={stats['sem_prospecto']} erro={stats['erro']}"
            )

    total_t = time.time() - t_inicio
    logger.info(f"Fees concluído em {total_t:.1f}s: {stats}")
    stats["tempo_segundos"] = round(total_t, 1)

    if fechar_conexao_no_fim:
        try:
            get_client().fechar()
            logger.info("Conexão Neo4j fechada.")
        except Exception as e:
            logger.warning(f"Erro ao fechar conexão Neo4j: {e}")

    return stats


def diagnosticar(id_requerimento: int | str = 26401) -> dict:
    """Smoke test: roda extração em uma oferta conhecida (BRC Renda Corporativa)."""
    return extrair_fees_oferta(id_requerimento)


if __name__ == "__main__":
    import json, sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arg = sys.argv[1] if len(sys.argv) > 1 else 26401
    print(json.dumps(diagnosticar(arg), indent=2, ensure_ascii=False))
