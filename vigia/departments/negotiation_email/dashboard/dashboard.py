# -*- coding: utf-8 -*-
"""
Dashboard de Análise de Negociações – E‑mail v3.3
-------------------------------------------------
Abas:
• 📊 Resumos  — KPIs gerais + métricas financeiras
• 🔍 Análises — gráficos e modelos estatísticos
• 📑 Tabelas  — explorador de dados detalhado + sumarizações
"""
# --------------------------------------------------------------------------
# DEPENDÊNCIAS
# --------------------------------------------------------------------------
import os
import json
import textwrap
import warnings
import itertools
from datetime import timedelta

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

try:
    from lifelines import KaplanMeierFitter
except ImportError:
    KaplanMeierFitter = None
try:
    import networkx as nx
except ImportError:
    nx = None
try:
    from wordcloud import WordCloud
except ImportError:
    WordCloud = None

warnings.filterwarnings("ignore", category=FutureWarning)
st.set_page_config(page_title="Vigia | Dashboard E‑mail",
                   page_icon="📧", layout="wide")

PLOTLY_TEMPLATE = "plotly_dark"
DB_URI = (
    f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('DB_HOST', 'postgres')}:5432/{os.getenv('POSTGRES_DB')}"
)
JSON_COLUMNS = [
    "extracted_data", 
    "temperature_assessment", 
    "director_decision",
    "kpis",
    "advisor_recommendation",
    "context",
    "formal_summary"
]

# --------------------------------------------------------------------------
# UTILITÁRIOS
# --------------------------------------------------------------------------
def wrap_text(s: str, width: int = 80) -> str:
    return s if not isinstance(s, str) or len(s) <= width else textwrap.shorten(s, width, "…")

def find_col(df: pd.DataFrame, keys: list[str]) -> str | None:
    for k in keys:
        for c in df.columns:
            if k.lower() in c.lower():
                return c
    return None

@st.cache_data(ttl=timedelta(minutes=5), show_spinner="🔄 Carregando dados do banco…")
def read_email_data() -> pd.DataFrame:
    engine = create_engine(DB_URI, poolclass=QueuePool, pool_size=3)
    query = """
      SELECT a.id AS analysis_id,
             a.analysable_id,
             et.subject,
             et.participants,
             et.first_email_date,
             et.last_email_date,
             (SELECT COUNT(*) FROM email_messages WHERE thread_id = et.id) AS email_count,
             a.created_at,
             a.extracted_data,
             a.temperature_assessment,
             a.director_decision,
             a.kpis,
             a.advisor_recommendation,
             a.context,
             a.formal_summary
        FROM analyses a
        JOIN email_threads et ON CAST(a.analysable_id AS UUID) = et.id
       WHERE a.analysable_type = 'email_thread';
    """
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return df

    # Datas & tempo de resolução
    for c in ["created_at", "first_email_date", "last_email_date"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df.dropna(subset=["first_email_date", "last_email_date"], inplace=True)
    df["tempo_resolucao_dias"] = (
        (df["last_email_date"] - df["first_email_date"]).dt.total_seconds() / 86_400
    ).round(1)

    # Parse/flatten JSON
    df_proc = df.copy()
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
        if col not in df_proc:
            continue
        nested = df_proc[col].apply(_safe).tolist()
        flat = pd.json_normalize(nested, sep="_").set_index(df_proc.index)
        prefix_map = {
            "extracted_data": "extracted",
            "temperature_assessment": "temperature",
            "director_decision": "director",
            "context": "pipedrive",
            "advisor_recommendation": "advisor",
            "formal_summary": "summary"
        }
        prefix = prefix_map.get(col, col.split('_')[0])
        flat.columns = [f"{prefix}_{c}" for c in flat.columns]
        
        df_proc = df_proc.join(flat)

    df_proc.drop(columns=JSON_COLUMNS, inplace=True, errors="ignore")

    # Valor da proposta
    df_proc["valor_proposta"] = np.nan
    for c in [c for c in df_proc.columns if "proposta_valor" in c]:
        s = df_proc[c].astype(str).str.extract(r"(\d[\d.,]*)")[0]
        pat_thou = r"(?<=\d)[.,](?=\d{3}(?:\D|$))"
        nums = (
            s.str.replace(r"[^\d,.-]", "", regex=True)
             .str.replace(pat_thou, "", regex=True)
             .str.replace(",", ".")
             .astype(float)
        )
        df_proc["valor_proposta"].fillna(nums, inplace=True)

    return df_proc

# --------------------------------------------------------------------------
# ABA 1 – RESUMOS
# --------------------------------------------------------------------------
def tab_resumos(df: pd.DataFrame):
    st.subheader("📊 KPIs & Métricas Financeiras")

    total_threads = df["analysable_id"].nunique()
    avg_emails    = df["email_count"].mean()
    avg_res_days  = df["tempo_resolucao_dias"].mean()

    estatus       = find_col(df, ["status_acordo"])
    valor_cols    = df["valor_proposta"].dropna()
    total_valor   = valor_cols.sum()
    ticket_medio  = valor_cols.mean()

    fechados      = df[estatus].eq("Acordo Fechado").sum() if estatus else 0
    taxa_fech     = 100 * fechados / total_threads if total_threads else 0
    valor_fech    = df.loc[df[estatus].eq("Acordo Fechado") if estatus else [], "valor_proposta"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Threads analisadas",           total_threads)
    c2.metric("Média de e‑mails / thread", f"{avg_emails:,.1f}")
    c3.metric("Tempo médio de resolução",  f"{avg_res_days:,.1f} dias")
    c4.metric("Taxa de acordo fechado",    f"{taxa_fech:,.1f}%")

    c5, c6, c7 = st.columns(3)
    c5.metric("Valor total proposto (R$)", f"{total_valor:,.2f}")
    c6.metric("Ticket médio proposto (R$)",f"{ticket_medio:,.2f}")
    c7.metric("Valor fechado (R$)",        f"{valor_fech:,.2f}")

    st.divider()
    st.subheader("📈 Evolução semanal de threads & valor")
    ts = (df.set_index("created_at")
            .resample("W-MON")
            .agg(threads=("analysable_id", "nunique"),
                 valor=("valor_proposta", "sum"))
            .reset_index())

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=ts.created_at, y=ts.threads, name="Threads", marker_color="#1f77b4"), secondary_y=False)
    fig.add_trace(go.Scatter(x=ts.created_at, y=ts.valor,   name="Valor (R$)", mode="lines+markers", marker_color="#ff7f0e"), secondary_y=True)
    fig.update_layout(template=PLOTLY_TEMPLATE, legend_orientation="h", legend_y=1.02)
    fig.update_yaxes(title_text="Threads", secondary_y=False)
    fig.update_yaxes(title_text="Valor (R$)", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------
# ABA 2 – ANÁLISES
# --------------------------------------------------------------------------
def tab_analises(df: pd.DataFrame):
    st.subheader("🔍 Análises Estatísticas & Visuais")

    eng_col   = find_col(df, ["temperature_engajamento"])
    urg_col   = find_col(df, ["temperature_urgencia"])
    est_col   = find_col(df, ["negociacao_estagio"])
    tom_col   = find_col(df, ["tom_da_conversa"])
    stat_col  = find_col(df, ["status_acordo"])

    # 1. Scatter Engajamento × Urgência
    if eng_col and urg_col:
        st.markdown("#### Engajamento × Urgência")
        sc_df = df.copy()
        sc_df["subject_short"] = sc_df["subject"].apply(lambda s: wrap_text(s, 120))
        fig_sc = px.scatter(
            sc_df, x=eng_col, y=urg_col,
            color="tempo_resolucao_dias", size="email_count",
            hover_name="subject_short", template=PLOTLY_TEMPLATE,
            color_continuous_scale="Viridis",
            labels={eng_col: "Engajamento", urg_col: "Urgência",
                    "tempo_resolucao_dias": "Dias p/ resolver",
                    "email_count": "E‑mails"},
        )
        st.plotly_chart(fig_sc, use_container_width=True)

    # 2. Funil de Estágios
    if est_col:
        st.markdown("#### Funil de Negociação")
        ordem = ["Proposta Inicial","Contraproposta","Esclarecimento de Dúvidas",
                 "Acordo Fechado","Acordo Rejeitado"]
        funil_df = (df[est_col].value_counts()
                       .reindex(ordem).fillna(0).reset_index()
                       .rename(columns={"index": "Estágio", est_col: "Threads"}))
        fig_funil = px.funnel(funil_df, x="Threads", y="Estágio",
                               template=PLOTLY_TEMPLATE)
        st.plotly_chart(fig_funil, use_container_width=True)

    # 3. Histograma tempo de resolução
    if "tempo_resolucao_dias" in df.columns and df["tempo_resolucao_dias"].notna().sum() > 2:
        fig_hist = px.histogram(
            df["tempo_resolucao_dias"], nbins=20, marginal="violin",
            template=PLOTLY_TEMPLATE, opacity=0.75,
            title="Distribuição do tempo de resolução (dias)")
        st.plotly_chart(fig_hist, use_container_width=True)

    # 4. Box‑plot Valor × Estágio & Tom
    if est_col and "valor_proposta" in df:
        st.markdown("#### Valor proposto por estágio")
        fig_box = px.box(
            df[[est_col, "valor_proposta"]].dropna(),
            x=est_col, y="valor_proposta", points="all",
            template=PLOTLY_TEMPLATE,
            labels={est_col: "Estágio", "valor_proposta": "Valor (R$)"})
        st.plotly_chart(fig_box, use_container_width=True)

    if tom_col and "valor_proposta" in df:
        st.markdown("#### Valor proposto por tom da conversa")
        fig_violin = px.violin(
            df[[tom_col, "valor_proposta"]].dropna(),
            x=tom_col, y="valor_proposta", points="all",
            template=PLOTLY_TEMPLATE)
        st.plotly_chart(fig_violin, use_container_width=True)

    # 5. Pair‑plot KPIs
    num_cols = [c for c in ["email_count", "tempo_resolucao_dias", "valor_proposta"] if c in df]
    if len(num_cols) >= 3:
        st.markdown("#### Scatter matrix (KPIs)")
        fig_pair = px.scatter_matrix(
            df[num_cols].dropna(), dimensions=num_cols, template=PLOTLY_TEMPLATE)
        fig_pair.update_traces(diagonal_visible=False, showupperhalf=False)
        st.plotly_chart(fig_pair, use_container_width=True)

    st.divider()

    # 6. Volume semanal
    st.markdown("#### Volume semanal de threads")
    ts = df.set_index("created_at").resample("W")["analysable_id"].nunique()
    fig_vol = px.bar(ts, labels={"value": "Threads", "created_at": "Semana"},
                       template=PLOTLY_TEMPLATE)
    st.plotly_chart(fig_vol, use_container_width=True)
    
    st.divider()

    # 7. Modelos em statsmodels ------------------------------------------------
    st.markdown("### 📐 Modelagens (statsmodels)")

    # 7.1 Logit: Prob. Fechar ~ Emails + Tempo
    if stat_col and set(df[stat_col].dropna().unique()) >= {"Acordo Fechado", "Proposta"}:
        st.markdown("#### Logit: probabilidade de fechar")
        log_df = df[[stat_col, "email_count", "tempo_resolucao_dias"]].dropna()
        log_df["y"] = log_df[stat_col].eq("Acordo Fechado").astype(int)
        if log_df["y"].nunique() == 2 and len(log_df) > 20:
            try:
                logit = smf.logit("y ~ email_count + tempo_resolucao_dias", data=log_df).fit(disp=False)
                st.write(logit.summary())
                # curva de resposta
                xs = np.linspace(0, log_df.email_count.max(), 100)
                ts_ = np.linspace(0, log_df.tempo_resolucao_dias.max(), 100)
                df_grid = pd.DataFrame({"email_count": xs,
                                        "tempo_resolucao_dias": np.median(ts_)})
                probs = logit.predict(df_grid)
                fig_log = go.Figure([
                    go.Scatter(x=xs, y=probs, mode="lines", name="Prob. fechar"),
                    go.Scatter(x=log_df.email_count, y=log_df.y+0.02, mode="markers",
                             name="Dados", marker=dict(size=4))
                ])
                fig_log.update_layout(template=PLOTLY_TEMPLATE,
                                      xaxis_title="E‑mails por thread",
                                      yaxis_title="Probabilidade de acordo")
                st.plotly_chart(fig_log, use_container_width=True)
            except PerfectSeparationError:
                st.warning("Perfect separation: não foi possível ajustar o Logit.")

    # 7.2 Curva de Sobrevivência
    if KaplanMeierFitter and "tempo_resolucao_dias" in df and stat_col:
        st.markdown("#### Curva de sobrevivência – tempo até acordo")
        km_df = df[["tempo_resolucao_dias", stat_col]].dropna()
        km_df["fechou"] = km_df[stat_col].eq("Acordo Fechado").astype(int)
        if km_df["fechou"].sum():
            kmf = KaplanMeierFitter()
            kmf.fit(km_df["tempo_resolucao_dias"], event_observed=km_df["fechou"])
            fig_surv = go.Figure(go.Scatter(
                x=kmf.survival_function_.index,
                y=kmf.survival_function_["KM_estimate"],
                mode="lines"))
            fig_surv.update_layout(template=PLOTLY_TEMPLATE,
                                   xaxis_title="Dias", yaxis_title="P(NÃO fechado)")
            st.plotly_chart(fig_surv, use_container_width=True)

    # 8. Rede de participantes
    if nx and "participants" in df.columns:
        with st.expander("🔗 Rede de participantes"):
            edges = []
            for parts in df["participants"].dropna():
                ps = list({p.strip().lower() for p in parts})
                edges += list(itertools.combinations(ps, 2))
            G = nx.Graph()
            G.add_edges_from(edges)
            if G.number_of_nodes() > 2:
                pos = nx.spring_layout(G, k=0.4, seed=42)
                edge_x, edge_y = [], []
                for e in G.edges():
                    x0, y0 = pos[e[0]]
                    x1, y1 = pos[e[1]]
                    edge_x += [x0, x1, None]
                    edge_y += [y0, y1, None]
                node_x, node_y = zip(*pos.values())
                fig_net = go.Figure([
                    go.Scatter(x=edge_x, y=edge_y, mode="lines",
                               line=dict(width=0.5), hoverinfo="none"),
                    go.Scatter(x=node_x, y=node_y, mode="markers+text",
                               text=list(G.nodes()), textposition="top center",
                               marker=dict(size=6))])
                fig_net.update_layout(template=PLOTLY_TEMPLATE,
                                      showlegend=False, height=500)
                st.plotly_chart(fig_net, use_container_width=True)
            else:
                st.info("Rede muito pequena para visualização.")

    # 9. Word‑cloud de argumentos legais
    if WordCloud and "argumentos_legais" in df.columns:
        with st.expander("☁️ Word‑cloud de argumentos legais"):
            text = " ".join(itertools.chain.from_iterable(df["argumentos_legais"].dropna()))
            if text.strip():
                wc = WordCloud(width=600, height=300, background_color="white").generate(text)
                st.image(wc.to_array(), use_column_width=True)
            else:
                st.info("Nenhum argumento legal encontrado.")

# --------------------------------------------------------------------------
# ABA 3 – TABELAS
# --------------------------------------------------------------------------
def tab_tabelas(df: pd.DataFrame):
    st.subheader("📑 Tabela Detalhada & Sumarizações")

    # ---------- seletor de colunas ----------
    cols_all = sorted(df.columns)
    default_cols = ["subject","email_count","tempo_resolucao_dias",
                    "valor_proposta", find_col(df,["status_acordo"]),
                    find_col(df,["negociacao_estagio"])]
    selected = st.multiselect("Colunas a exibir", cols_all,
                              default=[c for c in default_cols if c in cols_all])

    # ---------- data editor ----------
    df_show = df[selected].copy()
    df_show.rename(columns=lambda c: c.replace("_"," ").title(), inplace=True)
    st.data_editor(
        df_show,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic"
    )

    # ---------- resumo por estágio ----------
    est_col = find_col(df, ["negociacao_estagio"])
    if est_col and "valor_proposta" in df:
        st.markdown("#### Resumo financeiro por estágio")
        resumo = (df.groupby(est_col)
                    .agg(threads=("analysable_id","nunique"),
                         valor_total=("valor_proposta","sum"),
                         ticket_medio=("valor_proposta","mean"))
                    .sort_values("threads", ascending=False))
        resumo.rename(columns={"threads":"Threads",
                               "valor_total":"Valor Total (R$)",
                               "ticket_medio":"Ticket Médio (R$)"}, inplace=True)
        st.dataframe(resumo.style.format({"Valor Total (R$)":"R$ {:.2f}",
                                          "Ticket Médio (R$)":"R$ {:.2f}"}),
                       use_container_width=True)

# --------------------------------------------------------------------------
# ABA 4 – ANÁLISE INDIVIDUAL (E-mail)
# --------------------------------------------------------------------------
def get_id_col(df: pd.DataFrame) -> str:
    for cand in ("analysis_id", "id"):
        if cand in df.columns:
            return cand
    raise KeyError("Nenhuma coluna de ID encontrada (analysis_id / id).")

def tab_email_individual(df_raw: pd.DataFrame, df_filtered: pd.DataFrame) -> None:
    """
    🔎 Exibe uma thread de e-mail específica com seus blobs JSON
    (extracted_data, temperature_assessment, director_decision).

    • Funciona com qualquer formato de ID (UUID, int…).
    • Gera rótulos de seleção a partir da data + assunto do e-mail.
    • Reconstrói JSONs se eles tiverem sido achatados pelo normalize.
    """
    st.subheader("📧 Análise Individual – E-mail")
    st.markdown("Selecione uma thread para inspecionar os dados extraídos.")

    if df_filtered.empty:
        st.info("Nenhum dado disponível para os filtros atuais.")
        return

    # ──────────────────────────────────────────────────────────────
    # 1) <selectbox> – sempre strings
    # ──────────────────────────────────────────────────────────────
    id_col = get_id_col(df_filtered)
    df_view = df_filtered.copy()
    df_view["id_str"] = df_view[id_col].astype(str)

    # Tenta extrair um “assunto” (nº do processo) do JSON flat ou da coluna subject
    subj_col = find_col(df_view, ["subject", "extracted_numero_processo", "extracted_nome_parte"])

    if subj_col:
        df_view["assunto"] = (
            df_view[subj_col]
            .fillna("Assunto indisponível")
            .astype(str)
            .str.slice(0, 60)  # evita rótulos gigantes
        )
    else:
        # Se nenhuma coluna de assunto for encontrada, cria uma padrão
        df_view["assunto"] = "Assunto indisponível"


    labels = (
        df_view["created_at"].dt.strftime("%d/%m/%Y %H:%M")
        + " | "
        + df_view["assunto"]
    )
    labels.index = df_view["id_str"]

    sel = st.selectbox(
        "Selecione uma thread:",
        options=df_view["id_str"],
        format_func=lambda k: labels.get(k, "ID não encontrado"),
    )
    if not sel:
        return

    # ──────────────────────────────────────────────────────────────
    # 2) Linha completa
    # ──────────────────────────────────────────────────────────────
    row = df_raw.loc[df_raw[id_col].astype(str) == sel].iloc[0]
    st.divider()

    # ──────────────────────────────────────────────────────────────
    # 3) Helper JSON (aceita flatten)
    # ──────────────────────────────────────────────────────────────
    def _json_email(prefix: str) -> dict | None:
        raw_key = {
            "extracted": "extracted_data",
            "temperature": "temperature_assessment",
            "director": "director_decision",
            "kpis": "kpis",
            "advisor": "advisor_recommendation",
            "pipedrive": "context",
            "summary": "formal_summary",
        }[prefix]

        # 3a) blob bruto existe?
        if raw_key in row and isinstance(row[raw_key], str) and row[raw_key].strip():
            try:
                return json.loads(row[raw_key])
            except json.JSONDecodeError:
                return {"erro": "JSON inválido", "raw_data": row[raw_key]}

        # 3b) reconstruir do flatten
        subcols = {c: row[c] for c in row.index if c.startswith(f"{prefix}_")}
        if not subcols:
            return None

        rebuilt = {
            c.split(f"{prefix}_", 1)[1]: v
            for c, v in subcols.items()
            if not (np.isscalar(v) and pd.isna(v))
        }
        return rebuilt or None

    # ──────────────────────────────────────────────────────────────
    # 4) Exibição em duas linhas
    # ──────────────────────────────────────────────────────────────

    # --- Primeira Linha ---
    row1_col1, row1_col2, row1_col3 = st.columns(3)

    with row1_col1:
        st.markdown("#### Conteúdo Extraído")
        j = _json_email("extracted")
        if j:
            st.json(j, expanded=False)
        else:
            st.write("Nenhum dado.")

    with row1_col2:
        st.markdown("#### Avaliação de Temperatura")
        j = _json_email("temperature")
        if j:
            st.json(j, expanded=False)
        else:
            st.write("Nenhum dado.")

    with row1_col3:
        st.markdown("#### Ação do Diretor")
        j = _json_email("director")
        if j:
            st.json(j, expanded=False)
        else:
            st.write("Nenhum dado.")

    st.divider()

    # --- Segunda Linha ---
    row2_col1, row2_col2, row2_col3, row2_col4 = st.columns(4)
            
    with row2_col1:
        st.markdown("#### KPIs")
        j = _json_email("kpis")
        if j:
            st.json(j, expanded=False)
        else:
            st.write("Nenhum dado.")
            
    with row2_col2:
        st.markdown("#### Recomendações")
        j = _json_email("advisor")
        if j:
            st.json(j, expanded=False)
        else:
            st.write("Nenhum dado.")
            
    with row2_col3:
        st.markdown("#### Contexto Pipedrive")
        j = _json_email("pipedrive")
        if j:
            st.json(j, expanded=False)
        else:
            st.write("Nenhum dado.")
            
    with row2_col4:
        st.markdown("#### Sumarização")
        j = _json_email("summary")
        if j:
            st.json(j, expanded=False)
        else:
            st.write("Nenhum dado.")


# --------------------------------------------------------------------------
# APLICAÇÃO PRINCIPAL
# --------------------------------------------------------------------------
def main():
    st.title("📧 Dashboard de Negociações por E‑mail")

    df_raw = read_email_data()
    if df_raw.empty:
        st.warning("⚠️ Nenhum dado encontrado no banco.")
        return

    # -------- filtros laterais --------
    st.sidebar.header("⚙️ Filtros")
    min_d, max_d = df_raw.created_at.min().date(), df_raw.created_at.max().date()
    inicio, fim = st.sidebar.date_input("Período", (min_d, max_d),
                                        min_value=min_d, max_value=max_d)
    if inicio > fim:
        st.sidebar.error("Datas inválidas.")
        return
    df = df_raw[(df_raw.created_at.dt.date >= inicio) &
                (df_raw.created_at.dt.date <= fim)].copy()

    est_col = find_col(df, ["negociacao_estagio"])
    if est_col:
        est_opts = sorted(df[est_col].dropna().unique())
        escolha = st.sidebar.multiselect("Filtrar por estágio", est_opts, default=est_opts)
        df = df[df[est_col].isin(escolha)]

    if df.empty:
        st.info("Nenhum registro para os filtros escolhidos.")
        return

    # -------- abas --------
    abas = st.tabs(["📊 Resumos", "🔍 Análises", "📑 Tabelas", " 🔎 E-mail Individual "])
    with abas[0]: 
        tab_resumos(df)
    with abas[1]: 
        tab_analises(df)
    with abas[2]: 
        tab_tabelas(df)
    with abas[3]:
        tab_email_individual(df_raw, df) 

if __name__ == "__main__":
    main()