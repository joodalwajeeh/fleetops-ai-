"""
FleetOps AI - Streamlit Dashboard
====================================
Professional visual identity inspired by XCMG's industrial branding
(engineering red + charcoal steel + concrete grey), built for the
China International College Students' Innovation & Entrepreneurship
Competition — Track: AI + Construction Machinery -> AI + Operations.

One app with:
  1) Overview: fleet KPIs, charts, and the unified Attention Score
  2) Chat: natural-language Q&A with the AI agent (agent.ask_agent)
  3) Reports: a shareable performance summary
  4) Upload Your Data: test the exact same pipeline against an external CSV dataset

Run locally: streamlit run app/main.py
Deploy: push to GitHub and deploy on share.streamlit.io
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import tools
import agent
import ml_anomaly

st.set_page_config(page_title="FleetOps AI | XCMG Innovation Track", page_icon="🚧", layout="wide")

# ---------------------------------------------------------------------------
# Brand palette (inspired by XCMG's engineering-red / steel-charcoal identity)
# ---------------------------------------------------------------------------
RED = "#C8102E"        # XCMG engineering red
RED_DARK = "#8C0B20"
CHARCOAL = "#1D2126"   # steel charcoal
CHARCOAL_2 = "#2B3038"
STEEL = "#5A6472"
CONCRETE = "#F3F4F6"   # light neutral background
GOLD = "#F2A900"       # safety-yellow accent
WHITE = "#FFFFFF"
GREEN = "#1E8E5A"

REQUIRED_EQUIP_COLS = {"equipment_id", "equipment_type", "project"}
REQUIRED_DAILY_COLS = {"date", "equipment_id", "equipment_type", "project",
                        "operating_hours", "downtime_hours", "fuel_consumption_l", "maintenance_flag"}

SEQ_RED = [STEEL, "#D94B5C", RED, RED_DARK]  # sequential palette for charts

# ---------------------------------------------------------------------------
# Global CSS — industrial / engineering look
# ---------------------------------------------------------------------------
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Barlow+Condensed:wght@600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', -apple-system, sans-serif;
}}

/* Hide default Streamlit chrome for a cleaner branded look */
#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}

/* Top brand banner */
.xcmg-banner {{
    background: linear-gradient(90deg, {CHARCOAL} 0%, {CHARCOAL_2} 100%);
    border-bottom: 4px solid {RED};
    padding: 18px 28px;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 18px;
}}
.xcmg-banner .brand-left {{ display: flex; align-items: center; gap: 14px; }}
.xcmg-mark {{
    width: 44px; height: 44px; border-radius: 6px;
    background: {RED};
    display: flex; align-items: center; justify-content: center;
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 700; color: white; font-size: 22px;
    flex-shrink: 0;
}}
.xcmg-title {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 700; font-size: 26px; color: white; letter-spacing: 0.5px; line-height: 1.1;
}}
.xcmg-subtitle {{ color: #B8BFC9; font-size: 12.5px; margin-top: 2px; }}
.xcmg-pill {{
    background: rgba(200,16,46,0.18); border: 1px solid {RED};
    color: #FF8C9A; padding: 6px 14px; border-radius: 20px;
    font-size: 11.5px; font-weight: 600; white-space: nowrap;
}}

/* KPI cards */
.kpi-card {{
    background: {WHITE}; border-radius: 8px; padding: 16px 18px;
    border-left: 4px solid {RED};
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    height: 100%;
}}
.kpi-label {{ font-size: 12px; color: {STEEL}; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }}
.kpi-value {{ font-family: 'Barlow Condensed', sans-serif; font-size: 30px; font-weight: 700; color: {CHARCOAL}; margin-top: 2px; }}

/* Section headers */
.section-header {{
    font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 20px;
    color: {CHARCOAL}; border-left: 5px solid {RED}; padding-left: 10px; margin: 6px 0 10px 0;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
.stTabs [data-baseweb="tab"] {{
    background: {CONCRETE}; border-radius: 6px 6px 0 0; padding: 8px 18px; font-weight: 600; color: {STEEL};
}}
.stTabs [aria-selected="true"] {{ background: {WHITE}; color: {RED} !important; border-bottom: 3px solid {RED}; }}

/* Buttons */
.stButton > button, .stDownloadButton > button {{
    background: {CHARCOAL}; color: white; border: none; border-radius: 6px; font-weight: 600;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{ background: {RED}; }}

/* Footer strip */
.xcmg-footer {{
    margin-top: 30px; padding: 14px 20px; background: {CHARCOAL}; border-radius: 6px;
    color: #9AA3AF; font-size: 11.5px; text-align: center; border-top: 3px solid {RED};
}}
</style>
""", unsafe_allow_html=True)


def kpi_card(label, value):
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
    </div>
    """, unsafe_allow_html=True)


def section(title):
    st.markdown(f'<div class="section-header">{title}</div>', unsafe_allow_html=True)


def style_fig(fig, height=380):
    fig.update_layout(
        height=height, plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Inter, sans-serif", color=CHARCOAL, size=12),
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(gridcolor="#EEF0F2", linecolor="#D8DCE1")
    fig.update_yaxes(gridcolor="#EEF0F2", linecolor="#D8DCE1")
    return fig


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
        <div style="width:34px;height:34px;border-radius:5px;background:{RED};
                    display:flex;align-items:center;justify-content:center;
                    font-family:'Barlow Condensed',sans-serif;font-weight:700;color:white;font-size:16px;">F</div>
        <div style="font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:19px;color:{CHARCOAL};">FleetOps AI</div>
    </div>
    """, unsafe_allow_html=True)
    st.caption("AI Operations Agent for Construction Equipment")

    st.divider()
    api_key = st.text_input("OpenAI API Key (optional)", type="password",
                             help="If provided, chat answers are generated by a real LLM (function calling). "
                                  "If left empty, the app runs in Test Mode (rule-based, no API key required).")
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        st.success("✅ Real Mode enabled (OpenAI)")
    else:
        st.info("ℹ️ Running in Test Mode (no live LLM)")

    st.divider()
    if tools.using_custom_data():
        st.warning("📂 Using your uploaded dataset")
        if st.button("Reset to sample data"):
            tools.reset_data_source()
            st.session_state["custom_data_active"] = False
            st.rerun()
    else:
        st.caption("📊 Using bundled sample dataset (30 units, 90 days)")

    st.divider()
    st.caption("China International College Students' Innovation & Entrepreneurship Competition")
    st.caption("Track: AI + Construction Machinery → AI + Operations")

# ---------------------------------------------------------------------------
# Brand banner
# ---------------------------------------------------------------------------
st.markdown(f"""
<div class="xcmg-banner">
    <div class="brand-left">
        <div class="xcmg-mark">F</div>
        <div>
            <div class="xcmg-title">FLEETOPS AI</div>
            <div class="xcmg-subtitle">Intelligent Operations Agent for Construction Equipment</div>
        </div>
    </div>
    <div class="xcmg-pill">AI + OPERATIONS TRACK</div>
</div>
""", unsafe_allow_html=True)

st.caption("From raw fleet data to a decision a manager can act on today")

with st.expander("💡 How this works (core idea)", expanded=False):
    st.markdown("""
FleetOps AI turns raw, low-level equipment logs (hours, downtime, fuel, maintenance) into
**prioritized, explainable action items** — instead of a manager reading through spreadsheets.

**The core idea is classification by need:** every piece of equipment is automatically classified
according to how urgently the *project* needs attention on it, using a single **Attention Score
(0-100)** that combines four signals:

1. **Downtime rate** — how much this unit is standing idle instead of working
2. **Fuel deviation** — fuel use compared to *its own equipment type's* normal range (fair comparison)
3. **Maintenance frequency** — is this unit being serviced abnormally often?
4. **ML anomaly detection** (Isolation Forest) — does this unit look statistically unusual across all signals combined?

The AI agent then lets a manager ask for this in plain language ("which equipment needs attention?")
instead of building the analysis manually every time.
""")

tab_overview, tab_chat, tab_report, tab_upload = st.tabs(
    ["📊 Overview", "💬 Ask the Agent", "📋 Report", "📂 Upload Your Data"]
)

# ============================== TAB 1: OVERVIEW ==============================
with tab_overview:
    report = tools.generate_fleet_report()

    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi_card("Fleet size", report["fleet_size"])
    with c2: kpi_card("Overall utilization", f"{report['overall_utilization_%']}%")
    with c3: kpi_card("Total operating hours", f"{report['total_operating_hours']:,.0f}")
    with c4: kpi_card("Total fuel (L)", f"{report['total_fuel_l']:,.0f}")

    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        section("Equipment ranked by downtime")
        top_downtime = pd.DataFrame(tools.get_top_downtime_equipment(8)["data"])
        fig = px.bar(top_downtime, x="equipment_id", y="downtime_rate_%",
                     color="equipment_type", text="downtime_rate_%",
                     color_discrete_sequence=[CHARCOAL, STEEL, RED, GOLD, RED_DARK, "#8A94A3"])
        st.plotly_chart(style_fig(fig), use_container_width=True)

    with col2:
        section("Utilization rate by project")
        by_project = pd.DataFrame(report["by_project"])
        fig2 = px.bar(by_project, x="project", y="utilization_%", text="utilization_%",
                      color_discrete_sequence=[RED])
        fig2.update_traces(marker_color=RED)
        st.plotly_chart(style_fig(fig2), use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)
    section("🚨 Equipment needing immediate attention")
    attention = pd.DataFrame(tools.get_equipment_needing_attention()["data"])
    if attention.empty:
        st.success("No equipment currently needs immediate attention ✅")
    else:
        st.dataframe(attention[["equipment_id", "equipment_type", "project", "reason"]],
                     use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)
    section("🎯 Unified priority ranking (Attention Score)")
    st.caption("Combines downtime + fuel deviation + maintenance frequency + ML anomaly detection into one 0-100 score")
    scores = pd.DataFrame(ml_anomaly.compute_attention_scores()["data"])
    fig3 = go.Figure(go.Bar(
        x=scores["equipment_id"], y=scores["attention_score"],
        marker=dict(color=scores["attention_score"], colorscale=[[0, STEEL], [0.5, GOLD], [1, RED]]),
        text=scores["attention_score"], textposition="outside",
    ))
    st.plotly_chart(style_fig(fig3, height=350), use_container_width=True)

# ============================== TAB 2: CHAT ==============================
with tab_chat:
    section("Ask the AI agent about your fleet")
    st.caption("Try: 'Which equipment has the highest downtime?' / 'Which equipment needs urgent attention?' "
               "/ 'What\'s causing the fuel increase?' / 'Give me a unified priority ranking'")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for role, msg in st.session_state.chat_history:
        with st.chat_message(role):
            st.markdown(msg)

    user_q = st.chat_input("Type your question here...")
    if user_q:
        st.session_state.chat_history.append(("user", user_q))
        with st.chat_message("user"):
            st.markdown(user_q)

        with st.chat_message("assistant"):
            with st.spinner("Analyzing..."):
                answer = agent.ask_agent(user_q)
                st.markdown(answer)
        st.session_state.chat_history.append(("assistant", answer))

# ============================== TAB 3: REPORT ==============================
with tab_report:
    section("📋 Full Fleet Performance Report")
    report = tools.generate_fleet_report()

    st.markdown(f"**Period:** {report['period']}")
    st.markdown(f"**Fleet size:** {report['fleet_size']}")
    st.markdown(f"**Overall utilization rate:** {report['overall_utilization_%']}%")

    st.markdown("#### Performance by project")
    st.dataframe(pd.DataFrame(report["by_project"]), use_container_width=True, hide_index=True)

    st.markdown("#### Top 3 downtime issues")
    st.dataframe(pd.DataFrame(report["top_downtime_equipment"]), use_container_width=True, hide_index=True)

    if report["fuel_anomalies"]:
        st.markdown("#### ⚠️ Fuel consumption alerts")
        st.dataframe(pd.DataFrame(report["fuel_anomalies"]), use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Download report as CSV",
        pd.DataFrame(report["by_project"]).to_csv(index=False).encode("utf-8-sig"),
        file_name="fleet_performance_report.csv",
    )

# ============================== TAB 4: UPLOAD YOUR DATA ==============================
with tab_upload:
    section("📂 Test FleetOps AI on your own data")
    st.markdown(
        "Upload your own equipment master list and daily operations log to run the **exact same "
        "analysis pipeline** shown above against real or different data. Uploaded files are processed "
        "in the app session. If LLM mode is enabled, relevant tool results may be sent to the configured "
        "LLM provider to generate the response."
    )

    st.markdown("**Required columns**")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("`equipment_master.csv`")
        st.code(", ".join(sorted(REQUIRED_EQUIP_COLS)), language="text")
    with col_b:
        st.markdown("`fleet_daily_logs.csv`")
        st.code(", ".join(sorted(REQUIRED_DAILY_COLS)), language="text")

    st.download_button("⬇️ Download a sample equipment_master.csv (as a template)",
                        open("data/equipment_master.csv", "rb").read(),
                        file_name="equipment_master_template.csv")
    st.download_button("⬇️ Download a sample fleet_daily_logs.csv (as a template)",
                        open("data/fleet_daily_logs.csv", "rb").read(),
                        file_name="fleet_daily_logs_template.csv")

    st.divider()
    up_equip = st.file_uploader("Upload equipment_master.csv", type="csv", key="up_equip")
    up_daily = st.file_uploader("Upload fleet_daily_logs.csv", type="csv", key="up_daily")

    if up_equip and up_daily:
        try:
            new_equip = pd.read_csv(up_equip)
            new_daily = pd.read_csv(up_daily)

            missing_e = REQUIRED_EQUIP_COLS - set(new_equip.columns)
            missing_d = REQUIRED_DAILY_COLS - set(new_daily.columns)

            if missing_e or missing_d:
                if missing_e:
                    st.error(f"equipment_master.csv is missing required columns: {sorted(missing_e)}")
                if missing_d:
                    st.error(f"fleet_daily_logs.csv is missing required columns: {sorted(missing_d)}")
            else:
                tools.set_data_source(new_equip, new_daily)
                if not st.session_state.get("custom_data_active", False):
                    st.session_state["custom_data_active"] = True
                    st.rerun()
                st.success(f"✅ Loaded {new_equip['equipment_id'].nunique()} units, "
                           f"{len(new_daily)} daily records. Switch to the Overview or Ask the Agent "
                           "tabs — they now use your uploaded data.")
                st.dataframe(new_daily.head(10), use_container_width=True)
        except Exception as e:
            st.error(f"Could not read the uploaded files: {e}")
    else:
        if tools.using_custom_data():
            tools.reset_data_source()
            st.session_state["custom_data_active"] = False
            st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("""
<div class="xcmg-footer">
    FleetOps AI — Built for the China International College Students' Innovation &amp; Entrepreneurship Competition
    &nbsp;|&nbsp; Track: AI + Construction Machinery → AI + Operations
</div>
""", unsafe_allow_html=True)
