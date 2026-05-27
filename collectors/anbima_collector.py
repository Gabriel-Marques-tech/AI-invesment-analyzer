"""Placeholder para futura integração com a ANBIMA Data API.

Decisão de escopo (25/05/2026): a v1 do projeto usa apenas dados da CVM SRE.

Estado atual da API ANBIMA:
- Base: https://api.anbima.com.br/feed/precos-indices/v1/
- Cobre: CRI/CRA, Fundos v2 (RCVM 175, inclui FII), Títulos Públicos, Índices
- Exige autenticação OAuth/token via cadastro institucional em
  https://developers.anbima.com.br/
- Não disponível sem cadastro prévio.

Quando o BTG fornecer credenciais ANBIMA, basta:
1. Adicionar ANBIMA_CLIENT_ID e ANBIMA_CLIENT_SECRET no .env
2. Implementar `_obter_token()` (OAuth client credentials)
3. Implementar as funções de busca (cri_taxas, fii_dy, indicadores_macro)
4. Plugar no collector_agent como tool adicional
"""
import logging

logger = logging.getLogger(__name__)

DISPONIVEL = False


def buscar_taxas_cri(*args, **kwargs) -> list[dict]:
    logger.warning("anbima_collector.buscar_taxas_cri: integração ANBIMA não habilitada na v1.")
    return []


def buscar_fundos_fii(*args, **kwargs) -> list[dict]:
    logger.warning("anbima_collector.buscar_fundos_fii: integração ANBIMA não habilitada na v1.")
    return []


def buscar_indicadores_macro(*args, **kwargs) -> dict:
    logger.warning(
        "anbima_collector.buscar_indicadores_macro: integração ANBIMA não habilitada na v1."
    )
    return {}
