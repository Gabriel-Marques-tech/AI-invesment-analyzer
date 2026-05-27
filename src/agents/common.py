"""LLM compartilhado e helper de loop ReAct para os agentes do supervisor."""
import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_groq import ChatGroq

load_dotenv()
logger = logging.getLogger(__name__)

MODELO_GROQ = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
TEMPERATURA_PADRAO = float(os.getenv("GROQ_TEMPERATURE", "0.1"))
MAX_ITERACOES_REACT = 6
MAX_RETRIES_TOOL_CALL_INVALIDO = 2


def construir_llm(temperature: Optional[float] = None) -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY ausente no .env")
    return ChatGroq(
        model=MODELO_GROQ,
        temperature=TEMPERATURA_PADRAO if temperature is None else temperature,
        api_key=api_key,
    )


def _eh_erro_tool_call_invalido(exc: Exception) -> bool:
    """Detecta o erro 'Failed to call a function' do Groq quando o Llama gera
    tool call em formato não padronizado (ex: '<function=name{...}>')."""
    s = str(exc).lower()
    return (
        "failed to call a function" in s
        or "tool_use_failed" in s
        or "failed_generation" in s
    )


def _invoke_com_retry(llm_com_tools, historico, tentativa_atual=0):
    """Chama o LLM tolerando erros de formato de tool call do Groq.
    Se o LLM gera <function=...> em vez de JSON estruturado, faz retry com
    instrução explícita pra usar JSON."""
    try:
        return llm_com_tools.invoke(historico)
    except Exception as e:
        if not _eh_erro_tool_call_invalido(e):
            raise
        if tentativa_atual >= MAX_RETRIES_TOOL_CALL_INVALIDO:
            logger.error(f"Esgotadas retries de tool call inválido. Último erro: {e}")
            raise
        logger.warning(
            f"Groq rejeitou tool call (tentativa {tentativa_atual + 1}). "
            f"Adicionando hint e tentando de novo."
        )
        # Adiciona dica no histórico e tenta de novo
        historico_corrigido = historico + [HumanMessage(
            content=(
                "Sua última chamada de função usou formato inválido. "
                "Use o formato JSON padrão de tool_calls do Groq. "
                "Se a pergunta puder ser respondida sem chamar tool, responda diretamente em texto."
            )
        )]
        time.sleep(0.5)
        return _invoke_com_retry(llm_com_tools, historico_corrigido, tentativa_atual + 1)


def loop_react(
    llm: ChatGroq,
    tools: list,
    system_prompt: str,
    mensagens_entrada: list[BaseMessage],
    max_iteracoes: int = MAX_ITERACOES_REACT,
) -> list[BaseMessage]:
    """Loop ReAct mínimo: pede LLM, se houver tool_calls executa, repete até parar."""
    tools_por_nome = {t.name: t for t in tools}
    llm_com_tools = llm.bind_tools(tools)

    historico: list[BaseMessage] = [SystemMessage(content=system_prompt), *mensagens_entrada]
    geradas: list[BaseMessage] = []

    for iteracao in range(max_iteracoes):
        try:
            resposta = _invoke_com_retry(llm_com_tools, historico)
        except Exception as e:
            logger.error(f"loop_react: invoke falhou definitivamente — {e}")
            fallback = AIMessage(
                content=(
                    "Desculpe, não consegui processar essa pergunta no momento. "
                    "Tente reformular ou fazer uma pergunta mais específica "
                    "(ex: 'qual o volume total das ofertas FII em andamento?')."
                )
            )
            geradas.append(fallback)
            return geradas

        historico.append(resposta)
        geradas.append(resposta)

        if not isinstance(resposta, AIMessage) or not resposta.tool_calls:
            break

        for tc in resposta.tool_calls:
            nome = tc["name"]
            args = tc.get("args", {})
            tool = tools_por_nome.get(nome)
            if tool is None:
                conteudo = f"Tool '{nome}' não existe. Tools disponíveis: {list(tools_por_nome)}"
            else:
                try:
                    conteudo = str(tool.invoke(args))
                except Exception as e:
                    logger.error(f"Tool {nome} falhou: {e}")
                    conteudo = f"ERRO ao executar {nome}: {e}"
            msg_tool = ToolMessage(content=conteudo, tool_call_id=tc["id"], name=nome)
            historico.append(msg_tool)
            geradas.append(msg_tool)
    else:
        logger.warning(f"loop_react atingiu max_iteracoes={max_iteracoes} sem terminar")

    return geradas
