# -*- coding: utf-8 -*-
"""
Dashboard de Análises – v2.3
----------------------------
• Pool de conexões + SELECT enxuto
• Normalização JSON automática
• Localização de colunas por substring (à prova de prefixos)
• Métricas e visualizações interativas
• Busca e consolidação de colunas de valor robusta
"""

# ------------------------------------------------------------------ #
# DEPENDÊNCIAS
# ------------------------------------------------------------------ #
import os
import json
import warnings
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

# libs analíticas
warnings.filterwarnings("ignore", category=FutureWarning)
try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LinearRegression
except ImportError:
    KMeans = StandardScaler = LinearRegression = None

# ------------------------------------------------------------------ #
# CONFIG STREAMLIT
# ------------------------------------------------------------------ #
st.set_page_config(
    page_title="Vigia | Dashboard de Análises",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------ #
# VARIÁVEIS DE AMBIENTE / DB
# ------------------------------------------------------------------ #
DB_URI = (
    f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('DB_HOST', 'postgres')}:5432/{os.getenv('POSTGRES_DB')}"
)
JSON_COLUMNS = ("extracted_data", "temperature_assessment", "director_decision")

# ------------------------------------------------------------------ #
# HELPERS
# ------------------------------------------------------------------ #
def find_col(df: pd.DataFrame, substrings: list[str]) -> str | None:
    """Busca a primeira coluna que contém qualquer uma das substrings (case-insensitive)."""
    for sub in substrings:
        sub = sub.lower()
        for col in df.columns:
            if sub in col.lower():
                return col
    return None


@st.cache_data(ttl="10m", show_spinner=True)
def read_data() -> pd.DataFrame:
    engine = create_engine(DB_URI, poolclass=QueuePool, pool_size=3, max_overflow=2)
    with engine.connect() as conn:
        df = pd.read_sql(
            f"SELECT id, conversation_id, created_at, {', '.join(JSON_COLUMNS)} FROM analyses",
            conn,
        )

    df["id"] = df["id"].astype(str)
    df["conversation_id"] = df["conversation_id"].astype(str)
    df["created_at"] = pd.to_datetime(df["created_at"])

    # ------- normalização JSON --------
    for col in JSON_COLUMNS:
        if col not in df.columns:
            continue

        def _to_dict(x):
            if isinstance(x, (dict, list)):
                return x
            if isinstance(x, str) and x.strip():
                try:
                    return json.loads(x)
                except json.JSONDecodeError:
                    return {}
            return {}

        parsed = df[col].apply(_to_dict)
        if parsed.apply(bool).any():
            flat = pd.json_normalize(parsed, sep="_")
            # Adiciona um prefixo para evitar colisões de nome
            flat.columns = [f"{col.split('_')[0]}_{c}" for c in flat.columns]
            df = pd.concat([df.drop(columns=[col]), flat], axis=1)

    # --- INÍCIO DA CORREÇÃO: Consolidação de Colunas de Valor ---
    # Busca por vários nomes possíveis para as colunas de valor
    orig_col = find_col(df, ["valores_valor_total", "valores_valor_cobrado", "valores_valor_original", "valor_ressarcimento", "saldo_excedente_franquia"])
    fin_col = find_col(df, ["valores_valor_final", "valores_valor_acordado"])

    # Cria colunas consolidadas e padronizadas
    df["valor_original_consolidado"] = pd.to_numeric(df[orig_col], errors="coerce").fillna(0) if orig_col else 0
    df["valor_final_consolidado"] = pd.to_numeric(df[fin_col], errors="coerce").fillna(0) if fin_col else df["valor_original_consolidado"]

    # Calcula métricas de desconto usando as colunas consolidadas
    df["discount_reais"] = df["valor_original_consolidado"] - df["valor_final_consolidado"]
    df["discount_pct"] = np.where(df["valor_original_consolidado"] > 0, df["discount_reais"] / df["valor_original_consolidado"] * 100, 0)
    # --- FIM DA CORREÇÃO ---
    
    return df


# ------------------------------------------------------------------ #
# FILTROS
# ------------------------------------------------------------------ #
def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.title("⚙️ Filtros")

    min_d, max_d = df["created_at"].min().date(), df["created_at"].max().date()
    start, end = st.sidebar.date_input("Período", (min_d, max_d), min_d, max_d)
    mask = df["created_at"].between(pd.to_datetime(start), pd.to_datetime(end)+pd.Timedelta(days=1))
    
    # Adapta a busca de colunas para usar a nova assinatura de find_col
    for lbl, key in [("Status", ["extracted_status"]), ("Temperatura", ["temperature_temperatura_final"])]:
        col = find_col(df, key)
        if col:
            opts = sorted(df[col].dropna().unique())
            sel = st.sidebar.multiselect(lbl, opts, default=opts)
            if sel:
                mask &= df[col].isin(sel)

    return df[mask].copy()

# ------------------------------------------------------------------ #
# ABA: ANALYTICS
# ------------------------------------------------------------------ #
def tab_analytics(df: pd.DataFrame):
    st.subheader("📈 Analytics Avançado")

    # USA AS NOVAS COLUNAS CONSOLIDADAS
    orig, fin = "valor_original_consolidado", "valor_final_consolidado"
    
    if df[orig].sum() == 0:
        st.info("Colunas de valor não encontradas ou zeradas no período.")
        return
    if df.empty:
        st.info("Sem dados após filtros.")
        return

    # ---------------- BOX PLOT por quartil ----------------
    st.markdown("##### Distribuição do % de desconto por quartis do valor original")
    # Garante que há valores distintos para o qcut
    if df[orig].nunique() >= 4:
        df["orig_quartil"] = pd.qcut(df[orig][df[orig] > 0], 4, labels=["Q1 (baixo)", "Q2", "Q3", "Q4 (alto)"])
        fig_box = px.box(
            df.dropna(subset=['orig_quartil']), x="orig_quartil", y="discount_pct",
            labels={"orig_quartil":"Quartil do Valor Original", "discount_pct":"% de Desconto"},
            color="orig_quartil", title="% de desconto vs Quartil do ticket"
        )
        st.plotly_chart(fig_box, use_container_width=True)
    else:
        st.warning("Dados insuficientes para análise de quartis.")

    # ---------------- REGRESSÃO discount_pct ~ valor_original ----------------
    st.markdown("##### Regressão linear: % desconto ~ valor original")
    X = df[[orig]].values
    y = df["discount_pct"].values
    if len(np.unique(X)) > 1 and LinearRegression:
        model = LinearRegression().fit(X, y)
        slope = model.coef_[0]
        r2 = model.score(X, y)

        fig_reg = px.scatter(
            df, x=orig, y="discount_pct",
            trendline="ols", trendline_color_override="red",
            labels={orig:"Valor Original (R$)", "discount_pct":"% Desconto"},
            title=f"Slope ≈ {slope:.4f} (p.p / R$) · R² = {r2:.2f}"
        )
        st.plotly_chart(fig_reg, use_container_width=True)
    else:
        st.warning("Dados insuficientes para regressão.")

    # ---------------- K‑MEANS Cluster ----------------
    st.markdown("##### Clusterização K‑means (k=3)")
    temp_col = find_col(df, ["temperature_temperatura_final"])
    if KMeans and temp_col:
        temp_map = {"negativo":-1, "neutro":0, "positivo":1}
        temp_num = df[temp_col].str.lower().map(temp_map).fillna(0)
        cluster_df = df[[orig, fin]].copy()
        cluster_df["temp_num"] = temp_num

        scaler = StandardScaler()
        scaled = scaler.fit_transform(cluster_df)
        km = KMeans(n_clusters=3, n_init="auto", random_state=42).fit(scaled)
        df["cluster"] = km.labels_.astype(str)

        counts = df["cluster"].value_counts().sort_index()
        c1, c2, c3 = st.columns(3)
        for i, c in enumerate([c1, c2, c3]):
            c.metric(f"Cluster {i}", counts.get(str(i), 0))

        fig_clu = px.scatter(
            df, x=orig, y=fin, color="cluster",
            hover_name="conversation_id",
            labels={orig:"Valor Original (R$)", fin:"Valor Acordado (R$)"},
            title="Clusters em espaço de valores"
        )
        st.plotly_chart(fig_clu, use_container_width=True)
    else:
        st.info("scikit‑learn indisponível ou coluna 'temperatura' ausente – cluster não gerado.")

    st.divider()

    # ---------------- Outras análises rápidas ----------------
    st.markdown("##### Outras relações")

    # Regressão discount_reais ~ valor_original
    if LinearRegression:
        X2, y2 = df[[orig]].values, df["discount_reais"].values
        if len(np.unique(X2)) > 1:
            m2 = LinearRegression().fit(X2, y2)
            st.caption(f"**discount_reais ~ valor_original** → slope ≈ {m2.coef_[0]:.2f} (R$ de desconto por R$ no ticket) · R² = {m2.score(X2, y2):.2f}")

    # Box‑plot %desconto por temperatura
    if temp_col:
        st.plotly_chart(
            px.box(
                df, x=temp_col, y="discount_pct",
                title="% de desconto por Temperatura",
                labels={temp_col:"Temperatura", "discount_pct":"% Desconto"},
                color=temp_col
            ), use_container_width=True
        )

# ------------------------------------------------------------------ #
# ABA: VISÃO GERAL
# ------------------------------------------------------------------ #
def tab_overview(df: pd.DataFrame):
    st.subheader("📊 Visão Geral")

    status_col = find_col(df, ["extracted_status"])
    temp_col = find_col(df, ["temperature_temperatura_final"])

    total = len(df)
    success = (
        df[status_col].str.contains(r"acordo fechado|sucesso|resolvido|concluída", case=False, na=False).sum()
        if status_col else 0
    )
    rate = (success / total * 100) if total else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total de Análises", total)
    c2.metric("Negociações com Sucesso", success)
    c3.metric("Taxa de Sucesso", f"{rate:.1f}%")

    st.divider()

    # Distribuição de status
    if status_col and not df[status_col].dropna().empty:
        counts = df[status_col].value_counts()
        fig = px.bar(
            counts, x=counts.index, y=counts.values, text_auto=True,
            title="Distribuição de Status", color_discrete_sequence=px.colors.sequential.Blues_r
        )
        fig.update_layout(xaxis_title=None, yaxis_title="Contagem", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Séries temporais
    ts = df.set_index("created_at").resample("D").size()
    fig_ts = px.area(
        ts, x=ts.index, y=ts.values, markers=True,
        title="Volume de Análises por Dia"
    )
    fig_ts.update_layout(xaxis_title="Data", yaxis_title="Qtd.")
    st.plotly_chart(fig_ts, use_container_width=True)

    # Heat‑map Temperatura × Status
    if status_col and temp_col and not df[status_col].dropna().empty and not df[temp_col].dropna().empty:
        pivot = df.groupby([temp_col, status_col]).size().unstack(fill_value=0)
        fig_hm = px.imshow(
            pivot, text_auto=True, aspect="auto",
            color_continuous_scale="Viridis", title="Heat‑map: Temperatura × Status"
        )
        st.plotly_chart(fig_hm, use_container_width=True)

# ------------------------------------------------------------------ #
# ABA: FINANCEIRO
# ------------------------------------------------------------------ #
def tab_finance(df: pd.DataFrame):
    st.subheader("💰 Indicadores Financeiros")

    # USA AS NOVAS COLUNAS CONSOLIDADAS
    orig_col, fin_col = "valor_original_consolidado", "valor_final_consolidado"

    if df[orig_col].sum() == 0:
        st.info("Colunas de valores não encontradas ou zeradas no período.")
        return

    df_val = df[df[orig_col] > 0]
    if df_val.empty:
        st.info("Não há registros financeiros no período.")
        return

    orig_total = df_val[orig_col].sum()
    fin_total = df_val[fin_col].sum()
    desc_total = orig_total - fin_total
    rec_rate = (fin_total / orig_total * 100) if orig_total else 0
    avg_ticket = df_val[orig_col].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valor Original (Σ)", f"R$ {orig_total:,.2f}")
    c2.metric("Valor Acordado (Σ)", f"R$ {fin_total:,.2f}")
    c3.metric("Desconto (Σ)", f"R$ {desc_total:,.2f}")
    c4.metric("Recuperação (%)", f"{rec_rate:.1f}%")
    st.caption(f"Ticket médio: **R$ {avg_ticket:,.2f}**")

    st.divider()
    # Scatter
    fig_scatter = px.scatter(
        df_val, x=orig_col, y=fin_col,
        color=find_col(df, ["temperature_temperatura_final"]),
        hover_name="conversation_id",
        labels={orig_col: "Original (R$)", fin_col: "Acordado (R$)"},
        title="Valor Original × Valor Acordado"
    )
    max_axis = df_val[orig_col].max()
    fig_scatter.add_shape(type="line", x0=0, y0=0, x1=max_axis, y1=max_axis,
                          line=dict(color="gray", dash="dash"))
    st.plotly_chart(fig_scatter, use_container_width=True)

    # Histograma
    st.plotly_chart(
        px.histogram(
            df_val, x="discount_pct", nbins=25,
            labels={"discount_pct": "% de Desconto"},
            title="Distribuição da % de Desconto"
        ),
        use_container_width=True,
    )

    # Box‑plot por status
    status_col = find_col(df, ["extracted_status"])
    if status_col and not df_val[status_col].dropna().empty:
        st.plotly_chart(
            px.box(
                df_val, x=status_col, y="discount_pct",
                labels={status_col: "Status", "discount_pct": "% de Desconto"},
                title="Desconto (%) por Status"
            ),
            use_container_width=True,
        )

# ------------------------------------------------------------------ #
# ABA: OPERACIONAL
# ------------------------------------------------------------------ #
def tab_ops(df: pd.DataFrame):
    st.subheader("⚙️ Performance Operacional")

    # Próximas ações
    action_col = find_col(df, ["director_proxima_acao_sugerida"])
    if action_col and not df[action_col].dropna().empty:
        acao = df[action_col].value_counts()
        st.plotly_chart(
            px.bar(
                acao, x=acao.index, y=acao.values, text_auto=True,
                title="Próximas Ações Sugeridas",
                color_discrete_sequence=px.colors.sequential.Purples_r,
            ),
            use_container_width=True,
        )

    # Tendência
    tend_col = find_col(df, ["temperature_tendencia"])
    if tend_col and not df[tend_col].dropna().empty:
        tend = df[tend_col].value_counts()
        st.plotly_chart(
            px.pie(
                tend, names=tend.index, values=tend.values, hole=0.45,
                title="Tendência das Conversas",
                color_discrete_sequence=px.colors.qualitative.Pastel,
            ),
            use_container_width=True,
        )

    # Correlação numérica
    num = df.select_dtypes("number")
    if len(num.columns) >= 2:
        corr = num.corr(numeric_only=True)
        st.plotly_chart(
            px.imshow(
                corr, text_auto=".2f", aspect="auto",
                color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                title="Correlação entre Métricas Numéricas",
            ),
            use_container_width=True,
        )

# ------------------------------------------------------------------ #
# ABA: INSIGHTS DE CLIENTE
# ------------------------------------------------------------------ #
def tab_customer(df: pd.DataFrame):
    st.subheader("💬 Pontos-chave do Cliente")

    pontos_col = find_col(df, ["extracted_pontos_chave_cliente"])
    if not pontos_col:
        st.warning("Coluna de pontos-chave não localizada.")
        return

    # explode e limpa
    pontos = (
        df[pontos_col]
        .dropna()
        .explode()
        .str.strip()
        .replace("", pd.NA)
        .dropna()
    )

    if pontos.empty:
        st.info("Nenhum ponto-chave no período.")
        return

    # ---------------- KPIs ----------------
    total_mensagens = len(pontos)
    itens_unicos = pontos.nunique()
    top_n = pontos.value_counts().head(15)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total de Pontos", f"{total_mensagens}")
    c2.metric("Tópicos Únicos", f"{itens_unicos}")
    if not top_n.empty:
        c3.metric("Top 1", f"{top_n.index[0]} ({top_n.iloc[0]})")
    
    st.divider()

    # ---------------- Gráfico ----------------
    if not top_n.empty:
        fig = px.bar(
            top_n[::-1], # inverte p/ barra horizontal
            x=top_n[::-1].values,
            y=top_n[::-1].index,
            orientation="h",
            labels={"y": "Tópico", "x": "Frequência"},
            title="Top 15 Pontos-chave mais citados",
            text_auto=True,
            color_discrete_sequence=px.colors.sequential.Blues_r,
        )
        fig.update_layout(yaxis=dict(dtick=1))
        st.plotly_chart(fig, use_container_width=True)

    # ---------------- Tabela ----------------
    st.markdown("#### Detalhe por conversa")
    display_cols = ["conversation_id"]
    for col_key in [
        ["extracted_status"],
        ["temperature_temperatura_final"],
        ["valor_original_consolidado"],
        ["valor_final_consolidado"],
        [pontos_col]
    ]:
        found_col = find_col(df, col_key)
        if found_col and found_col not in display_cols:
            display_cols.append(found_col)

    table = df[display_cols].copy()
    if pontos_col in table.columns:
        table[pontos_col] = table[pontos_col].apply(
            lambda lst: ", ".join(lst) if isinstance(lst, list) else lst
        )

    st.dataframe(table, use_container_width=True)

# ------------------------------------------------------------------ #
# MAIN
# ------------------------------------------------------------------ #
def main():
    st.title("🤖 Dashboard de Conversas – Vigia")
    df_raw = read_data()
    if df_raw.empty:
        st.warning("Sem dados disponíveis no banco de dados.")
        return
        
    df = apply_filters(df_raw)

    tabs = st.tabs(["Visão Geral", "Financeiro 💲", "Operacional ⚙️", "Clientes 💬", "Analytics 📊"])
    with tabs[0]:
        tab_overview(df)
    with tabs[1]:
        tab_finance(df)
    with tabs[2]:
        tab_ops(df)
    with tabs[3]:
        tab_customer(df)
    with tabs[4]:
        tab_analytics(df)


if __name__ == "__main__":
    main()