# app.py
"""SUPPLY-1000 -- US Government Supply Chain Scoring Platform."""
import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_logic import (
    AXES_LABELS, score_all_top_companies, get_company_profile,
    score_company, get_supply_chain_network, autocomplete_recipient,
)
from ui_components import inject_css, render_radar_chart

APP_TITLE = "SUPPLY-1000 -- Supply Chain Scoring"
st.set_page_config(page_title=APP_TITLE, page_icon="\u26d3\ufe0f", layout="wide")

# ---------------------------------------------------------------------------
# Score history
# ---------------------------------------------------------------------------
SCORES_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "scores_history.json")


def _load_scores_history() -> dict:
    if os.path.exists(SCORES_HISTORY_FILE):
        with open(SCORES_HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}


def render_score_delta(asset_name: str, current_total: int):
    history = _load_scores_history()
    if not history:
        return
    dates = sorted(history.keys(), reverse=True)
    prev_score = None
    for d in dates:
        s = history[d].get(asset_name)
        if s is not None:
            prev_score = s
            break
    if prev_score is None:
        return
    delta = current_total - prev_score
    if delta > 0:
        color, arrow = "#10b981", "&#9650;"
    elif delta < 0:
        color, arrow = "#ef4444", "&#9660;"
    else:
        color, arrow = "#94a3b8", "&#9644;"
    st.markdown(
        f'<div style="text-align:center; font-size:1.1em; font-weight:700; color:{color}; margin-top:-8px; margin-bottom:10px;">'
        f'{arrow} {delta:+d} from last record ({prev_score})'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_daily_score_tracker(asset_name: str):
    history = _load_scores_history()
    if not history:
        st.caption("No daily score records yet.")
        return
    dates = sorted(history.keys())
    values, valid_dates = [], []
    for d in dates:
        score = history[d].get(asset_name)
        if score is not None:
            valid_dates.append(d)
            values.append(score)
    if len(valid_dates) < 2:
        st.caption(f"Not enough daily records for {asset_name} yet.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=valid_dates, y=values, mode='lines+markers', name=asset_name,
        line=dict(color='#2E7BE6', width=2), marker=dict(size=5),
        fill='tozeroy', fillcolor='rgba(46,123,230,0.05)',
    ))
    fig.update_layout(
        yaxis=dict(range=[0, 1000], title="Score"), height=250,
        margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor='white',
        hovermode="x unified", clickmode='none', dragmode=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_dollar(amount: float) -> str:
    """Format large dollar amounts."""
    if amount >= 1e12:
        return f"${amount / 1e12:.1f}T"
    if amount >= 1e9:
        return f"${amount / 1e9:.1f}B"
    if amount >= 1e6:
        return f"${amount / 1e6:.0f}M"
    if amount >= 1e3:
        return f"${amount / 1e3:.0f}K"
    return f"${amount:,.0f}"


def _score_color(total: int) -> str:
    """Return color based on score tier."""
    if total >= 800:
        return "#10b981"
    if total >= 600:
        return "#2E7BE6"
    if total >= 400:
        return "#f59e0b"
    return "#ef4444"


# ---------------------------------------------------------------------------
# Logic descriptions
# ---------------------------------------------------------------------------

LOGIC_DESC = {
    "Contract Volume": "Total contract value (prime + sub) and number of contracts, percentile-ranked against peers.",
    "Diversification": "Number of different agencies and prime contractors. Single-client concentration reduces score.",
    "Contract Continuity": "Years of active government contracting. Consecutive-year bonuses for recurring relationships.",
    "Network Position": "Prime contractor status, sub-contractor network size, and supply chain hub importance.",
    "Growth Momentum": "Year-over-year change in contract value, percentile-ranked. New contract acquisition bonus.",
}


# ---------------------------------------------------------------------------
# Supply chain network graph
# ---------------------------------------------------------------------------

def render_network_graph(network: dict, company_name: str):
    """Render a Plotly network graph showing prime->sub connections."""
    connections = network.get("connections", [])
    if not connections:
        st.info("No supply chain connections found for this company.")
        return

    # Build node list and edge list
    nodes = set()
    edges = []
    for conn in connections:
        nodes.add(conn["from"])
        nodes.add(conn["to"])
        edges.append(conn)

    node_list = list(nodes)
    node_idx = {n: i for i, n in enumerate(node_list)}

    # Simple circular layout
    import math
    n = len(node_list)
    positions = {}
    for i, node in enumerate(node_list):
        angle = 2 * math.pi * i / n
        positions[node] = (math.cos(angle), math.sin(angle))

    # Center the target company
    if company_name in positions:
        positions[company_name] = (0, 0)

    # Build edge traces
    edge_x, edge_y = [], []
    for edge in edges:
        x0, y0 = positions.get(edge["from"], (0, 0))
        x1, y1 = positions.get(edge["to"], (0, 0))
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode='lines',
        line=dict(width=1.5, color='#94a3b8'),
        hoverinfo='none',
    )

    # Build node traces
    node_x = [positions[n][0] for n in node_list]
    node_y = [positions[n][1] for n in node_list]
    node_colors = []
    node_sizes = []
    for node in node_list:
        if node == company_name:
            node_colors.append('#2E7BE6')
            node_sizes.append(25)
        elif node in [c["from"] for c in connections if c["type"] == "prime"]:
            node_colors.append('#64748b')
            node_sizes.append(18)
        else:
            node_colors.append('#94a3b8')
            node_sizes.append(12)

    # Truncate long names for display
    display_names = [n[:30] + "..." if len(n) > 30 else n for n in node_list]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode='markers+text',
        marker=dict(size=node_sizes, color=node_colors, line=dict(width=1, color='white')),
        text=display_names,
        textposition="top center",
        textfont=dict(size=9),
        hovertext=node_list,
        hoverinfo='text',
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=10, r=10, t=10, b=10),
        height=450,
        plot_bgcolor='white',
        clickmode='none', dragmode=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def generate_csv(data: dict) -> bytes:
    rows = []
    for k in AXES_LABELS:
        desc = LOGIC_DESC.get(k, "")
        rows.append({"Axis": k, "Score": int(data["axes"].get(k, 0)), "Description": desc})
    rows.append({"Axis": "TOTAL", "Score": int(data.get("total", 0)), "Description": ""})
    rows.append({"Axis": "", "Score": "", "Description": ""})
    rows.append({"Axis": "Total Contract Value", "Score": _fmt_dollar(data.get("total_value", 0)), "Description": ""})
    rows.append({"Axis": "Agencies", "Score": data.get("agency_count", 0), "Description": ""})
    rows.append({"Axis": "Sub-contractors", "Score": data.get("sub_contractor_count", 0), "Description": ""})
    rows.append({"Axis": "Years Active", "Score": data.get("years_active", 0), "Description": ""})
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    inject_css()
    st.markdown("""
    <style>
    .block-container { padding-top: 1rem !important; }
    header[data-testid="stHeader"] { display: none !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    .viewerBadge_container__r5tak { display: none !important; }
    .styles_viewerBadge__CvC9N { display: none !important; }
    [data-testid="stActionButtonIcon"] { display: none !important; }
    [data-testid="manage-app-button"] { display: none !important; }
    a[href*="github.com"] img { display: none !important; }
    div[class*="viewerBadge"] { display: none !important; }
    div[class*="StatusWidget"] { display: none !important; }
    div[data-testid="stStatusWidget"] { display: none !important; }
    iframe[title="streamlit_lottie.streamlit_lottie"] { display: none !important; }
    .stDeployButton { display: none !important; }
    div[class*="stToolbar"] { display: none !important; }
    div.embeddedAppMetaInfoBar_container__DxxL1 { display: none !important; }
    div[class*="embeddedAppMetaInfoBar"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

    # Session state
    if "saved_company_data" not in st.session_state:
        st.session_state.saved_company_data = None

    # Tabs
    tab_dash, tab_detail, tab_rankings = st.tabs(["Dashboard", "Company Detail", "Rankings"])

    # ===================================================================
    # DASHBOARD TAB
    # ===================================================================
    with tab_dash:
        st.markdown(
            "<div style='font-size:1.5em; font-weight:900; color:#1e3a8a; margin-bottom:5px;'>"
            "Supply Chain Dashboard</div>"
            "<p style='color:#64748b; margin-bottom:20px;'>"
            "Real-time supply chain health scores for top US government contractors, "
            "powered by USAspending.gov data.</p>",
            unsafe_allow_html=True,
        )

        with st.expander("How to use SUPPLY-1000"):
            st.markdown("""
**Dashboard** shows the top government contractors ranked by supply chain health (0-1000).

**Company Detail** lets you search any contractor and see their full supply chain profile, including a network visualization of prime-to-sub relationships.

**Rankings** shows all scored companies in a card-based ranking format.

**Scoring axes:** Contract Volume, Diversification, Contract Continuity, Network Position, and Growth Momentum. Each axis is scored 0-200 using percentile ranking.

**Data source:** USAspending.gov (free, public API). All data is live from the US government's official spending database.
""")

        # Load top companies
        all_scores = []
        with st.spinner("Loading supply chain data from USAspending.gov..."):
            all_scores = score_all_top_companies(year=2024, limit=50)

        if not all_scores:
            st.error("Could not load data from USAspending.gov. Please try again later.")
            return

        # Key metrics row
        avg_score = sum(s["total"] for s in all_scores) / len(all_scores)
        total_contract_value = sum(s["total_value"] for s in all_scores)
        total_subs = sum(s["sub_contractor_count"] for s in all_scores)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f"<div class='card' style='text-align:center; padding:25px;'>"
                f"<div style='font-size:14px; color:#64748b; font-weight:600;'>AVG SUPPLY CHAIN SCORE</div>"
                f"<div style='font-size:42px; font-weight:900; color:#2E7BE6;'>{avg_score:.0f}</div>"
                f"<div style='font-size:12px; color:#94a3b8;'>/ 1000</div></div>",
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"<div class='card' style='text-align:center; padding:25px;'>"
                f"<div style='font-size:14px; color:#64748b; font-weight:600;'>COMPANIES SCORED</div>"
                f"<div style='font-size:42px; font-weight:900; color:#1e293b;'>{len(all_scores)}</div>"
                f"<div style='font-size:12px; color:#94a3b8;'>top contractors</div></div>",
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"<div class='card' style='text-align:center; padding:25px;'>"
                f"<div style='font-size:14px; color:#64748b; font-weight:600;'>TOTAL CONTRACT VALUE</div>"
                f"<div style='font-size:42px; font-weight:900; color:#1e293b;'>{_fmt_dollar(total_contract_value)}</div>"
                f"<div style='font-size:12px; color:#94a3b8;'>prime awards</div></div>",
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f"<div class='card' style='text-align:center; padding:25px;'>"
                f"<div style='font-size:14px; color:#64748b; font-weight:600;'>SUB-CONTRACTORS</div>"
                f"<div style='font-size:42px; font-weight:900; color:#1e293b;'>{total_subs}</div>"
                f"<div style='font-size:12px; color:#94a3b8;'>in network</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)

        # Top 10 / Bottom 10
        col_top, col_bot = st.columns(2)
        with col_top:
            st.markdown("<div class='section-title'>TOP 10 SUPPLY CHAINS</div>", unsafe_allow_html=True)
            for i, s in enumerate(all_scores[:10]):
                color = _score_color(s["total"])
                st.markdown(
                    f"<div class='dna-card'>"
                    f"<div><span style='font-size:18px; font-weight:900; color:#94a3b8; margin-right:12px;'>#{i+1}</span>"
                    f"<span class='dna-label'>{s['name']}</span></div>"
                    f"<div class='dna-value' style='color:{color};'>{s['total']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        with col_bot:
            st.markdown("<div class='section-title'>BOTTOM 10 SUPPLY CHAINS</div>", unsafe_allow_html=True)
            bottom = all_scores[-10:]
            bottom.reverse()
            for i, s in enumerate(bottom):
                rank = len(all_scores) - i
                color = _score_color(s["total"])
                st.markdown(
                    f"<div class='dna-card'>"
                    f"<div><span style='font-size:18px; font-weight:900; color:#94a3b8; margin-right:12px;'>#{rank}</span>"
                    f"<span class='dna-label'>{s['name']}</span></div>"
                    f"<div class='dna-value' style='color:{color};'>{s['total']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # Score distribution chart
        st.markdown("<div class='section-title'>SCORE DISTRIBUTION</div>", unsafe_allow_html=True)
        df_dist = pd.DataFrame(all_scores)
        fig_dist = px.histogram(
            df_dist, x="total", nbins=20,
            color_discrete_sequence=["#2E7BE6"],
            labels={"total": "Supply Chain Score"},
        )
        fig_dist.update_layout(
            yaxis_title="Number of Companies",
            plot_bgcolor='white', margin=dict(l=0, r=0, t=10, b=0),
            height=300, clickmode='none', dragmode=False,
            showlegend=False,
        )
        st.plotly_chart(fig_dist, use_container_width=True, config={"displayModeBar": False})

    # ===================================================================
    # COMPANY DETAIL TAB
    # ===================================================================
    with tab_detail:
        st.markdown(
            "<div style='font-size:1.5em; font-weight:900; color:#1e3a8a; margin-bottom:5px;'>"
            "Company Detail</div>",
            unsafe_allow_html=True,
        )

        # Company search
        search_text = st.text_input(
            "Search company name",
            placeholder="e.g. Lockheed Martin, Raytheon, Boeing...",
            key="company_search",
        )

        # Load scores for dropdown
        if "all_scores_cache" not in st.session_state:
            st.session_state.all_scores_cache = []

        all_scores_for_select = st.session_state.all_scores_cache
        if not all_scores_for_select:
            with st.spinner("Loading company list..."):
                all_scores_for_select = score_all_top_companies(year=2024, limit=50)
                st.session_state.all_scores_cache = all_scores_for_select

        company_names = [s["name"] for s in all_scores_for_select]

        # If search text, try autocomplete
        if search_text:
            matches = autocomplete_recipient(search_text, limit=10)
            if matches:
                # Filter to just the name strings
                match_names = []
                for m in matches:
                    if isinstance(m, dict):
                        match_names.append(m.get("recipient_name", str(m)))
                    else:
                        match_names.append(str(m))
                selected_name = st.selectbox(
                    "Select from matches", match_names, key="match_select"
                )
            else:
                selected_name = search_text
        else:
            if company_names:
                selected_name = st.selectbox(
                    "Or select from top contractors", company_names, key="top_select"
                )
            else:
                selected_name = None

        if selected_name:
            # Check if already in our scored list
            existing = None
            for s in all_scores_for_select:
                if s["name"].upper() == selected_name.upper():
                    existing = s
                    break

            if existing:
                data = existing
            else:
                with st.spinner(f"Building profile for {selected_name}..."):
                    profile = get_company_profile(selected_name)
                    data = score_company(profile, [profile])

            # Save/Clear buttons
            col_save, col_clear = st.columns([1, 1])
            with col_save:
                if st.button("Save for comparison"):
                    st.session_state.saved_company_data = data
            with col_clear:
                if st.button("Clear comparison"):
                    st.session_state.saved_company_data = None

            # Total score centered
            st.markdown(
                f"<div class='total-score-container'>"
                f"<div class='total-score-label'>SUPPLY CHAIN HEALTH SCORE</div>"
                f"<div class='total-score-val'>{data['total']}</div>"
                f"<div style='font-size:16px; color:#94a3b8; font-weight:600;'>/ 1000</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            render_score_delta(data["name"], data["total"])

            # Radar + Score cards
            col_radar, col_cards = st.columns([1, 1])

            with col_radar:
                fig = render_radar_chart(
                    data, st.session_state.saved_company_data, AXES_LABELS
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            with col_cards:
                for axis in AXES_LABELS:
                    score_val = data["axes"].get(axis, 0)
                    st.markdown(
                        f"<div class='dna-card'>"
                        f"<div class='dna-label'>{axis}</div>"
                        f"<div class='dna-value'>{score_val} <span style='font-size:12px; color:#94a3b8;'>/ 200</span></div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    with st.expander(f"Why {axis}?"):
                        st.markdown(f"**Formula:** {LOGIC_DESC.get(axis, '')}")
                        if axis == "Contract Volume":
                            st.markdown(f"- Total contract value: {_fmt_dollar(data.get('total_value', 0))}")
                            st.markdown(f"- Prime value: {_fmt_dollar(data.get('total_prime_value', 0))}")
                            st.markdown(f"- Sub value: {_fmt_dollar(data.get('total_sub_value', 0))}")
                            st.markdown(f"- Contract count: {data.get('contract_count', 0)}")
                        elif axis == "Diversification":
                            st.markdown(f"- Agencies worked with: {data.get('agency_count', 0)}")
                            st.markdown(f"- Prime contractors (as sub): {data.get('prime_contractor_count', 0)}")
                        elif axis == "Contract Continuity":
                            st.markdown(f"- Years active: {data.get('years_active', 0)}")
                        elif axis == "Network Position":
                            st.markdown(f"- Sub-contractors managed: {data.get('sub_contractor_count', 0)}")
                            has_prime = data.get("total_prime_value", 0) > 0
                            st.markdown(f"- Is prime contractor: {'Yes' if has_prime else 'No'}")
                        elif axis == "Growth Momentum":
                            yoy = data.get("yoy_change", 0)
                            st.markdown(f"- YoY change: {yoy:+.1%}")

            # Key metrics
            st.markdown("<div class='section-title'>KEY METRICS</div>", unsafe_allow_html=True)
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Total Contract Value", _fmt_dollar(data.get("total_value", 0)))
            with m2:
                st.metric("Agencies", data.get("agency_count", 0))
            with m3:
                st.metric("Sub-contractors", data.get("sub_contractor_count", 0))
            with m4:
                st.metric("Years Active", data.get("years_active", 0))

            # Daily score tracker
            st.markdown("<div class='section-title'>SCORE HISTORY</div>", unsafe_allow_html=True)
            render_daily_score_tracker(data["name"])

            # Supply chain network visualization
            st.markdown("<div class='section-title'>SUPPLY CHAIN MAP</div>", unsafe_allow_html=True)
            with st.spinner("Loading supply chain network..."):
                network = get_supply_chain_network(data["name"], year=2024)
            render_network_graph(network, data["name"])

            # Network details
            col_primes, col_subs = st.columns(2)
            with col_primes:
                prime_contracts = network.get("prime_contracts", [])
                if prime_contracts:
                    st.markdown("**Prime Contracts (from agencies):**")
                    for pc in prime_contracts[:10]:
                        st.markdown(
                            f"- {pc['agency']}: {_fmt_dollar(pc['amount'])}"
                        )
                sub_received = network.get("sub_contracts_received", [])
                if sub_received:
                    st.markdown("**Sub-contracts received (from primes):**")
                    for sr in sub_received[:10]:
                        st.markdown(
                            f"- {sr['prime_name']}: {_fmt_dollar(sr['amount'])}"
                        )
            with col_subs:
                sub_given = network.get("sub_contracts_given", [])
                if sub_given:
                    st.markdown("**Sub-contracts given (to subs):**")
                    for sg in sub_given[:10]:
                        st.markdown(
                            f"- {sg['sub_name']}: {_fmt_dollar(sg['amount'])}"
                        )

            # CSV download
            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
            csv_data = generate_csv(data)
            st.download_button(
                label="Download CSV Report",
                data=csv_data,
                file_name=f"supply1000_{data['name'].replace(' ', '_')}.csv",
                mime="text/csv",
            )

    # ===================================================================
    # RANKINGS TAB
    # ===================================================================
    with tab_rankings:
        st.markdown(
            "<div style='font-size:1.5em; font-weight:900; color:#1e3a8a; margin-bottom:5px;'>"
            "Supply Chain Rankings</div>"
            "<p style='color:#64748b; margin-bottom:20px;'>"
            "All scored companies ranked by supply chain health.</p>",
            unsafe_allow_html=True,
        )

        # Load scores
        if not all_scores_for_select:
            with st.spinner("Loading rankings..."):
                all_scores_for_select = score_all_top_companies(year=2024, limit=50)

        if all_scores_for_select:
            for i, s in enumerate(all_scores_for_select):
                rank = i + 1
                total = s["total"]
                color = _score_color(total)

                # Build axis bar HTML
                axis_bars = ""
                for axis in AXES_LABELS:
                    val = s["axes"].get(axis, 0)
                    pct = val / 200 * 100
                    axis_bars += (
                        f"<div style='display:flex; align-items:center; margin:4px 0;'>"
                        f"<div style='width:130px; font-size:11px; color:#64748b;'>{axis}</div>"
                        f"<div style='flex:1; background:#f1f5f9; border-radius:4px; height:14px; margin:0 8px;'>"
                        f"<div style='width:{pct}%; background:{color}; height:100%; border-radius:4px;'></div></div>"
                        f"<div style='width:40px; font-size:12px; font-weight:700; color:#1e293b; text-align:right;'>{val}</div>"
                        f"</div>"
                    )

                st.markdown(
                    f"<div class='card' style='margin-bottom:12px; padding:18px 24px;'>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>"
                    f"<div>"
                    f"<span style='font-size:20px; font-weight:900; color:#94a3b8; margin-right:12px;'>#{rank}</span>"
                    f"<span style='font-size:18px; font-weight:700; color:#1e293b;'>{s['name']}</span>"
                    f"</div>"
                    f"<div style='font-size:32px; font-weight:900; color:{color};'>{total}</div>"
                    f"</div>"
                    f"<div style='display:flex; gap:20px; font-size:12px; color:#64748b; margin-bottom:10px;'>"
                    f"<span>Value: {_fmt_dollar(s.get('total_value', 0))}</span>"
                    f"<span>Agencies: {s.get('agency_count', 0)}</span>"
                    f"<span>Subs: {s.get('sub_contractor_count', 0)}</span>"
                    f"<span>YoY: {s.get('yoy_change', 0):+.0%}</span>"
                    f"</div>"
                    f"{axis_bars}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # Methodology
            with st.expander("Methodology"):
                st.markdown("""
**SUPPLY-1000 Scoring Methodology**

Each company is scored on 5 axes (0-200 each, total 0-1000) using percentile ranking among all scored companies.

| Axis | Weight | Description |
|------|--------|-------------|
| Contract Volume | 0-200 | Total contract value and count, percentile-ranked |
| Diversification | 0-200 | Agency diversity and client concentration |
| Contract Continuity | 0-200 | Years active with consecutive-year bonuses |
| Network Position | 0-200 | Prime/sub status and hub importance |
| Growth Momentum | 0-200 | YoY contract value change and new acquisitions |

**Data source:** USAspending.gov, the official source for US government spending data. Updated daily by the US Treasury.
""")
        else:
            st.warning("No scoring data available. Please try again later.")


if __name__ == "__main__":
    main()
