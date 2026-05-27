"""Dashboard Streamlit — Monitor de Ofertas Primárias Imobiliárias BTG."""
import logging
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from agents.supervisor import construir_grafo, perguntar
from graph import queries
from graph.neo4j_client import get_client
from scheduler.monitor import criar_scheduler, parar, proximo_disparo

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

st.set_page_config(
    page_title="BTG · Monitor de Mercado Imobiliário",
    page_icon=":bar_chart:",
    layout="wide",
)


# ---------- Inicialização (singleton via session_state) ----------

@st.cache_resource
def _grafo_singleton():
    return construir_grafo()


def _inicializar_scheduler() -> None:
    if "scheduler_iniciado" in st.session_state:
        return
    grafo = _grafo_singleton()
    try:
        st.session_state.scheduler = criar_scheduler(grafo)
        st.session_state.scheduler_iniciado = True
    except Exception as e:
        st.session_state.scheduler = None
        st.session_state.scheduler_erro = str(e)
        st.session_state.scheduler_iniciado = True


def _verificar_conexao_neo4j() -> bool:
    try:
        return get_client().verificar_conexao()
    except Exception:
        return False


# ---------- Loaders com cache curto ----------

@st.cache_data(ttl=60)
def carregar_ofertas_em_andamento(tipo: str | None = None) -> pd.DataFrame:
    dados = queries.listar_ofertas_em_andamento(tipo=tipo)
    return pd.DataFrame(dados) if dados else pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_taxa_media_por_indexador() -> pd.DataFrame:
    return pd.DataFrame(queries.taxa_media_por_indexador())


@st.cache_data(ttl=60)
def carregar_gap_btg_vs_mercado() -> pd.DataFrame:
    return pd.DataFrame(queries.gap_btg_vs_mercado())


@st.cache_data(ttl=60)
def carregar_ofertas_sem_btg() -> pd.DataFrame:
    return pd.DataFrame(queries.ofertas_sem_btg())


@st.cache_data(ttl=30)
def carregar_alertas(criticidade: str | None = None) -> pd.DataFrame:
    return pd.DataFrame(queries.listar_alertas_pendentes(criticidade=criticidade))


# ---------- Sidebar ----------

def render_sidebar() -> None:
    st.sidebar.title("BTG · Monitor")
    st.sidebar.caption("Ofertas primárias — CRI, CRA, FII")

    conectado = _verificar_conexao_neo4j()
    st.sidebar.markdown(
        f"**Neo4j:** {'conectado' if conectado else 'desconectado'}"
    )

    sched = st.session_state.get("scheduler")
    if sched and sched.running:
        prox = proximo_disparo(sched)
        st.sidebar.markdown(
            f"**Scheduler:** ativo  \nPróxima coleta: "
            f"{prox.strftime('%H:%M:%S') if prox else '—'}"
        )
    else:
        st.sidebar.markdown("**Scheduler:** parado")
        if "scheduler_erro" in st.session_state:
            st.sidebar.caption(f"Erro: {st.session_state.scheduler_erro}")

    if st.sidebar.button("Limpar cache e recarregar"):
        st.cache_data.clear()
        st.rerun()


# ---------- Abas ----------

def _formatar_distribuidores(valor) -> str:
    """Transforma lista de {banco, papel} em string legível: 'BTG (LIDER), XP (DISTRIB)'."""
    if not isinstance(valor, list) or not valor:
        return "—"
    siglas = {"COORDENADOR_LIDER": "LIDER", "DISTRIBUIDOR": "DISTRIB"}
    partes = []
    for d in valor:
        if not isinstance(d, dict):
            continue
        banco = d.get("banco")
        if not banco:
            continue
        papel = siglas.get(d.get("papel") or "", d.get("papel") or "")
        partes.append(f"{banco} ({papel})" if papel else banco)
    return ", ".join(partes) if partes else "—"


def _fmt_pct(v) -> str:
    return f"{v:.2f}%" if v is not None and pd.notna(v) else "—"


def _fmt_dinheiro(v) -> str:
    if v is None or pd.isna(v) or v == 0:
        return "—"
    if v >= 1_000_000_000:
        return f"R$ {v/1e9:.2f} bi"
    if v >= 1_000_000:
        return f"R$ {v/1e6:.2f} mi"
    return f"R$ {v:,.0f}".replace(",", ".")


def _classificar_enriquecimento(row: pd.Series) -> str:
    """Classifica nível de dado disponível por oferta (para coluna 'Cobertura')."""
    tem_fee = pd.notna(row.get("preco_emissao")) or pd.notna(row.get("comissao_pct"))
    tem_fii = pd.notna(row.get("fii_pl"))
    if tem_fee and tem_fii:
        return "Completo"
    if tem_fee:
        return "Prospecto"
    if tem_fii:
        return "Fundo"
    return "Cadastral"


def aba_mercado_agora() -> None:
    st.header("Mercado agora")
    st.caption("Ofertas em andamento — Registro Concedido + Aguardando Bookbuilding.")

    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    with col_f1:
        tipo = st.selectbox("Tipo", ["Todos", "FII", "CRI", "CRA", "DEBENTURE"])
    with col_f2:
        cobertura_filtro = st.selectbox(
            "Cobertura mín.",
            ["Todas", "Com dado de fundo", "Com fee de prospecto", "Completas"],
        )
    tipo_filtro = None if tipo == "Todos" else tipo

    df = carregar_ofertas_em_andamento(tipo=tipo_filtro)

    if df.empty:
        st.info("Ainda não há ofertas no grafo. Aguarde a próxima coleta ou clique em "
                "_Limpar cache e recarregar_ na sidebar.")
        return

    # Classifica cada oferta por nível de enriquecimento
    df = df.copy()
    df["cobertura"] = df.apply(_classificar_enriquecimento, axis=1)

    # Aplica filtro de cobertura
    if cobertura_filtro == "Com dado de fundo":
        df = df[df["cobertura"].isin(["Completo", "Prospecto", "Fundo"])]
    elif cobertura_filtro == "Com fee de prospecto":
        df = df[df["cobertura"].isin(["Completo", "Prospecto"])]
    elif cobertura_filtro == "Completas":
        df = df[df["cobertura"] == "Completo"]

    if df.empty:
        st.warning(f"Nenhuma oferta atende ao filtro '{cobertura_filtro}'.")
        return

    # Cards de resumo
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ofertas filtradas", len(df))
    if "volume" in df.columns:
        vol_total = df["volume"].fillna(0).sum()
        c2.metric("Volume total registrado", _fmt_dinheiro(vol_total))
    if "comissao_pct" in df.columns:
        com_med = df["comissao_pct"].mean()
        com_n = df["comissao_pct"].notna().sum()
        c3.metric(f"Comissão média (n={com_n})", _fmt_pct(com_med))
    if "fii_pl" in df.columns:
        fii_n = df["fii_pl"].notna().sum()
        c4.metric("FIIs com dados financeiros", int(fii_n))

    st.subheader("Lista de ofertas")
    df_view = df.copy()

    # Renderização amigável
    if "distribuidores" in df_view.columns:
        df_view["distribuidores"] = df_view["distribuidores"].apply(_formatar_distribuidores)
    if "volume" in df_view.columns:
        df_view["volume"] = df_view["volume"].apply(_fmt_dinheiro)
    if "preco_emissao" in df_view.columns:
        df_view["preco_emissao"] = df_view["preco_emissao"].apply(_fmt_dinheiro)
    for c in ("comissao_pct", "fii_rend_mes", "fii_taxa_adm"):
        if c in df_view.columns:
            df_view[c] = df_view[c].apply(_fmt_pct)
    for c in ("fii_pl", "fii_vp_cota"):
        if c in df_view.columns:
            df_view[c] = df_view[c].apply(_fmt_dinheiro)

    # Renomeia colunas para nomes legíveis
    df_view = df_view.rename(columns={
        "id": "ID", "numero_registro": "Nº Registro", "tipo": "Tipo",
        "emissor": "Emissor", "volume": "Volume", "data_registro": "Data",
        "distribuidores": "Distribuidores",
        "preco_emissao": "Preço Emissão", "comissao_pct": "Comissão Distr.",
        "regime": "Regime", "publico_alvo": "Público",
        "fii_tipo": "Tipo FII", "fii_rend_mes": "Rent. mês",
        "fii_vp_cota": "VP/Cota", "fii_pl": "PL Fundo",
        "fii_taxa_adm": "Taxa Adm", "fii_cotistas": "Cotistas",
        "cobertura": "Cobertura",
    })

    colunas_ordenadas = [c for c in [
        "ID", "Cobertura", "Nº Registro", "Tipo", "Tipo FII", "Emissor",
        "Volume", "Data", "Distribuidores",
        "Preço Emissão", "Comissão Distr.",
        "Regime", "Público", "Rent. mês", "VP/Cota", "PL Fundo", "Taxa Adm", "Cotistas",
    ] if c in df_view.columns]
    st.dataframe(df_view[colunas_ordenadas], use_container_width=True, hide_index=True)
    st.caption(
        "**Legenda da cobertura:** "
        "_Completo_ = prospecto + informe mensal · "
        "_Prospecto_ = fee extraído do PDF · "
        "_Fundo_ = só dado financeiro do informe mensal · "
        "_Cadastral_ = só metadados do registro CVM. "
        "Taxa final/indexador da oferta não são publicados pela CVM em dados abertos."
    )

    # Gráfico: ranking de coordenadores líderes por nº de ofertas
    st.subheader("Top distribuidores (coordenadores líderes)")
    lideres = []
    for lst in df["distribuidores"]:
        if not isinstance(lst, list):
            continue
        for d in lst:
            if isinstance(d, dict) and d.get("papel") == "COORDENADOR_LIDER" and d.get("banco"):
                lideres.append(d["banco"])
                break
    if lideres:
        ranking = pd.Series(lideres).value_counts().head(15).reset_index()
        ranking.columns = ["Banco", "Ofertas"]
        fig = px.bar(
            ranking, x="Ofertas", y="Banco", orientation="h",
            color="Ofertas", color_continuous_scale="Blues",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=500)
        st.plotly_chart(fig, use_container_width=True)


def aba_btg_vs_concorrentes() -> None:
    st.header("BTG vs concorrentes")
    st.caption(
        "Comparação do grupo BTG (Investment Banking, Serviços Financeiros DTVM, etc.) "
        "com o restante do mercado nas ofertas EM_ANDAMENTO."
    )

    gap = carregar_gap_btg_vs_mercado()
    sem_btg = carregar_ofertas_sem_btg()
    from graph.queries import ranking_distribuidores
    ranking = pd.DataFrame(ranking_distribuidores(limite=15))

    # Linha de cards: market share total do BTG
    if not gap.empty:
        total_btg = int(gap["qtd_btg"].sum())
        total_mercado = int(gap["qtd_total"].sum())
        share_global = (total_btg / total_mercado * 100) if total_mercado else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Ofertas BTG (em andamento)", total_btg)
        c2.metric("Total mercado", total_mercado)
        c3.metric("Market share BTG", f"{share_global:.1f}%")

    # Tabela: posicionamento por tipo
    st.subheader("Posicionamento por tipo de ativo")
    if gap.empty:
        st.caption("Sem dados suficientes.")
    else:
        gap_view = gap.copy()
        gap_view["share_pct"] = gap_view["share_pct"].apply(lambda v: f"{v:.1f}%")
        gap_view["vol_medio_btg"] = gap_view["vol_medio_btg"].apply(_fmt_dinheiro)
        gap_view["vol_medio_mercado"] = gap_view["vol_medio_mercado"].apply(_fmt_dinheiro)
        gap_view = gap_view.rename(columns={
            "tipo": "Tipo", "qtd_btg": "Ofertas BTG", "qtd_total": "Total mercado",
            "share_pct": "Market share", "vol_medio_btg": "Vol. médio BTG",
            "vol_medio_mercado": "Vol. médio mercado",
        })
        st.dataframe(gap_view, use_container_width=True, hide_index=True)

    # Ranking de distribuidores
    st.subheader("Top distribuidores por nº de ofertas em andamento")
    if ranking.empty:
        st.caption("Sem dados.")
    else:
        ranking_view = ranking.copy()
        ranking_view["volume_total"] = ranking_view["volume_total"].apply(_fmt_dinheiro)
        ranking_view = ranking_view.rename(columns={
            "banco": "Banco", "qtd_ofertas": "Ofertas", "volume_total": "Volume total",
        })
        st.dataframe(ranking_view, use_container_width=True, hide_index=True)

        # Gráfico do ranking
        fig = px.bar(
            ranking.sort_values("qtd_ofertas"),
            x="qtd_ofertas", y="banco", orientation="h",
            color="qtd_ofertas", color_continuous_scale="Blues",
            labels={"qtd_ofertas": "Ofertas em andamento", "banco": ""},
        )
        fig.update_layout(height=550, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Filtrar ofertas por distribuidor específico
    st.subheader("Ofertas por distribuidor")
    from graph.queries import listar_bancos_distribuidores, ofertas_por_distribuidor
    bancos_disponiveis = pd.DataFrame(listar_bancos_distribuidores())
    if not bancos_disponiveis.empty:
        # Sugestões fixas dos grandes + opção de digitar
        sugestoes = ["BTG PACTUAL", "XP", "ITAU", "BRADESCO", "SANTANDER",
                    "SAFRA", "BB ", "CAIXA", "GENIAL", "MASTER", "RICO"]
        opcoes_combo = sugestoes + ["— ver todos —"]
        col_a, col_b = st.columns([1, 3])
        with col_a:
            sel = st.selectbox("Banco/grupo", opcoes_combo, key="dist_sel")
        with col_b:
            custom = st.text_input(
                "Ou digite parte do nome (ex: 'RIO BRAVO')",
                key="dist_custom",
                placeholder="deixe vazio para usar o seletor",
            )
        padrao_busca = (custom.strip() if custom.strip()
                        else ("" if sel == "— ver todos —" else sel))

        if padrao_busca:
            ofertas_dist = pd.DataFrame(ofertas_por_distribuidor(padrao_busca))
            if ofertas_dist.empty:
                st.caption(f"Nenhuma oferta encontrada para '{padrao_busca}'.")
            else:
                vol_total = ofertas_dist["volume"].fillna(0).sum()
                qtd = len(ofertas_dist)
                c1, c2 = st.columns(2)
                c1.metric(f"Ofertas com '{padrao_busca}'", qtd)
                c2.metric("Volume agregado", _fmt_dinheiro(vol_total))

                df_view = ofertas_dist.copy()
                df_view["volume"] = df_view["volume"].apply(_fmt_dinheiro)
                df_view["papeis_banco"] = df_view["papeis_banco"].apply(_formatar_distribuidores)
                df_view["fii_pl"] = df_view["fii_pl"].apply(_fmt_dinheiro)
                df_view = df_view.rename(columns={
                    "id": "ID", "numero_registro": "Nº Registro", "tipo": "Tipo",
                    "emissor": "Emissor", "volume": "Volume", "data": "Data",
                    "regime": "Regime", "publico": "Público",
                    "papeis_banco": "Papel do banco",
                    "fii_tipo": "Tipo FII", "fii_pl": "PL Fundo",
                })
                colunas = [c for c in [
                    "ID", "Nº Registro", "Tipo", "Tipo FII", "Emissor",
                    "Volume", "Data", "Papel do banco", "Regime", "Público", "PL Fundo",
                ] if c in df_view.columns]
                st.dataframe(df_view[colunas], use_container_width=True, hide_index=True)
        else:
            st.caption("Selecione um banco ou digite um nome para listar suas ofertas.")

    # Ofertas que BTG não distribui (oportunidades)
    st.subheader("Oportunidades — ofertas onde o BTG não está presente")
    if sem_btg.empty:
        st.caption("Nenhuma oferta sem o BTG no momento.")
    else:
        sem_btg_view = sem_btg.copy()
        sem_btg_view["volume"] = sem_btg_view["volume"].apply(_fmt_dinheiro)
        sem_btg_view["distribuidores"] = sem_btg_view["distribuidores"].apply(
            lambda lst: ", ".join(b for b in lst if b) if isinstance(lst, list) else "—"
        )
        sem_btg_view = sem_btg_view.rename(columns={
            "id": "ID", "numero_registro": "Nº Registro", "tipo": "Tipo",
            "emissor": "Emissor", "volume": "Volume", "distribuidores": "Distribuidores",
        })
        st.dataframe(sem_btg_view.head(30), use_container_width=True, hide_index=True)
        st.caption(f"Mostrando 30 de {len(sem_btg)} ofertas (ordenado por volume).")


def aba_alertas() -> None:
    st.header("Alertas")
    crit = st.selectbox("Filtrar por criticidade", ["Todas", "ALTA", "MEDIA", "BAIXA"])
    filtro = None if crit == "Todas" else crit
    df = carregar_alertas(criticidade=filtro)

    if df.empty:
        st.success("Nenhum alerta pendente.")
        return

    for _, row in df.iterrows():
        with st.expander(f"[{row['criticidade']}] [{row['tipo']}] {row['descricao'][:120]}"):
            st.write(f"**Criticidade:** {row['criticidade']}")
            st.write(f"**Criado em:** {row['criado_em']}")
            if row.get("id_oferta"):
                st.write(f"**Oferta relacionada:** {row['id_oferta']}")
            st.write(row["descricao"])
            if st.button(f"Marcar como visualizado", key=f"viz_{row['id']}"):
                queries.marcar_alerta_visualizado(row["id"])
                st.cache_data.clear()
                st.rerun()


def aba_chat() -> None:
    st.header("Pergunte ao agente")
    st.caption("Faça perguntas sobre o mercado — o supervisor roteia para o agente certo.")

    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    for msg in st.session_state.mensagens:
        st.chat_message(msg["role"]).write(msg["content"])

    pergunta = st.chat_input("Ex: Qual a taxa média de FII em andamento?")
    if not pergunta:
        return

    st.session_state.mensagens.append({"role": "user", "content": pergunta})
    st.chat_message("user").write(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Analisando..."):
            try:
                resposta = perguntar(_grafo_singleton(), pergunta)
            except Exception as e:
                resposta = f"Erro ao processar a pergunta: {e}"
        st.write(resposta)
        st.session_state.mensagens.append({"role": "assistant", "content": resposta})


# ---------- Main ----------

def main() -> None:
    if not _verificar_conexao_neo4j():
        st.error(
            "Não foi possível conectar ao Neo4j. Verifique as variáveis "
            "NEO4J_URI, NEO4J_USER e NEO4J_PASSWORD no arquivo `.env`."
        )
        st.stop()

    if not os.getenv("GROQ_API_KEY"):
        st.warning(
            "GROQ_API_KEY ausente — o chat com o agente e o scheduler de coleta "
            "automática não vão funcionar. Adicione no `.env` para habilitar."
        )
    else:
        _inicializar_scheduler()

    render_sidebar()

    aba1, aba2, aba3, aba4 = st.tabs([
        "Mercado agora",
        "BTG vs concorrentes",
        "Alertas",
        "Pergunte ao agente",
    ])
    with aba1:
        aba_mercado_agora()
    with aba2:
        aba_btg_vs_concorrentes()
    with aba3:
        aba_alertas()
    with aba4:
        aba_chat()


main()
