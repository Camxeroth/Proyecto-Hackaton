import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import scipy.stats as stats
import sys
import os
import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.ingestion import IngestorMercado
from scripts.motor_garch import MotorVolatilidadGARCH, evaluar_persistencia
from scripts.backtester import BacktesterGARCH
from scripts.analista_bedrock import AnalistaRiesgoBedrock

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SGR-IA — Sistema de Gestión de Riesgo",
    layout="wide",
    page_icon="assets/favicon.ico" if os.path.exists("assets/favicon.ico") else "",
)

# CSS institucional: paleta oscura estilo terminal financiera
st.markdown("""
<style>
  /* Fondo general */
  .stApp { background-color: #0d1117; color: #e6edf3; }
  /* Sidebar */
  section[data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
  /* Métricas */
  [data-testid="stMetric"] { background-color: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 12px 16px; }
  [data-testid="stMetricLabel"] { color: #8b949e !important; font-size: 0.75rem; text-transform: uppercase; }
  [data-testid="stMetricValue"] { color: #e6edf3 !important; font-size: 1.6rem; font-weight: 600; }
  /* Tabs */
  .stTabs [data-baseweb="tab-list"] { background-color: #161b22; border-bottom: 1px solid #30363d; }
  .stTabs [data-baseweb="tab"] { color: #8b949e; padding: 10px 20px; font-size: 0.85rem; }
  .stTabs [aria-selected="true"] { color: #58a6ff !important; border-bottom: 2px solid #58a6ff !important; }
  /* Expanders */
  .streamlit-expanderHeader { background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; }
  /* Dataframe */
  .stDataFrame { border: 1px solid #30363d; border-radius: 6px; }
  /* Botones */
  .stButton > button { background-color: #1f6feb; color: white; border: none;
    border-radius: 6px; padding: 8px 20px; font-weight: 500; }
  .stButton > button:hover { background-color: #388bfd; }
  /* Divider */
  hr { border-color: #30363d; }
  /* Captions */
  .stCaption { color: #8b949e; font-size: 0.75rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# ENCABEZADO INSTITUCIONAL
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="padding: 20px 0 10px 0; border-bottom: 1px solid #30363d; margin-bottom: 24px;">
  <h1 style="color:#e6edf3; font-size:1.8rem; font-weight:700; margin:0;">
    SGR-IA &nbsp;·&nbsp; Sistema de Gestión de Riesgo con Inteligencia Artificial
  </h1>
  <p style="color:#8b949e; margin:6px 0 0 0; font-size:0.9rem;">
    Motor GARCH(1,1) · Distribución t-Student · VaR / CVaR Condicional · AWS Bedrock GenAI
  </p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — PARÁMETROS DE SESIÓN
# ─────────────────────────────────────────────────────────────────────────────
ACTIVOS = {
    "SPY":    "S&P 500 — Índice Accionario EEUU",
    "QQQ":    "Nasdaq 100 — Tecnología de Alta Capitalización",
    "GLD":    "SPDR Gold Shares — Oro Físico (Refugio)",
    "TLT":    "iShares 20+ Year Treasury Bond — Renta Fija LP",
    "BTC-USD":"Bitcoin — Activo Digital de Alta Volatilidad",
    "EEM":    "iShares MSCI Emerging Markets",
    "XLE":    "Energy Select Sector SPDR — Energía / Commodities",
}

with st.sidebar:
    st.markdown("### Configuración del Modelo")
    st.markdown("---")

    ticker = st.selectbox(
        "Activo",
        options=list(ACTIVOS.keys()),
        format_func=lambda x: f"{x}  ·  {ACTIVOS[x]}",
    )
    st.markdown("---")
    c1, c2 = st.columns(2)
    fecha_ini = c1.date_input("Inicio", datetime.date(2015, 1, 1))
    fecha_fin = c2.date_input("Fin",    datetime.date(2026, 6, 1))
    st.markdown("---")
    st.markdown("**Umbrales de Señal Táctica**")
    pct_salida  = st.slider("Salida — Percentil de Volatilidad",  85, 99, 95)
    pct_entrada = st.slider("Reentrada — Percentil de Volatilidad", 50, 84, 70)
    st.markdown("---")
    walk_forward = st.checkbox(
        "Re-estimación walk-forward",
        help="Re-ajusta el modelo cada trimestre usando únicamente datos históricos. Elimina data leakage en la calibración.",
        value=False,
    )
    st.markdown("---")
    st.markdown(
        "<p style='color:#8b949e;font-size:0.72rem;'>Fuente de datos: Yahoo Finance · "
        "Motor: arch-py · Visualización: Plotly · "
        "IA Generativa: Amazon Bedrock</p>",
        unsafe_allow_html=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# CAPA DE PROCESAMIENTO (CACHEADA)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def compilar_modelo(ticker, fecha_ini, fecha_fin, walk_forward):
    ingestor    = IngestorMercado(ticker, str(fecha_ini), str(fecha_fin))
    bucket      = os.environ.get("AWS_BUCKET_NAME")
    df_retornos = ingestor.procesar_datos_con_cache_s3(bucket) if bucket else ingestor.procesar_datos_en_memoria()

    motor = MotorVolatilidadGARCH(df_retornos, dist='t')
    if walk_forward:
        df, params = motor.ejecutar_walk_forward()
    else:
        df, params = motor.ejecutar_modelo_en_memoria()

    comp_gjr = motor.comparar_con_gjr()
    return df, params, comp_gjr

# ─────────────────────────────────────────────────────────────────────────────
# EJECUCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
try:
    with st.spinner("Ajustando modelo GARCH por Máxima Verosimilitud..."):
        df_proc, params, comp_gjr = compilar_modelo(ticker, fecha_ini, fecha_fin, walk_forward)

    backtest = BacktesterGARCH(df_proc)
    df_res   = backtest.simular(pct_salida=pct_salida, pct_entrada=pct_entrada)
    metricas = backtest.obtener_metricas()

    # ── KPI Banner ────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Retorno Estrategia",  f"{metricas['Retorno_Estrategia']:.2f}%")
    k2.metric("Retorno Mercado",     f"{metricas['Retorno_Mercado']:.2f}%")
    k3.metric("MDD Estrategia",      f"{metricas['MDD_Estrategia']:.2f}%")
    k4.metric("MDD Mercado",         f"{metricas['MDD_Mercado']:.2f}%")
    k5.metric("Reducción Drawdown",
              f"{abs(metricas['MDD_Mercado']) - abs(metricas['MDD_Estrategia']):.2f} p.p.",
              delta="Estrategia vs. Pasivo",
              delta_color="normal")

    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)

    # ── TABS ──────────────────────────────────────────────────────────────────
    TAB_LABELS = [
        "Terminal de Riesgo",
        "Análisis de Cola  (VaR / CVaR)",
        "Insights GenAI  ·  AWS Bedrock",
        "Arquitectura y Metodología",
    ]
    tab_riesgo, tab_cola, tab_ia, tab_arq = st.tabs(TAB_LABELS)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — TERMINAL DE RIESGO
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_riesgo:
        PLOTLY_DARK = dict(
            template="plotly_dark",
            paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117",
            font=dict(color="#8b949e", size=11),
        )

        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.6, 0.4],
            subplot_titles=["Capital Acumulado (base 1.00)", "Volatilidad Condicional Anualizada (%)"],
        )

        # Panel superior — equity curves
        fig.add_trace(go.Scatter(
            x=df_res.index, y=df_res['Eq_Mercado'],
            name="Buy & Hold", line=dict(color="#484f58", width=1.8)),
            row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df_res.index, y=df_res['Eq_Estrategia'],
            name="Estrategia GARCH", line=dict(color="#58a6ff", width=2.2)),
            row=1, col=1)

        # Zonas en liquidez
        df_res['_chg'] = df_res['Estado'].diff()
        for start, end in zip(
            df_res[df_res['_chg'] == -1].index,
            list(df_res[df_res['_chg'] == 1].index) + [df_res.index[-1]]
        ):
            fig.add_vrect(x0=start, x1=end, fillcolor="#da3633",
                          opacity=0.10, line_width=0, row=1, col=1)

        # Panel inferior — volatilidad anualizada
        df_res['Vol_Anual'] = np.sqrt(df_res['Varianza_GARCH']) * np.sqrt(252) * 100
        fig.add_trace(go.Scatter(
            x=df_res.index, y=df_res['Vol_Anual'],
            name="Volatilidad", line=dict(color="#da3633", width=1.4)),
            row=2, col=1)

        # Umbrales (solo visual, referencia sobre histórico completo)
        p_sal = np.percentile(df_res['Vol_Anual'].dropna(), pct_salida)
        p_ent = np.percentile(df_res['Vol_Anual'].dropna(), pct_entrada)
        fig.add_hline(y=p_sal, line_dash="dash", line_color="#da3633", line_width=1,
                      annotation_text=f"Señal de Salida P{pct_salida}", row=2, col=1)
        fig.add_hline(y=p_ent, line_dash="dash", line_color="#3fb950", line_width=1,
                      annotation_text=f"Señal de Reentrada P{pct_entrada}", row=2, col=1)

        fig.update_layout(height=600, hovermode="x unified",
                          legend=dict(orientation="h", y=1.02, x=0),
                          **PLOTLY_DARK)
        fig.update_xaxes(showgrid=True, gridcolor="#21262d", zeroline=False)
        fig.update_yaxes(showgrid=True, gridcolor="#21262d", zeroline=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Zonas sombreadas en rojo: períodos en los que la estrategia táctica mantiene liquidez (posición 0). "
            "Las líneas punteadas son percentiles calculados sobre el histórico completo — solo para referencia visual. "
            "El backtester opera con umbrales expandientes (sin look-ahead bias)."
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 — ANÁLISIS DE COLA (VaR / CVaR + QQ-Plot)
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_cola:
        col_metricas, col_qq = st.columns([1, 2])

        with col_metricas:
            st.markdown("#### Métricas de Cola — Promedio Histórico")
            st.caption("Promedios basados en VaR/CVaR condicionales diarios del modelo GARCH.")

            for nivel, col_var, col_cvar in [
                ("95%",   "VaR_95",   "CVaR_95"),
                ("97.5%", "VaR_97_5", "CVaR_97_5"),
                ("99%",   "VaR_99",   "CVaR_99"),
            ]:
                if col_var in df_proc.columns:
                    v = df_proc[col_var].mean() * 100
                    c = df_proc[col_cvar].mean() * 100
                    st.markdown(f"**Nivel {nivel}**")
                    ca, cb = st.columns(2)
                    ca.metric(f"VaR",  f"{v:.3f}%")
                    cb.metric(f"CVaR (ES)", f"{c:.3f}%")
                    st.markdown("---")

        with col_qq:
            st.markdown("#### QQ-Plot — Retornos Observados vs. Distribución t-Student GARCH")
            st.caption(
                "Compara los cuantiles empíricos de los retornos reales con los cuantiles teóricos "
                "de la distribución t-Student implícita en el modelo. La línea de 45° indica ajuste perfecto. "
                "La divergencia en las colas revela la leptocurtosis del activo."
            )

            nu_est = params['nu']
            retornos_limpios = df_proc['Retorno_Log'].dropna()
            n = len(retornos_limpios)

            # Cuantiles empíricos vs teóricos t-Student escalados a la vol promedio
            p_points   = np.linspace(0.01, 0.99, min(n, 500))
            q_empirico = np.quantile(retornos_limpios, p_points)
            vol_media  = np.sqrt(df_proc['Varianza_GARCH'].mean())
            q_teorico  = stats.t.ppf(p_points, nu_est) * vol_media

            fig_qq = go.Figure()
            fig_qq.add_trace(go.Scatter(
                x=q_teorico, y=q_empirico,
                mode='markers',
                marker=dict(color='#58a6ff', size=4, opacity=0.7),
                name='Observado vs. t-GARCH'
            ))
            lim = max(abs(q_teorico).max(), abs(q_empirico).max()) * 1.05
            fig_qq.add_trace(go.Scatter(
                x=[-lim, lim], y=[-lim, lim],
                mode='lines', line=dict(color='#f0883e', dash='dash', width=1.5),
                name='Ajuste perfecto (45°)'
            ))
            fig_qq.update_layout(
                xaxis_title="Cuantiles Teóricos t-Student GARCH",
                yaxis_title="Cuantiles Empíricos de Retornos",
                height=420,
                paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                font=dict(color="#8b949e"),
                xaxis=dict(showgrid=True, gridcolor="#21262d"),
                yaxis=dict(showgrid=True, gridcolor="#21262d"),
                legend=dict(orientation="h", y=-0.15),
            )
            st.plotly_chart(fig_qq, use_container_width=True)

        st.markdown("---")
        st.markdown("#### Serie Temporal de VaR y CVaR Condicionales")
        st.caption(
            "Evolución diaria del VaR y CVaR al 99%. Cuando el retorno observado (barras negativas) "
            "supera en magnitud al CVaR, se produce un 'exceedance' de cola — el evento que el "
            "motor GARCH está diseñado para anticipar y mitigar."
        )

        if "VaR_99" in df_res.columns and "CVaR_99" in df_res.columns:
            fig_var = go.Figure()
            fig_var.add_trace(go.Scatter(
                x=df_res.index, y=df_res['VaR_99'] * 100,
                name="VaR 99%", line=dict(color='#f0883e', width=1.5, dash='dot')
            ))
            fig_var.add_trace(go.Scatter(
                x=df_res.index, y=df_res['CVaR_99'] * 100,
                name="CVaR 99% (Expected Shortfall)",
                line=dict(color='#da3633', width=1.8)
            ))
            fig_var.add_trace(go.Bar(
                x=df_res.index, y=df_res['Retorno_Log'] * 100,
                name="Retorno Diario",
                marker_color=np.where(df_res['Retorno_Log'] < 0, '#da3633', '#3fb950'),
                opacity=0.35,
            ))
            fig_var.update_layout(
                height=360, hovermode="x unified",
                yaxis_title="Retorno / VaR / CVaR (%)",
                paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                font=dict(color="#8b949e"),
                xaxis=dict(showgrid=True, gridcolor="#21262d"),
                yaxis=dict(showgrid=True, gridcolor="#21262d"),
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig_var, use_container_width=True)
        else:
            st.info("Las columnas VaR_99/CVaR_99 no están presentes en el DataFrame de resultados. Recarga el modelo.")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3 — INSIGHTS GenAI / AWS BEDROCK
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_ia:
        col_ctx, col_reporte = st.columns([1, 2])

        with col_ctx:
            st.markdown("#### Contexto Cuantitativo del Modelo")
            st.caption("Parámetros MLE transmitidos al motor generativo.")

            alpha_v = params['alpha']
            beta_v  = params['beta']
            omega_v = params['omega']
            nu_v    = params['nu']
            pers_v  = params['persistencia']
            vl_v    = params.get('vol_largo_plazo', float('nan'))

            st.markdown(f"""
| Parámetro | Valor |
|-----------|-------|
| ω (omega) | `{omega_v:.6f}` |
| α[1] (ARCH) | `{alpha_v:.4f}` |
| β[1] (GARCH) | `{beta_v:.4f}` |
| α + β (Persistencia) | `{pers_v:.4f}` |
| ν (grados de libertad) | `{nu_v:.2f}` |
| Vol. Largo Plazo | `{vl_v*100:.3f}%` si finito |
""")
            pi = evaluar_persistencia(alpha_v, beta_v)
            if pi['es_estacionaria']:
                st.success(pi['interpretacion'])
            else:
                st.error(pi['interpretacion'])

            st.markdown("---")
            st.markdown("#### Resultados del Backtest")
            st.dataframe(
                pd.DataFrame({
                    "Métrica": ["Retorno", "Drawdown Máximo"],
                    "Estrategia GARCH": [
                        f"{metricas['Retorno_Estrategia']:.2f}%",
                        f"{metricas['MDD_Estrategia']:.2f}%",
                    ],
                    "Buy & Hold": [
                        f"{metricas['Retorno_Mercado']:.2f}%",
                        f"{metricas['MDD_Mercado']:.2f}%",
                    ],
                }).set_index("Métrica"),
                use_container_width=True,
            )

        with col_reporte:
            st.markdown("#### Memorando de Riesgo — Generado por Amazon Bedrock")
            st.caption(
                "El motor de IA recibe las métricas cuantitativas y produce un informe ejecutivo "
                "siguiendo el estándar de memorandos institucionales de gestión de riesgo. "
                "Si AWS Bedrock no está disponible, el sistema activa un motor de análisis local."
            )

            if st.button("Generar Informe Ejecutivo", type="primary"):
                with st.spinner("Consultando Amazon Bedrock (Claude 3 Haiku)..."):
                    analista = AnalistaRiesgoBedrock()
                    reporte  = analista.generar_reporte_riesgo(ticker, metricas, params)
                st.markdown(
                    f"""<div style="background:#161b22; border:1px solid #30363d; border-radius:8px;
                    padding:20px; color:#e6edf3; line-height:1.7; font-size:0.9rem;">
                    {reporte}</div>""",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    "<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;"
                    "padding:20px;color:#8b949e;font-size:0.87rem;'>"
                    "Presiona <strong>Generar Informe Ejecutivo</strong> para invocar el modelo "
                    "de lenguaje de Amazon Bedrock y obtener un análisis cualitativo del riesgo.</div>",
                    unsafe_allow_html=True
                )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 4 — ARQUITECTURA Y METODOLOGÍA
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_arq:
        col_diag, col_met = st.columns([1, 1])

        with col_diag:
            st.markdown("#### Diagrama de Arquitectura")
            st.components.v1.html("""
<!DOCTYPE html>
<html>
<head>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 12px; }
  .flow { display: flex; flex-direction: column; align-items: center; gap: 0; width: 100%; }
  .row  { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; }
  .node {
    border-radius: 8px; padding: 8px 12px; font-size: 11.5px; font-weight: 500;
    text-align: center; min-width: 130px; line-height: 1.4; border: 1.5px solid;
  }
  .node-data  { background:#21262d; border-color:#30363d; color:#e6edf3; }
  .node-aws   { background:#1f3a5c; border-color:#388bfd; color:#e6edf3; }
  .node-garch { background:#1a3a2a; border-color:#3fb950; color:#e6edf3; }
  .node-risk  { background:#3a1f2a; border-color:#da3633; color:#e6edf3; }
  .node-ui    { background:#1c2433; border-color:#58a6ff; color:#e6edf3; }
  .arrow-v { display:flex; align-items:center; justify-content:center; height:24px; color:#484f58; font-size:16px; }
  .arrow-h { color:#484f58; font-size:16px; flex-shrink:0; }
  .label-sm { font-size:9px; color:#8b949e; text-align:center; margin-top:-6px; margin-bottom:2px; }
</style>
</head>
<body>
<div class="flow">

  <!-- Row 1: Data source -->
  <div class="row">
    <div class="node node-data">Yahoo Finance API</div>
  </div>
  <div class="arrow-v">↓</div>
  <div class="label-sm">Retornos Logarítmicos</div>

  <!-- Row 2: S3 -->
  <div class="row">
    <div class="node node-aws">Amazon S3<br><span style="font-size:10px;opacity:0.75;">Cache Parquet</span></div>
  </div>
  <div class="arrow-v">↓</div>

  <!-- Row 3: GARCH engine -->
  <div class="row">
    <div class="node node-garch">Motor GARCH(1,1)<br><span style="font-size:10px;opacity:0.75;">Distribución t-Student</span></div>
  </div>
  <div class="arrow-v" style="height:12px;"></div>

  <!-- Row 4: VaR + Backtester split -->
  <div class="row" style="gap:20px;">
    <div style="display:flex;flex-direction:column;align-items:center;gap:0;">
      <div class="arrow-v">↓</div>
      <div class="label-sm">Varianza Cond.</div>
      <div class="node node-risk">VaR / CVaR<br><span style="font-size:10px;opacity:0.75;">95% · 97.5% · 99%</span></div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:0;">
      <div class="arrow-v">↓</div>
      <div class="label-sm">Señales de Régimen</div>
      <div class="node node-garch">Backtester<br><span style="font-size:10px;opacity:0.75;">Walk-Forward</span></div>
    </div>
  </div>
  <div class="arrow-v" style="height:12px;"></div>

  <!-- Row 5: Bedrock -->
  <div class="row">
    <div style="display:flex;flex-direction:column;align-items:center;gap:0; margin-right:20px;">
      <div style="height:24px;"></div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:0;">
      <div class="label-sm">Métricas MLE</div>
      <div class="arrow-v">↓</div>
      <div class="node node-aws">Amazon Bedrock<br><span style="font-size:10px;opacity:0.75;">Claude 3 Haiku</span></div>
      <div class="arrow-v">↓</div>
      <div class="label-sm">Memorando de Riesgo</div>
    </div>
  </div>

  <!-- Row 6: Dashboard (converge) -->
  <div class="row">
    <div class="node node-ui" style="min-width:180px; padding:10px 16px; font-size:13px; font-weight:600;">
      Dashboard Streamlit
    </div>
  </div>

</div>
</body>
</html>
""", height=540)

        with col_met:
            st.markdown("#### Especificación Matemática del Modelo")
            omega_v = params['omega']
            alpha_v = params['alpha']
            beta_v  = params['beta']
            nu_v    = params['nu']
            pers_v  = params['persistencia']

            st.markdown(rf"""
**Ecuación de varianza condicional:**

$$\sigma_t^2 = \underbrace{{{omega_v:.6f}}}_{{\omega}} + \underbrace{{{alpha_v:.4f}}}_{{\alpha}} \varepsilon_{{t-1}}^2 + \underbrace{{{beta_v:.4f}}}_{{\beta}} \sigma_{{t-1}}^2$$

**Innovaciones:** $\varepsilon_t = \sigma_t z_t$ con $z_t \sim t(\nu={nu_v:.2f})$

**Volatilidad incondicional de largo plazo:**
$$\sigma_{{LR}} = \sqrt{{\frac{{\omega}}{{1 - \alpha - \beta}}}}$$

**Persistencia:** $\alpha + \beta = {pers_v:.4f}$
""")

            st.markdown("---")
            st.markdown("#### Comparación de Modelos — Criterio de Información")
            st.caption("AIC/BIC menor indica mejor ajuste. GJR-GARCH captura el efecto asimétrico (leverage effect).")
            df_gjr = pd.DataFrame(comp_gjr).T
            df_gjr.index.name = "Modelo"
            st.dataframe(df_gjr.style.highlight_min(axis=0, color="#1a3a2a"), use_container_width=True)

            st.markdown("---")
            st.markdown("#### Validación Econométrica")
            pi = evaluar_persistencia(alpha_v, beta_v)
            st.metric("Persistencia α+β", f"{pi['persistencia']:.4f}")
            if pi['es_estacionaria']:
                st.success(pi['interpretacion'])
            else:
                st.error(pi['interpretacion'])

            st.caption(
                "Regla: α+β < 1 garantiza estacionariedad de covarianza (GARCH estándar). "
                "Si α+β → 1, el proceso se aproxima a IGARCH (varianza integrada) y el "
                "modelo sobreestima la persistencia de los choques de volatilidad."
            )

except Exception as e:
    st.error(f"Error al ejecutar el motor: {e}")
    st.exception(e)