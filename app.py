"""Dashboard Streamlit — Monitor de Ofertas Primárias Imobiliárias BTG."""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Permite rodar `streamlit run app.py` sem `pip install -e .` (src layout)
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd
import plotly.express as px
import plotly.io as pio
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

# Paleta oficial BTG Pactual: azul marinho profundo + cinza + branco
BTG_PRIMARY = "#1E5BB8"   # azul marinho principal
BTG_DEEP = "#0E3979"      # azul mais escuro
BTG_LIGHT = "#4A90E2"     # azul claro
BTG_DARK = "#0A0E1A"      # background preto-azulado
BTG_PANEL = "#11182A"     # painel secundário

BTG_PALETTE = [
    "#1E5BB8", "#4A90E2", "#0E3979", "#7FB3F0", "#2B7AC4",
    "#8FAFD8", "#163B6E", "#A8C5E8", "#0A2952", "#C7D9F0",
]
BTG_SCALE = [[0.0, "#0A2952"], [0.5, "#1E5BB8"], [1.0, "#7FB3F0"]]

# Template Plotly único — aplicado em todos os gráficos
pio.templates["btg"] = pio.templates["plotly_dark"]
pio.templates["btg"]["layout"]["colorway"] = BTG_PALETTE
pio.templates["btg"]["layout"]["paper_bgcolor"] = BTG_DARK
pio.templates["btg"]["layout"]["plot_bgcolor"] = BTG_DARK
pio.templates["btg"]["layout"]["font"]["color"] = "#F5F7FA"
pio.templates.default = "btg"


_CSS_BTG = """
<style>
/* Tipografia */
h1, h2, h3 { letter-spacing: -0.01em; font-weight: 600; }
section.main > div { padding-top: 1rem; }

/* Cards de métrica — compactos, sem truncar label */
[data-testid="stMetric"] {
    background-color: #11182A !important;
    border: 1px solid #1F2A44 !important;
    border-radius: 8px !important;
    padding: 14px 18px !important;
}
[data-testid="stMetricValue"] {
    color: #4A90E2 !important;
    font-weight: 600 !important;
    font-size: 1.6rem !important;
    line-height: 1.2 !important;
}
[data-testid="stMetricValue"] > div {
    color: #4A90E2 !important;
    overflow: visible !important;
    white-space: nowrap !important;
}
[data-testid="stMetricLabel"] {
    color: #8B95A8 !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
}
[data-testid="stMetricLabel"] > div,
[data-testid="stMetricLabel"] p {
    color: #8B95A8 !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
}

/* Gap entre as colunas de cards */
[data-testid="stHorizontalBlock"] {
    gap: 12px !important;
}

/* Dataframes com borda sutil */
[data-testid="stDataFrame"] {
    border: 1px solid #1F2A44;
    border-radius: 6px;
    overflow: hidden;
}

/* ===== Tabs com visual de botão e hover ===== */
div[data-baseweb="tab-list"] {
    gap: 8px !important;
    border-bottom: 1px solid #1F2A44 !important;
    padding-bottom: 0 !important;
    margin-bottom: 18px !important;
}
button[data-baseweb="tab"] {
    background-color: transparent !important;
    color: #9AA3B2 !important;
    padding: 12px 22px !important;
    border-radius: 8px 8px 0 0 !important;
    border: 1px solid transparent !important;
    border-bottom: 2px solid transparent !important;
    margin-bottom: -1px !important;
    font-weight: 500 !important;
    transition: background-color 0.15s ease, color 0.15s ease,
                border-color 0.15s ease !important;
}
button[data-baseweb="tab"]:hover {
    background-color: #11182A !important;
    color: #F5F7FA !important;
    border-color: #1F2A44 !important;
    border-bottom-color: #2A3654 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    background-color: #11182A !important;
    color: #4A90E2 !important;
    border-color: #1F2A44 !important;
    border-bottom-color: #1E5BB8 !important;
    font-weight: 600 !important;
}
/* Tira o sublinhado padrão do baseweb */
div[data-baseweb="tab-highlight"],
[data-baseweb="tab-border"] {
    display: none !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #07101F;
    border-right: 1px solid #1F2A44;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #F5F7FA;
}

/* Botões */
.stButton > button {
    border-radius: 6px;
}
.stButton > button[kind="primary"] {
    background-color: #1E5BB8;
    border-color: #1E5BB8;
}
.stButton > button[kind="primary"]:hover {
    background-color: #2B6FCC;
    border-color: #2B6FCC;
}

/* Containers de seção (st.container(border=True)) — visual sutil de painel */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #11182A !important;
    border: 1px solid #1F2A44 !important;
    border-radius: 8px !important;
    padding: 18px 22px !important;
    margin-bottom: 12px !important;
}
/* Não aninhar borda — cards dentro de cards ficam transparentes */
div[data-testid="stVerticalBlockBorderWrapper"]
    div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: transparent !important;
    border: none !important;
    padding: 0 !important;
    margin: 0 !important;
}
/* Headers dentro de cards têm menos margem superior */
div[data-testid="stVerticalBlockBorderWrapper"] h2:first-child,
div[data-testid="stVerticalBlockBorderWrapper"] h3:first-child {
    margin-top: 0 !important;
}

/* Expanders */
[data-testid="stExpander"] {
    border: 1px solid #1F2A44;
    border-radius: 6px;
}

/* Selectbox e input */
[data-baseweb="select"] > div,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background-color: #11182A;
    border-color: #1F2A44 !important;
}

/* Headers de seção com margem superior pra respirar */
.main h2 { margin-top: 1.4rem; }
.main h3 { margin-top: 1rem; }

/* ===== Chat input sticky no rodapé do main (respeita sidebar automaticamente) =====
   position: sticky fica no flow do main — quando rola, gruda no bottom: 0
   da viewport, e a largura/posição respeita o container pai (que já é
   ajustado pelo Streamlit pra começar depois da sidebar). */
[data-testid="stChatInput"] {
    position: sticky !important;
    bottom: 0 !important;
    z-index: 100 !important;
    background-color: #07101F !important;
    border-top: 1px solid #1F2A44 !important;
    padding: 14px 0 14px 0 !important;
    margin: 0 -1rem -1rem -1rem !important;  /* sangra até as bordas do main */
}

/* Input do chat respeita o tema */
[data-testid="stChatInput"] textarea,
[data-testid="stChatInput"] input {
    background-color: #11182A !important;
    border-color: #2A3654 !important;
    color: #F5F7FA !important;
}
[data-testid="stChatInput"] > div {
    padding: 0 32px !important;
}
</style>
"""


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

def _fmt_intervalo(dt) -> str:
    """Formata um datetime futuro como 'em Xmin' ou 'em Xs'."""
    if dt is None:
        return "—"
    from datetime import datetime
    import datetime as dt_mod
    agora = datetime.now(dt.tzinfo) if getattr(dt, "tzinfo", None) else datetime.now()
    delta = (dt - agora).total_seconds()
    if delta <= 0:
        return "iminente"
    if delta < 60:
        return f"em {int(delta)}s"
    if delta < 3600:
        return f"em {int(delta/60)}min"
    return f"em {int(delta/3600)}h{int((delta%3600)/60):02d}"


def render_sidebar() -> None:
    st.sidebar.markdown(
        "<div style='padding: 8px 0 16px 0;'>"
        "<div style='font-size:1.35rem; font-weight:600; color:#F5F7FA;'>BTG Pactual</div>"
        "<div style='font-size:0.8rem; color:#7A8499; letter-spacing:0.05em; text-transform:uppercase;'>"
        "Monitor de Ofertas</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.divider()

    # Status do sistema em formato discreto
    conectado = _verificar_conexao_neo4j()
    cor_neo = "#4A90E2" if conectado else "#C44"
    txt_neo = "online" if conectado else "offline"
    st.sidebar.markdown(
        f"<div style='display:flex; justify-content:space-between; padding:4px 0;'>"
        f"<span style='color:#9AA3B2;'>Neo4j</span>"
        f"<span style='color:{cor_neo}; font-weight:600;'>{txt_neo}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    sched = st.session_state.get("scheduler")
    if sched and sched.running:
        prox = proximo_disparo(sched)
        proxima = _fmt_intervalo(prox)
        st.sidebar.markdown(
            f"<div style='display:flex; justify-content:space-between; padding:4px 0;'>"
            f"<span style='color:#9AA3B2;'>Scheduler</span>"
            f"<span style='color:#4A90E2; font-weight:600;'>ativo</span>"
            f"</div>"
            f"<div style='display:flex; justify-content:space-between; padding:4px 0;'>"
            f"<span style='color:#9AA3B2;'>Próxima coleta</span>"
            f"<span style='color:#F5F7FA;'>{proxima}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.markdown(
            "<div style='display:flex; justify-content:space-between; padding:4px 0;'>"
            "<span style='color:#9AA3B2;'>Scheduler</span>"
            "<span style='color:#7A8499;'>parado</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        if "scheduler_erro" in st.session_state:
            st.sidebar.caption(f"Erro: {st.session_state.scheduler_erro}")

    st.sidebar.divider()

    if st.sidebar.button("Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.caption(
        "Fonte: CVM Dados Abertos · atualização diária. "
        "Cache local de 60s na UI."
    )


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

    # ----- Filtros (sem card pra não dobrar borda) -----
    col_f1, col_f2 = st.columns([1, 1])
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

    # ----- CARDS de resumo (sem container externo — já têm visual de card) -----
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

    # ----- CARD: Lista de ofertas -----
    with st.container(border=True):
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

    # ----- CARD: Panorama visual (4 gráficos) -----
    with st.container(border=True):
        st.subheader("Panorama visual")
        g1, g2 = st.columns(2)

        # 1. Donut: distribuição de qtd por tipo
        with g1:
            tipos_count = df["tipo"].value_counts().reset_index()
            tipos_count.columns = ["Tipo", "Qtd"]
            if not tipos_count.empty:
                fig = px.pie(
                    tipos_count, names="Tipo", values="Qtd", hole=0.5,
                    title="Ofertas por tipo (quantidade)",
                    color_discrete_sequence=BTG_PALETTE,
                )
                fig.update_traces(textinfo="label+percent+value", textposition="outside")
                fig.update_layout(
                    showlegend=False, height=420,
                    margin=dict(l=20, r=20, t=60, b=40),
                    title_x=0.5,
                )
                st.plotly_chart(fig, use_container_width=True)

        # 2. Barras: volume total por tipo
        with g2:
            vol_por_tipo = df.groupby("tipo")["volume"].sum(numeric_only=True).reset_index()
            vol_por_tipo.columns = ["Tipo", "Volume"]
            vol_por_tipo["Volume_bi"] = vol_por_tipo["Volume"] / 1e9
            if not vol_por_tipo.empty:
                fig = px.bar(
                    vol_por_tipo.sort_values("Volume_bi"),
                    x="Volume_bi", y="Tipo", orientation="h",
                    title="Volume total por tipo (R$ bi)",
                    text="Volume_bi", color="Volume_bi",
                    color_continuous_scale=BTG_SCALE,
                )
                fig.update_traces(
                    texttemplate="R$ %{text:.2f} bi",
                    textposition="outside", cliponaxis=False,
                )
                max_v = vol_por_tipo["Volume_bi"].max()
                fig.update_layout(
                    showlegend=False, height=420, coloraxis_showscale=False,
                    xaxis_title="Volume (R$ bi)", yaxis_title="",
                    xaxis=dict(range=[0, max_v * 1.25]),
                    margin=dict(l=60, r=80, t=60, b=40),
                    title_x=0.5,
                )
                st.plotly_chart(fig, use_container_width=True)

        g3, g4 = st.columns(2)

        # 3. Histograma: distribuição de volume por oferta (em R$ milhões)
        with g3:
            df_vol = df[df["volume"].notna() & (df["volume"] > 0)].copy()
            if not df_vol.empty:
                df_vol["volume_mi"] = df_vol["volume"] / 1_000_000
                p95 = df_vol["volume_mi"].quantile(0.95)
                df_vol["volume_clipped"] = df_vol["volume_mi"].clip(upper=p95)
                fig = px.histogram(
                    df_vol, x="volume_clipped", color="tipo", nbins=25,
                    title="Distribuição de volume por oferta (R$ mi)",
                    labels={"volume_clipped": "Volume (R$ milhões)", "tipo": "Tipo"},
                    color_discrete_sequence=BTG_PALETTE,
                )
                fig.update_layout(
                    height=420, bargap=0.05, title_x=0.5,
                    margin=dict(l=60, r=20, t=60, b=60),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.25,
                                xanchor="center", x=0.5),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    f"Mín: R$ {df_vol['volume_mi'].min():.1f} mi · "
                    f"Mediana: R$ {df_vol['volume_mi'].median():.1f} mi · "
                    f"Máx: R$ {df_vol['volume_mi'].max():.0f} mi · "
                    f"clipped no p95 = R$ {p95:.0f} mi · "
                    f"({len(df_vol)} ofertas com volume registrado)"
                )

        # 4. Stacked bar: público-alvo por tipo
        with g4:
            if "publico_alvo" in df.columns and df["publico_alvo"].notna().any():
                mix = df.groupby(["tipo", "publico_alvo"]).size().reset_index(name="Qtd")
                fig = px.bar(
                    mix, x="tipo", y="Qtd", color="publico_alvo", barmode="stack",
                    title="Público-alvo por tipo",
                    labels={"tipo": "", "publico_alvo": "Público", "Qtd": "Ofertas"},
                    color_discrete_sequence=BTG_PALETTE,
                )
                fig.update_layout(
                    height=420, title_x=0.5,
                    margin=dict(l=40, r=20, t=60, b=60),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.25,
                                xanchor="center", x=0.5, title=""),
                )
                st.plotly_chart(fig, use_container_width=True)

    # ----- CARD: Ranking de coordenadores líderes -----
    with st.container(border=True):
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
            ranking["BancoLabel"] = ranking["Banco"].str.replace(
                r"\s*S[/.]?A\.?$", "", regex=True
            ).str.title().str.slice(0, 38)
            fig = px.bar(
                ranking, x="Ofertas", y="BancoLabel", orientation="h",
                color="Ofertas", color_continuous_scale=BTG_SCALE,
                text="Ofertas",
                hover_data={"Banco": True, "BancoLabel": False},
            )
            fig.update_traces(textposition="outside", cliponaxis=False)
            max_n = ranking["Ofertas"].max()
            fig.update_layout(
                yaxis={"categoryorder": "total ascending", "title": ""},
                xaxis={"title": "Ofertas em andamento",
                       "range": [0, max_n * 1.18]},
                height=560,
                coloraxis_showscale=False,
                margin=dict(l=260, r=40, t=20, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)


def _formatar_lista_distribuidores(papeis) -> str:
    if not isinstance(papeis, list):
        return "—"
    siglas = {"COORDENADOR_LIDER": "LIDER", "DISTRIBUIDOR": "DISTRIB"}
    out = []
    for d in papeis:
        if not isinstance(d, dict) or not d.get("banco"):
            continue
        papel = siglas.get(d.get("papel") or "", d.get("papel") or "")
        out.append(f"{d['banco']} ({papel})" if papel else d["banco"])
    return ", ".join(out) if out else "—"


def _renderizar_card_oferta(col, oferta: dict, titulo: str) -> None:
    """Renderiza um cartão de oferta em uma coluna do Streamlit."""
    if not oferta:
        col.warning(f"{titulo}: oferta não encontrada.")
        return
    col.markdown(f"### {titulo}")
    col.markdown(f"**{oferta.get('emissor') or '—'}**")
    col.caption(
        f"ID {oferta['id']} · {oferta.get('numero_registro') or '—'} · "
        f"{oferta.get('tipo') or '—'}"
    )
    linhas = [
        ("Tipo", oferta.get("tipo")),
        ("Status", oferta.get("status")),
        ("Tipo FII", oferta.get("fii_tipo")),
        ("Volume registrado", _fmt_dinheiro(oferta.get("volume"))),
        ("Data registro", oferta.get("data_registro") or "—"),
        ("Regime", oferta.get("regime") or "—"),
        ("Público-alvo", oferta.get("publico_alvo") or "—"),
        ("Mercado negociação", oferta.get("mercado") or "—"),
        ("Preço emissão", _fmt_dinheiro(oferta.get("preco_emissao"))),
        ("Comissão coord./distr.", _fmt_pct(oferta.get("comissao_pct"))),
        ("Custo total da oferta", _fmt_pct(oferta.get("custo_total_pct"))),
        ("PL Fundo", _fmt_dinheiro(oferta.get("fii_pl"))),
        ("VP / Cota", _fmt_dinheiro(oferta.get("fii_vp_cota"))),
        ("Nº cotistas", oferta.get("fii_cotistas") or "—"),
        ("Taxa administração", _fmt_pct(oferta.get("fii_taxa_adm"))),
        ("Rendimento mensal", _fmt_pct(oferta.get("fii_rend_mes"))),
        ("Distribuidores", _formatar_lista_distribuidores(oferta.get("distribuidores"))),
    ]
    for label, valor in linhas:
        col.markdown(f"**{label}:** {valor}")


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
        rank_view = ranking.copy()
        rank_view["BancoLabel"] = rank_view["banco"].str.replace(
            r"\s*S[/.]?A\.?$", "", regex=True
        ).str.title().str.slice(0, 38)
        rank_view = rank_view.sort_values("qtd_ofertas")
        fig = px.bar(
            rank_view, x="qtd_ofertas", y="BancoLabel", orientation="h",
            color="qtd_ofertas", color_continuous_scale=BTG_SCALE,
            text="qtd_ofertas",
            hover_data={"banco": True, "BancoLabel": False},
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        max_n = rank_view["qtd_ofertas"].max()
        fig.update_layout(
            height=580, showlegend=False, coloraxis_showscale=False,
            xaxis={"title": "Ofertas em andamento", "range": [0, max_n * 1.18]},
            yaxis={"title": ""},
            margin=dict(l=260, r=40, t=20, b=40),
        )
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

    # Comparador lado-a-lado de 2 ofertas
    st.subheader("Comparador de ofertas")
    st.caption("Selecione duas ofertas para comparar atributos lado a lado.")
    from graph.queries import listar_ids_para_seletor, buscar_oferta_completa

    @st.cache_data(ttl=120)
    def _opcoes_ofertas(tipo: str | None):
        return pd.DataFrame(listar_ids_para_seletor(tipo=tipo))

    col_t, col_a, col_b = st.columns([1, 2, 2])
    with col_t:
        tipo_cmp = st.selectbox(
            "Filtrar tipo", ["Todos", "FII", "CRI", "CRA"],
            key="cmp_tipo",
        )
    tipo_filtro_cmp = None if tipo_cmp == "Todos" else tipo_cmp
    opcoes_df = _opcoes_ofertas(tipo_filtro_cmp)
    if opcoes_df.empty:
        st.caption("Nenhuma oferta para comparar com este filtro.")
    else:
        def _label(row):
            emi = (row.get("emissor") or "—")[:50]
            vol = row.get("volume")
            vol_str = _fmt_dinheiro(vol) if vol else "vol. a definir"
            return f"[{row['id']}] {emi} ({row['tipo']}, {vol_str})"

        opcoes_df["label"] = opcoes_df.apply(_label, axis=1)
        labels = opcoes_df["label"].tolist()
        ids = opcoes_df["id"].tolist()

        with col_a:
            idx_a = st.selectbox("Oferta A", range(len(labels)),
                                 format_func=lambda i: labels[i], key="cmp_a")
        with col_b:
            idx_b = st.selectbox("Oferta B", range(len(labels)),
                                 format_func=lambda i: labels[i],
                                 index=min(1, len(labels) - 1), key="cmp_b")

        if labels:
            oferta_a = buscar_oferta_completa(ids[idx_a])
            oferta_b = buscar_oferta_completa(ids[idx_b])
            ca, cb = st.columns(2)
            _renderizar_card_oferta(ca, oferta_a, "Oferta A")
            _renderizar_card_oferta(cb, oferta_b, "Oferta B")

    st.divider()

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
    st.caption(
        "Sinais de oportunidade/risco detectados no mercado. Podem ser gerados "
        "automaticamente por regras de negócio, pelo agente recomendador via chat, "
        "ou criados manualmente pelo time."
    )

    # ---------- Ações: detectar automático + criar manual ----------
    col_a, col_b = st.columns(2)
    with col_a:
        with st.expander("Detectar alertas automaticamente", expanded=False):
            st.caption(
                "Varre o grafo aplicando 4 regras de negócio. Idempotente — pode rodar várias vezes:"
            )
            st.markdown(
                "- **R1**: Oferta > R$ 500 mi onde BTG não está → criticidade ALTA  \n"
                "- **R2**: FII com PL > R$ 1 bi sem BTG → MEDIA  \n"
                "- **R3**: Market share BTG < 5% numa categoria → MEDIA  \n"
                "- **R4**: Comissão de oferta > 1% (acima da mediana) → BAIXA"
            )
            volume_min_mi = st.number_input(
                "Volume mínimo (R$ mi) para alertar oferta sem BTG",
                value=500, step=50, min_value=10,
            )
            if st.button("Rodar detecção agora", type="primary"):
                with st.spinner("Varrendo grafo e criando alertas..."):
                    from graph.queries import detectar_alertas_automaticos
                    stats = detectar_alertas_automaticos(
                        volume_minimo_oportunidade=volume_min_mi * 1_000_000,
                    )
                total = sum(stats.values())
                st.success(
                    f"{total} alertas criados/atualizados: "
                    + ", ".join(f"{k.split('_', 1)[0]}={v}" for k, v in stats.items())
                )
                st.cache_data.clear()
                st.rerun()

    with col_b:
        with st.expander("Criar alerta manualmente", expanded=False):
            with st.form("form_alerta_manual"):
                tipo_a = st.selectbox(
                    "Tipo",
                    ["NOVA_OFERTA", "VARIACAO_TAXA", "GAP_COMPETITIVO", "OUTRO"],
                )
                crit_a = st.selectbox("Criticidade", ["ALTA", "MEDIA", "BAIXA"])
                desc_a = st.text_area("Descrição", placeholder="Ex: Oportunidade...")
                id_oferta_a = st.text_input(
                    "ID da oferta (opcional)",
                    placeholder="Ex: 26276",
                )
                if st.form_submit_button("Criar alerta"):
                    if not desc_a.strip():
                        st.error("Descrição é obrigatória.")
                    else:
                        from graph.queries import criar_alerta
                        criar_alerta(
                            tipo=tipo_a, descricao=desc_a.strip(),
                            criticidade=crit_a,
                            id_oferta=id_oferta_a.strip() or None,
                        )
                        st.success("Alerta criado.")
                        st.cache_data.clear()
                        st.rerun()

    st.divider()

    # ---------- Lista de alertas existentes ----------
    crit = st.selectbox("Filtrar por criticidade", ["Todas", "ALTA", "MEDIA", "BAIXA"])
    filtro = None if crit == "Todas" else crit
    df = carregar_alertas(criticidade=filtro)

    if df.empty:
        st.info(
            "Nenhum alerta pendente. Use 'Detectar alertas automaticamente' acima "
            "ou pergunte ao agente no chat ('crie um alerta sobre as ofertas grandes "
            "sem BTG')."
        )
        return

    # Cards de resumo por criticidade
    c1, c2, c3 = st.columns(3)
    c1.metric("ALTA", int((df["criticidade"] == "ALTA").sum()))
    c2.metric("MEDIA", int((df["criticidade"] == "MEDIA").sum()))
    c3.metric("BAIXA", int((df["criticidade"] == "BAIXA").sum()))

    for _, row in df.iterrows():
        with st.expander(f"[{row['criticidade']}] [{row['tipo']}] {row['descricao'][:120]}"):
            st.write(f"**Criticidade:** {row['criticidade']}")
            st.write(f"**Criado em:** {row['criado_em']}")
            if row.get("id_oferta"):
                st.write(f"**Oferta relacionada:** {row['id_oferta']}")
            st.write(row["descricao"])
            if st.button("Marcar como visualizado", key=f"viz_{row['id']}"):
                queries.marcar_alerta_visualizado(row["id"])
                st.cache_data.clear()
                st.rerun()


def aba_chat() -> None:
    # Header compacto + botão limpar
    col_h, col_btn = st.columns([4, 1])
    with col_h:
        st.subheader("Pergunte ao agente")
        st.caption(
            "Exemplos: \"quem é o maior distribuidor de FII?\" · "
            "\"compare BTG e XP em CRI\" · "
            "\"qual o PL médio dos FIIs em andamento?\""
        )
    with col_btn:
        st.write("")  # alinha verticalmente
        if st.button("Limpar conversa", use_container_width=True):
            st.session_state.mensagens = []
            st.rerun()

    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    # Histórico de mensagens — flui no main, o input fica fixo (via CSS) no rodapé
    if not st.session_state.mensagens:
        st.markdown(
            "<div style='color:#7A8499; text-align:center; padding:80px 0; "
            "border:1px dashed #1F2A44; border-radius:8px; margin: 16px 0;'>"
            "Comece uma conversa — pergunte sobre ofertas, distribuidores ou tendências."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        for msg in st.session_state.mensagens:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Input fixo no rodapé da viewport (via CSS position: fixed)
    pergunta = st.chat_input("Digite sua pergunta...")
    if not pergunta:
        return

    st.session_state.mensagens.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)
    with st.chat_message("assistant"):
        with st.spinner("Analisando..."):
            try:
                resposta = perguntar(_grafo_singleton(), pergunta)
            except Exception as e:
                resposta = f"Erro ao processar a pergunta: {e}"
        st.markdown(resposta)
        st.session_state.mensagens.append({"role": "assistant", "content": resposta})
    st.rerun()


# ---------- Main ----------

def main() -> None:
    st.markdown(_CSS_BTG, unsafe_allow_html=True)

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
