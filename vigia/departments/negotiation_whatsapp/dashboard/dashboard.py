# -*- coding: utf-8 -*-
"""
Dashboard de Análise de Negociações – WhatsApp v4.1-b
----------------------------------------------------
• Todas as abas implementadas (KPIs, Negociações, Insights, Avançadas)
• Modelagens em statsmodels (OLS & Logit)
• Resumo financeiro, heat-maps, CAGR, ACF, etc.
"""
# --------------------------------------------------------------------------
# DEPENDÊNCIAS
# --------------------------------------------------------------------------
import os
import json
import textwrap
import warnings
from datetime import timedelta
import locale
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool
import statsmodels.formula.api as smf
from statsmodels.tools.sm_exceptions import PerfectSeparationError

warnings.filterwarnings("ignore", category=FutureWarning)
locale.setlocale(locale.LC_ALL, "pt_BR.UTF-8")

# --------------------------------------------------------------------------
# CONFIGS
# --------------------------------------------------------------------------
st.set_page_config(page_title="Vigia | Dashboard WhatsApp",
                   page_icon="🤖", layout="wide")
PLOTLY_TEMPLATE = "plotly_dark"

DB_URI = (
    f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('DB_HOST', 'postgres')}:5432/{os.getenv('POSTGRES_DB')}"
)
JSON_COLUMNS = ["extracted_data", "temperature_assessment", "director_decision"]

# --------------------------------------------------------------------------
# UTILITÁRIOS
# --------------------------------------------------------------------------
def fmt_moeda(valor: float) -> str:
    try:
        # 'n'           → formato numérico respeitando locale
        # replace …     → garante espaço fino depois de R$
        return f"R$\u202F{locale.format_string('%.2f', valor, grouping=True)}"
    except ValueError:
        # fallback se o locale pt_BR não existir no container
        parte_int, parte_dec = f"{valor:,.2f}".split(".")
        parte_int = parte_int.replace(",", ".")      # 189.873
        return f"R$\u202F{parte_int},{parte_dec}"    # 189.873,87
    
def find_col(df: pd.DataFrame, keys: list[str]) -> str | None:
    for k in keys:
        for c in df.columns:
            if k.lower() in c.lower():
                return c
    return None

def wrap_text(s: str, width: int = 60) -> str:
    """Trunca texto longo e acrescenta reticências."""
    if not isinstance(s, str) or len(s) <= width:
        return s
    return textwrap.shorten(s, width, placeholder="…")

@st.cache_data(ttl=timedelta(minutes=5), show_spinner="🔄 Carregando dados…")
def read_whatsapp_data() -> pd.DataFrame:
    """Consulta somente conversas de WhatsApp e faz o parsing/flatten."""
    engine = create_engine(DB_URI, poolclass=QueuePool, pool_size=3)
    sql = """
      SELECT a.id, a.analysable_id, c.remote_jid, a.created_at,
             a.extracted_data, a.temperature_assessment, a.director_decision
      FROM analyses a
      JOIN conversations c ON CAST(a.analysable_id AS UUID) = c.id
      WHERE c.remote_jid LIKE '%%@s.whatsapp.net%%'
    """
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return df

    df.rename(columns={"remote_jid": "conversation_jid"}, inplace=True)
    df["created_at"] = pd.to_datetime(df["created_at"])

    # ---- JSON → colunas ----
    def _safe(x):
        if isinstance(x, dict):
            return x
        if isinstance(x, str) and x.strip():
            try:
                return json.loads(x)
            except json.JSONDecodeError:
                return {}
        return {}
    for col in JSON_COLUMNS:
        if col not in df:
            continue
        flat = pd.json_normalize(df[col].apply(_safe), sep="_")
        flat.columns = [f"{col.split('_')[0]}_{c}" for c in flat.columns]
        df.drop(columns=[col], inplace=True)
        df = pd.concat([df, flat], axis=1)

    # ---- valores financeiros ----
    orig_col = find_col(df, ["valores_valor_total", "valores_valor_original_divida"])
    fin_col  = find_col(df, ["valores_valor_final_acordado"])

    for target, source in [("valor_original", orig_col), ("valor_final", fin_col)]:
        serie = df[source] if source else pd.Series(np.nan, index=df.index)
        df[target] = pd.to_numeric(serie, errors="coerce").fillna(0)

    st_col = find_col(df, ["extracted_status"])
    if st_col is not None:
        fech = df[st_col].str.contains("Acordo Fechado", na=False)
        df.loc[fech & (df["valor_final"] == 0), "valor_final"] = df["valor_original"]

    df["desconto_reais"] = df["valor_original"] - df["valor_final"]
    df["desconto_pct"]   = (df["desconto_reais"] / df["valor_original"] * 100
                            ).replace([np.inf, -np.inf], 0).fillna(0)
    return df

def compound_growth(series: pd.Series, freq="D") -> float:
    if series.empty or series.iloc[0] == 0:
        return np.nan
    delta = (series.index[-1] - series.index[0]).days
    if freq == "M":
        delta /= 30.44
    elif freq == "Y":
        delta /= 365.25
    return ((series.iloc[-1] / series.iloc[0]) ** (1 / max(delta, 1)) - 1) * 100

# --------------------------------------------------------------------------
# MODELAGEM
# --------------------------------------------------------------------------
def sm_ols_valor(df: pd.DataFrame, temp_col: str | None):
    dfm = df[(df.valor_original > 0) & (df.valor_final > 0)].copy()
    if dfm.empty:
        return None
    formula = "valor_final ~ valor_original"
    if temp_col:
        formula += f" + C({temp_col})"
    return smf.ols(formula, data=dfm).fit()

def sm_logit_status(df: pd.DataFrame, st_col: str):
    dfm = df[[st_col, "valor_original", "desconto_pct"]].dropna().copy()
    dfm["y"] = dfm[st_col].eq("Acordo Fechado").astype(int)
    if dfm["y"].nunique() < 2 or len(dfm) < 20:
        return None
    try:
        return smf.logit("y ~ valor_original + desconto_pct", data=dfm).fit(disp=False)
    except PerfectSeparationError:
        return None

# --------------------------------------------------------------------------
# ABA 1 – KPIs
# --------------------------------------------------------------------------
def tab_performance_kpis(df: pd.DataFrame):
    st.subheader("🚀 KPIs de Performance e Automação")

    # ---------- métricas principais ----------
    act_col   = find_col(df, ["director_acao_executada_type"])
    alert_col = find_col(df, ["director_acao_executada_name"])
    df["_ia_flag"] = df[act_col].notna().astype(int) if act_col else 0

    total      = len(df)
    acoes      = df["_ia_flag"].sum()
    alertas    = df[alert_col].eq("AlertarSupervisor").sum() if alert_col else 0
    atividades = acoes - alertas
    taxa_auto  = 100 * acoes / total if total else 0

    # ---------- cards ----------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de Análises", total)
    c2.metric("Taxa de Ação da IA", f"{taxa_auto:.1f}%")
    c3.metric("Atividades Criadas", atividades)
    c4.metric("Alertas ao Supervisor", alertas)

    st.divider()
    st.subheader("Evolução de Volume × Automação")

    # ---------- agregação corrigida ----------
    ts = (
        df.set_index("created_at")
          .resample("D")
          .agg(analises=("id", "count"),
               ia_sum=("_ia_flag", "sum"))
          .assign(taxa=lambda d: 100 * d.ia_sum / d.analises)
          .reset_index()
    )

    # ---------- gráfico ----------
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=ts.created_at, y=ts.analises,
                         name="Análises", marker_color="#1f77b4"),
                  secondary_y=False)
    fig.add_trace(go.Scatter(x=ts.created_at, y=ts.taxa,
                             name="Taxa de IA (%)",
                             mode="lines+markers", marker_color="#ff7f0e"),
                  secondary_y=True)
    fig.update_layout(template=PLOTLY_TEMPLATE,
                      legend_orientation="h", legend_y=1.02)
    fig.update_yaxes(title_text="Análises", secondary_y=False)
    fig.update_yaxes(title_text="Taxa de IA (%)", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------
# ABA 2 – NEGOCIAÇÕES
# --------------------------------------------------------------------------
def tab_negotiation_analysis(df: pd.DataFrame):
    st.subheader("📈 Análise de Negociações")

    temp_col = find_col(df, ["temperature_temperatura_final"])
    st_col   = find_col(df, ["extracted_status"])

    col1, col2 = st.columns(2)
    # Heat-map Temperatura × Status
    if temp_col and st_col:
        with col1:
            heat = (df.groupby([temp_col, st_col]).size().unstack(fill_value=0))
            heat.columns = [wrap_text(c, 30) for c in heat.columns]
            fig = px.imshow(heat, text_auto=True, aspect="auto",
                            labels={"x":"Status", "y":"Temperatura", "color":"Contagem"},
                            title="Temperatura vs. Status", template=PLOTLY_TEMPLATE,
                            color_continuous_scale="Blues")
            st.plotly_chart(fig, use_container_width=True)

    # Desconto % por Temperatura
    if temp_col and "desconto_pct" in df:
        with col2:
            data = df[df.valor_original > 0]
            fig = px.box(data, x=temp_col, y="desconto_pct",
                         points="all", notched=True,
                         labels={temp_col:"Temperatura", "desconto_pct":"Desconto (%)"},
                         title="Desconto por Temperatura", template=PLOTLY_TEMPLATE,
                         color=temp_col)
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Resumo Financeiro")

    fin = df[df.valor_original > 0]
    if fin.empty:
        st.info("Sem dados financeiros no período.")
        return

    total_orig = fin.valor_original.sum()
    total_fin  = fin.valor_final.sum()
    total_desc = fin.desconto_reais.sum()
    taxa_recup = 100*total_fin/total_orig if total_orig else 0

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Valor Original",  fmt_moeda(total_orig))
    with col2:
        st.metric("Valor Acordado",  fmt_moeda(total_fin))
    col3, col4 = st.columns(2)
    with col3:
        st.metric("Desconto Total",  fmt_moeda(total_desc))
    with col4:
        st.metric("Taxa de Recuperação", f"{taxa_recup:.1f}%")

# --------------------------------------------------------------------------
# ABA 3 – INSIGHTS DE CLIENTE
# --------------------------------------------------------------------------
def tab_customer_insights(df: pd.DataFrame):
    st.subheader("💬 Insights dos Clientes")
    pt_col = find_col(df, ["pontos_chave_cliente"])
    if not pt_col:
        st.info("Tabela sem a coluna de pontos-chave.")
        return
    pontos = (df[pt_col].dropna().explode().str.strip()
              .replace("", np.nan).dropna())
    if pontos.empty:
        st.info("Nenhum ponto-chave disponível.")
        return

    top = pontos.value_counts().nlargest(15).reset_index()
    top.columns = ["ponto", "freq"]
    top["label"] = top["ponto"].apply(lambda x: wrap_text(x, 80))

    fig = px.bar(top, y="label", x="freq", orientation="h", text="freq",
                 labels={"label":"Ponto-chave", "freq":"Frequência"},
                 template=PLOTLY_TEMPLATE,
                 title="Top 15 Pontos-Chave citados por Clientes",
                 hover_name="ponto")
    fig.update_layout(yaxis={"categoryorder":"total ascending"})
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------
# ABA 4 – ANÁLISES AVANÇADAS
# --------------------------------------------------------------------------
def tab_advanced_analytics(df: pd.DataFrame):
    st.subheader("📊 Análises Avançadas")

    temp_col = find_col(df, ["temperature_temperatura_final"])
    st_col   = find_col(df, ["extracted_status"])

    # ---------- Regressão OLS ----------
    st.markdown("### Regressão OLS – Valor Final")
    ols = sm_ols_valor(df, temp_col)
    if ols:
        st.write(ols.summary())
    else:
        st.info("Amostra insuficiente para OLS.")

    # ---------- Logit ----------
    st.markdown("### Logit – Probabilidade de Fechar")
    if st_col:
        logit = sm_logit_status(df, st_col)
        if logit:
            st.write(logit.summary())
        else:
            st.info("Logit não pôde ser ajustado (amostra ou separação perfeita).")
    else:
        st.info("Sem coluna de status para Logit.")

    st.divider()
    # ---------- Correlação ----------
    st.markdown("#### Correlação de KPIs")
    num = df[["valor_original", "valor_final", "desconto_pct"]].copy()
    if num.dropna(axis=1, how="all").shape[1] >= 2:
        corr = num.corr().round(2)
        fig = px.imshow(corr, text_auto=True, color_continuous_scale="RdBu_r",
                        template=PLOTLY_TEMPLATE)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    # ---------- Série Temporal ----------
    st.markdown("#### Volume Diário + CAGR")
    ts = df.set_index("created_at").resample("D")["id"].count()
    if len(ts) >= 2:
        cagrd = compound_growth(ts)
        cagrm = compound_growth(ts.resample("M").sum(), "M")
        c1, c2 = st.columns(2)
        c1.metric("CAGR Diário",   f"{cagrd:.2f}%/dia" if not np.isnan(cagrd) else "N/A")
        c2.metric("CAGR Mensal",   f"{cagrm:.2f}%/mês" if not np.isnan(cagrm) else "N/A")

        if len(ts) >= 5:
            lags = range(1, min(31, len(ts)))
            acf = [ts.autocorr(l) for l in lags]  # noqa: E741
            fig = go.Figure(go.Bar(x=list(lags), y=acf))
            fig.update_layout(template=PLOTLY_TEMPLATE,
                              title="Autocorrelação (até 30 lags)",
                              xaxis_title="Lag (dias)", yaxis_title="ACF")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Série temporal muito curta para CAGR/ACF.")


# --------------------------------------------------------------------------
# ABA 5 – TABELAS
# --------------------------------------------------------------------------
def tab_tables(df: pd.DataFrame):
    st.subheader("📑 Tabela Detalhada")

    # ❶ Colunas visíveis e títulos amigáveis
    vis_map = {
        "conversation_jid"            : "JID",
        "created_at"                  : "Data",
        "valor_original"              : "Valor Original",
        "valor_final"                 : "Valor Acordado",
        "desconto_reais"              : "Desconto (R$)",
        "desconto_pct"                : "Desconto (%)",
        "extracted_status"            : "Status",
        "temperature_temperatura_final": "Temperatura",
        "pontos_chave_cliente"        : "Pontos‑chave",
    }

    # ❷ Seleciona apenas o que existe no DataFrame
    cols = [c for c in vis_map if c in df.columns]
    data = df[cols].rename(columns=vis_map).copy()

    # ❸ Formatação numérica
    moeda_cols = ["Valor Original", "Valor Acordado", "Desconto (R$)"]
    for c in moeda_cols:
        if c in data:
            data[c] = data[c].apply(fmt_moeda)

    if "Desconto (%)" in data:
        data["Desconto (%)"] = data["Desconto (%)"].round(1)

    # ❹ Exibe com data_editor (editável = False)
    st.data_editor(
        data,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        disabled=True,               
        column_config={
            "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Desconto (%)": st.column_config.NumberColumn(format="%.1f %%"),
        },
    )
    
# --------------------------------------------------------------------------
# APP
# --------------------------------------------------------------------------
def main():
    st.title("🤖 Dashboard de Negociações | WhatsApp")
    df_raw = read_whatsapp_data()
    if df_raw.empty:
        st.warning("Nenhum dado encontrado para o canal WhatsApp.")
        return

    # ----- Filtros -----
    st.sidebar.header("⚙️ Filtros")
    min_d, max_d = df_raw.created_at.min().date(), df_raw.created_at.max().date()
    inicio, fim = st.sidebar.date_input("Período", (min_d, max_d),
                                        min_value=min_d, max_value=max_d)
    if inicio > fim:
        st.sidebar.error("Data inicial > final")
        return
    df = df_raw[(df_raw.created_at.dt.date >= inicio) &
                (df_raw.created_at.dt.date <= fim)].copy()

    for lbl, keys in [("Status", ["extracted_status"]),
                      ("Temperatura", ["temperature_temperatura_final"])]:
        col = find_col(df, keys)
        if col:
            opts = sorted(df[col].dropna().unique())
            sel  = st.sidebar.multiselect(f"Filtrar por {lbl}", opts, default=opts)
            df   = df[df[col].isin(sel)]

    if df.empty:
        st.info("Nenhum registro para os filtros selecionados.")
        return

    # ----- Abas -----
    tabs = st.tabs([" KPIs de Performance ", " Análise de Negociações ",
                " Insights do Cliente ", " Análises Avançadas ",
                " Tabelas "])
    with tabs[0]: 
        tab_performance_kpis(df)
    with tabs[1]: 
        tab_negotiation_analysis(df)
    with tabs[2]: 
        tab_customer_insights(df)
    with tabs[3]: 
        tab_advanced_analytics(df)
    with tabs[4]:
        tab_tables(df)

if __name__ == "__main__":
    main()
