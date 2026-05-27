"""Supervisor LangGraph — orquestra coletor, analista e recomendador."""
import logging
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from agents.analyst_agent import analista_node
from agents.collector_agent import coletor_node
from agents.common import construir_llm
from agents.recommender_agent import recomendador_node

logger = logging.getLogger(__name__)

AGENTES_VALIDOS = {"coletor", "analista", "recomendador", "FINISH"}


class State(TypedDict):
    messages: list[BaseMessage]
    next_agent: str
    iteracoes: int


SUPERVISOR_PROMPT = """Você é o supervisor de um sistema multi-agente para análise de
mercado imobiliário do BTG Pactual.

Agentes disponíveis:

- coletor: busca ofertas novas na CVM e popula o Neo4j.
  Acione APENAS quando o usuário pedir explicitamente "atualizar dados",
  "coletar agora", "buscar ofertas novas", "rodar coleta".

- analista: consulta o grafo Neo4j e RESPONDE perguntas (NÃO cria nada).
  Acione para QUALQUER pergunta analítica/informativa, incluindo:
    "qual a melhor oferta", "qual a taxa média", "quais ofertas existem",
    "quem distribui X", "o que tem no mercado", "compare X e Y",
    "mostre as ofertas de FII", "quanto o BTG está pagando", etc.

- recomendador: gera insights ESTRATÉGICOS e/ou cria ALERTAS no banco.
  Acione APENAS quando o usuário pedir EXPLICITAMENTE:
    "crie um alerta", "registre alerta", "detecte gaps", "recomende posicionamento",
    "gere insight estratégico", "o que o BTG deve fazer".
  NÃO acione recomendador só porque a pergunta tem "melhor" ou "recomendar comprar".

- FINISH: quando o último agente já respondeu adequadamente.

Regras críticas:
- Em caso de dúvida entre analista e recomendador → escolha ANALISTA. O analista
  é seguro (só lê), o recomendador escreve no banco (alertas).
- Após o agente responder à pergunta do usuário, retorne FINISH.
- Nunca acione o mesmo agente duas vezes seguidas sem motivo.
- Responda APENAS com uma palavra: coletor, analista, recomendador ou FINISH.
"""


def _ultima_mensagem_texto(msgs: list[BaseMessage]) -> str:
    for m in reversed(msgs):
        if isinstance(m, (HumanMessage, AIMessage)) and m.content:
            return str(m.content)
    return ""


def supervisor_node(state: State) -> dict:
    iteracoes = state.get("iteracoes", 0)

    if iteracoes >= 4:
        logger.warning("Supervisor atingiu limite de iterações; forçando FINISH.")
        return {"next_agent": "FINISH", "iteracoes": iteracoes}

    llm = construir_llm(temperature=0.0)

    msgs_para_decidir = [
        SystemMessage(content=SUPERVISOR_PROMPT),
        HumanMessage(content=(
            f"Histórico da conversa:\n{_resumir_mensagens(state['messages'])}\n\n"
            "Qual agente deve responder agora? Responda apenas com: "
            "coletor, analista, recomendador ou FINISH."
        )),
    ]
    resp = llm.invoke(msgs_para_decidir)
    escolha = str(resp.content).strip().split()[0].rstrip(".,!?").lower()

    if escolha == "finish":
        escolha = "FINISH"
    if escolha not in AGENTES_VALIDOS:
        logger.warning(f"Supervisor devolveu valor inválido: {resp.content!r} → FINISH")
        escolha = "FINISH"

    return {"next_agent": escolha, "iteracoes": iteracoes + 1}


def _resumir_mensagens(msgs: list[BaseMessage], max_chars: int = 2000) -> str:
    linhas = []
    for m in msgs[-6:]:
        tipo = type(m).__name__.replace("Message", "")
        conteudo = str(m.content)[:300] if m.content else "(sem conteúdo)"
        linhas.append(f"[{tipo}] {conteudo}")
    out = "\n".join(linhas)
    if len(out) > max_chars:
        out = out[-max_chars:]
    return out


def _rotear(state: State) -> Literal["coletor", "analista", "recomendador", "FINISH"]:
    return state["next_agent"]  # type: ignore[return-value]


def construir_grafo():
    graph = StateGraph(State)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("coletor", coletor_node)
    graph.add_node("analista", analista_node)
    graph.add_node("recomendador", recomendador_node)

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        _rotear,
        {
            "coletor": "coletor",
            "analista": "analista",
            "recomendador": "recomendador",
            "FINISH": END,
        },
    )

    for agente in ["coletor", "analista", "recomendador"]:
        graph.add_edge(agente, "supervisor")

    return graph.compile()


def perguntar(grafo, pergunta: str) -> str:
    """Atalho para uma única pergunta — retorna a resposta final do último agente."""
    estado_final = grafo.invoke(
        {
            "messages": [HumanMessage(content=pergunta)],
            "next_agent": "",
            "iteracoes": 0,
        },
        config={"recursion_limit": 25},
    )
    for m in reversed(estado_final["messages"]):
        if isinstance(m, AIMessage) and m.content and not m.tool_calls:
            return str(m.content)
    return "(sem resposta)"


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pergunta_default = "Qual a taxa média das ofertas de FII em andamento no mercado?"
    pergunta = " ".join(sys.argv[1:]) or pergunta_default
    print(f"\nPergunta: {pergunta}\n")
    grafo = construir_grafo()
    print(perguntar(grafo, pergunta))
