# app.py
"""SUPPLY-1000 -- US Government Supply Chain Scoring Platform."""
import json
import math
import os

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_logic import (
    AXES_LABELS, score_all_top_companies, get_company_profile,
    score_company, get_supply_chain_network, autocomplete_recipient,
    apply_vital_pulse_modifier, apply_environment_adjustment,
)
from environment_scores import calculate_environment_adjustment
from vital_pulse import run_vital_pulse
from entity_resolver import assign_company_ids
from graph_analysis import (
    build_supply_chain_graph, calculate_network_metrics,
    simulate_risk_propagation, get_company_ego_network, get_critical_path,
)
from ui_components import inject_css, render_radar_chart
# pdf_report imported lazily when PDF download is triggered

APP_TITLE = "SUPPLY-1000 -- Supply Chain Scoring"
st.set_page_config(page_title=APP_TITLE, page_icon="\u26d3\ufe0f", layout="wide")

# ---------------------------------------------------------------------------
# Score history
# ---------------------------------------------------------------------------
SCORES_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "scores_history.json")
SCORES_CACHE_FILE = os.path.join(os.path.dirname(__file__), "scores_cache.json")


def _load_scores_history() -> dict:
    if os.path.exists(SCORES_HISTORY_FILE):
        with open(SCORES_HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}


def _load_scores_cache() -> list[dict]:
    """Load pre-calculated scores from cache (includes VP-1000 + environment).
    Returns list of scored company dicts, or empty list if cache not available.
    """
    if os.path.exists(SCORES_CACHE_FILE):
        try:
            with open(SCORES_CACHE_FILE, "r") as f:
                cache = json.load(f)
            return cache.get("companies", [])
        except Exception:
            pass
    return []


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
# Sample network data loader
# ---------------------------------------------------------------------------
SAMPLE_DATA_FILE = os.path.join(os.path.dirname(__file__), "dod_sample_data.json")


@st.cache_data(ttl=86400)
def load_sample_network():
    """Load dod_sample_data.json, resolve entities, build graph."""
    if not os.path.exists(SAMPLE_DATA_FILE):
        return None, {}, []
    try:
        with open(SAMPLE_DATA_FILE, "r") as f:
            data = json.load(f)
        records = data.get("records", [])
        if not records:
            return None, {}, []
        # Entity resolution
        resolved = assign_company_ids(records)
        # Build graph
        G = build_supply_chain_graph(resolved)
        # Calculate metrics
        metrics = calculate_network_metrics(G)
        return G, metrics, resolved
    except Exception:
        return None, {}, []


def _render_plotly_network(G, title_label="Supply Chain Network", top_n=50):
    """Render a Plotly network graph from a NetworkX DiGraph.

    Node size = total contract value (scaled).
    Node color = pagerank score (green=high, red=low).
    Shows top_n companies by total value to avoid cluttering.
    """
    if G is None or len(G.nodes) == 0:
        st.info("No network data available.")
        return

    # Pick top N nodes by total value (received + awarded)
    node_values = {}
    for node in G.nodes:
        received = G.nodes[node].get("total_received", 0)
        awarded = G.nodes[node].get("total_awarded", 0)
        node_values[node] = received + awarded

    sorted_nodes = sorted(node_values.keys(), key=lambda n: node_values[n], reverse=True)
    top_nodes = set(sorted_nodes[:top_n])

    # Build subgraph
    subG = G.subgraph(top_nodes).copy()
    if len(subG.nodes) == 0:
        st.info("No network data available.")
        return

    # Layout: spring layout
    try:
        pos = nx.spring_layout(subG, k=2.0 / math.sqrt(max(len(subG.nodes), 1)), iterations=50, seed=42)
    except Exception:
        pos = nx.circular_layout(subG)

    node_list = list(subG.nodes)

    # Compute pagerank for coloring
    try:
        pr = nx.pagerank(subG, weight="total_amount", max_iter=200)
    except Exception:
        pr = {n: 0.5 for n in node_list}

    max_pr = max(pr.values()) if pr else 1
    min_pr = min(pr.values()) if pr else 0
    pr_range = max_pr - min_pr if max_pr != min_pr else 1

    # Build edge traces
    edge_x, edge_y = [], []
    for u, v in subG.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=0.8, color="#d1d5db"),
        hoverinfo="none",
    )

    # Build node traces
    node_x = [pos[n][0] for n in node_list]
    node_y = [pos[n][1] for n in node_list]

    max_val = max(node_values[n] for n in node_list) if node_list else 1
    node_sizes = []
    node_colors = []
    hover_texts = []
    display_names = []

    for n in node_list:
        val = node_values.get(n, 0)
        # Scale size: min 8, max 40
        size = 8 + 32 * (val / max_val) if max_val > 0 else 12
        node_sizes.append(size)

        # Color: green (high pagerank) to red (low pagerank)
        normalized = (pr.get(n, 0) - min_pr) / pr_range
        r_val = int(239 * (1 - normalized) + 16 * normalized)
        g_val = int(68 * (1 - normalized) + 185 * normalized)
        b_val = int(68 * (1 - normalized) + 129 * normalized)
        node_colors.append(f"rgb({r_val},{g_val},{b_val})")

        hover_texts.append(
            f"{n}<br>Total Value: {_fmt_dollar(val)}<br>"
            f"PageRank: {pr.get(n, 0):.4f}<br>"
            f"In-degree: {subG.in_degree(n)}, Out-degree: {subG.out_degree(n)}"
        )
        short = n[:25] + "..." if len(n) > 25 else n
        display_names.append(short)

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=node_sizes, color=node_colors, line=dict(width=1, color="white")),
        text=display_names,
        textposition="top center",
        textfont=dict(size=8),
        hovertext=hover_texts,
        hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=10, r=10, t=10, b=10),
        height=550,
        plot_bgcolor="white",
        clickmode="none", dragmode=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_ego_network(G, company, radius=2):
    """Render the ego network for a specific company."""
    if G is None or company not in G:
        st.info("This company is not in the sample network data.")
        return

    ego = get_company_ego_network(G, company, radius=radius)
    if len(ego.nodes) == 0:
        st.info("No network connections found for this company.")
        return

    try:
        pos = nx.spring_layout(ego, k=2.0 / math.sqrt(max(len(ego.nodes), 1)), iterations=50, seed=42)
    except Exception:
        pos = nx.circular_layout(ego)

    node_list = list(ego.nodes)

    # Edge traces
    edge_x, edge_y = [], []
    for u, v in ego.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1.2, color="#94a3b8"),
        hoverinfo="none",
    )

    # Node traces
    node_x = [pos[n][0] for n in node_list]
    node_y = [pos[n][1] for n in node_list]
    node_colors = []
    node_sizes = []
    hover_texts = []
    display_names = []

    for n in node_list:
        if n == company:
            node_colors.append("#2E7BE6")
            node_sizes.append(28)
        elif ego.nodes[n].get("is_prime", False):
            node_colors.append("#64748b")
            node_sizes.append(18)
        else:
            node_colors.append("#94a3b8")
            node_sizes.append(12)

        received = ego.nodes[n].get("total_received", 0)
        awarded = ego.nodes[n].get("total_awarded", 0)
        hover_texts.append(
            f"{n}<br>Received: {_fmt_dollar(received)}<br>Awarded: {_fmt_dollar(awarded)}"
        )
        short = n[:25] + "..." if len(n) > 25 else n
        display_names.append(short)

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=node_sizes, color=node_colors, line=dict(width=1, color="white")),
        text=display_names,
        textposition="top center",
        textfont=dict(size=9),
        hovertext=hover_texts,
        hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=10, r=10, t=10, b=10),
        height=450,
        plot_bgcolor="white",
        clickmode="none", dragmode=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# Logic descriptions
# ---------------------------------------------------------------------------

LOGIC_DESC = {
    "Contract Volume": "Contract value + count + YoY growth bonus",
    "Diversification": "Agency diversity + client concentration",
    "Contract Continuity": "Years active + consecutive year bonus",
    "Network Position": "Prime/sub status + hub importance",
    "Digital Resilience": "SSL health + email security (CYBER-1000)",
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
    tab_dash, tab_detail, tab_rankings, tab_batch = st.tabs(["Dashboard", "Company Detail", "Rankings", "Batch Score"])

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

**Scoring axes:** Contract Volume (with growth bonus), Diversification, Contract Continuity, Network Position, and Digital Resilience. Each axis is scored 0-200.

**Data source:** USAspending.gov (free, public API) + direct SSL/DNS scanning for Digital Resilience (powered by CYBER-1000 engine).
""")

        # Load top companies from pre-calculated cache (includes VP-1000 + environment)
        all_scores = []
        cached_scores = _load_scores_cache()
        if cached_scores:
            all_scores = cached_scores
        else:
            # Fallback: calculate live if cache not available
            with st.spinner("Loading supply chain data from USAspending.gov..."):
                all_scores = score_all_top_companies(year=2024, limit=50)
                for i, s in enumerate(all_scores):
                    env = calculate_environment_adjustment(
                        s.get("state_code"),
                        s.get("naics_code"),
                        s.get("prime_contractors", [None])[0] if s.get("prime_contractors") else None,
                    )
                    s = apply_environment_adjustment(s, env)
                    all_scores[i] = s
                all_scores.sort(key=lambda x: x["total"], reverse=True)

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
            total_agencies = sum(s.get("agency_count", 0) for s in all_scores)
            st.markdown(
                f"<div class='card' style='text-align:center; padding:25px;'>"
                f"<div style='font-size:14px; color:#64748b; font-weight:600;'>AGENCIES TRACKED</div>"
                f"<div style='font-size:42px; font-weight:900; color:#1e293b;'>{total_agencies}</div>"
                f"<div style='font-size:12px; color:#94a3b8;'>across portfolio</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<div style='text-align:center; font-size:11px; color:#94a3b8; margin-top:-10px; margin-bottom:10px;'>"
            "Scores include VP-1000 vital pulse and environment adjustment (pre-calculated daily)."
            "</div>",
            unsafe_allow_html=True,
        )

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

        # Supply Chain Network from sample data
        st.markdown("<div class='section-title'>SUPPLY CHAIN NETWORK (DoD Sample Data)</div>", unsafe_allow_html=True)
        sample_G, sample_metrics, _ = load_sample_network()
        if sample_G is not None and len(sample_G.nodes) > 0:
            st.caption(
                f"Showing top 50 companies by contract value from {len(sample_G.nodes)} total companies "
                f"and {len(sample_G.edges)} connections. "
                f"Node size = total contract value. Color = PageRank (green = high importance, red = low)."
            )
            _render_plotly_network(sample_G, top_n=50)
        else:
            st.info("Sample network data not available. Place dod_sample_data.json in the app directory.")

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

        # Load scores for dropdown (prefer cache with VP-1000 + environment)
        if "all_scores_cache" not in st.session_state:
            st.session_state.all_scores_cache = []

        all_scores_for_select = st.session_state.all_scores_cache
        if not all_scores_for_select:
            cached_scores_detail = _load_scores_cache()
            if cached_scores_detail:
                all_scores_for_select = cached_scores_detail
            else:
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
                # Re-score with cyber scan enabled for detail view
                data = dict(existing)
                # Deep copy axes so we don't mutate cached object
                data["axes"] = dict(data["axes"])
                from data_logic import _guess_domain, _scan_domain_quick
                domain = data.get("domain") or _guess_domain(selected_name)
                if domain:
                    with st.spinner(f"Scanning {domain} for Digital Resilience..."):
                        cyber_score, cyber_detail = _scan_domain_quick(domain)
                    data["domain"] = domain
                    data["digital_score_detail"] = cyber_detail
                    # Replace cyber axis without stripping VP/env adjustments
                    old_cyber = data["axes"].get("Digital Resilience", 0)
                    data["axes"]["Digital Resilience"] = cyber_score
                    # Adjust total by the cyber delta only, preserving VP/env baked into cached total
                    data["total"] = max(0, min(1000, data.get("total", 0) + (cyber_score - old_cyber)))
            else:
                with st.spinner(f"Building profile for {selected_name}..."):
                    profile = get_company_profile(selected_name)
                    profile["_run_cyber_scan"] = True
                    # Score against the full cached population, not just self
                    population = all_scores_for_select if all_scores_for_select else [profile]
                    # score_company expects raw profiles in population; convert if needed
                    if all_scores_for_select:
                        # Build minimal profile-like dicts for percentile comparison
                        pop_profiles = [{
                            "name": s["name"],
                            "total_prime_value": s.get("total_value", 0),
                            "total_sub_value": 0,
                            "agencies": ["x"] * s.get("agency_count", 0),
                            "prime_contractors": [],
                            "sub_contractors": ["x"] * s.get("sub_contractor_count", 0),
                            "yearly_values": s.get("yearly_values", {}),
                            "contract_count": s.get("contract_count", 1),
                            "years_active": list(range(s.get("years_active", 1))),
                        } for s in all_scores_for_select]
                        pop_profiles.append(profile)
                        data = score_company(profile, pop_profiles)
                    else:
                        data = score_company(profile, [profile])

            # Save/Clear + PDF/CSV buttons
            col_btn1, col_btn2, col_btn3, col_btn4, col_btn_rest = st.columns([1, 1, 1.5, 1.5, 5.5])

            with col_btn1:
                save_it = st.button("Save")
            with col_btn2:
                clear_it = st.button("Clear")
            with col_btn3:
                from pdf_report import generate_supply_pdf
                pdf_bytes = generate_supply_pdf(data, all_scores=all_scores_for_select)
                st.download_button("PDF", pdf_bytes, file_name=f"SUPPLY1000_{data['name'].replace(' ', '_')}.pdf", mime="application/pdf")
            with col_btn4:
                csv_data = generate_csv(data)
                st.download_button("CSV", csv_data, file_name=f"SUPPLY1000_{data['name'].replace(' ', '_')}.csv", mime="text/csv")

            if save_it:
                st.session_state.saved_company_data = data
                st.rerun()
            if clear_it:
                st.session_state.saved_company_data = None
                st.rerun()

            # Total score centered (FRS-1000 pattern)
            display_total = int(data.get("total", 0))
            base_axes_total = sum(int(data["axes"].get(k, 0)) for k in AXES_LABELS)
            vp_adj = int(data.get("vp_adjustment", 0))
            env_adj = int(data.get("env_adjustment", 0))

            # Score delta for inline display
            _delta_html = ""
            _history = _load_scores_history()
            if _history:
                _dates = sorted(_history.keys(), reverse=True)
                _prev = None
                for _d in _dates:
                    _s = _history[_d].get(data["name"])
                    if _s is not None:
                        _prev = _s
                        break
                if _prev is not None:
                    _delta = display_total - _prev
                    if _delta > 0:
                        _delta_html = f'<span style="font-size:24px; font-weight:700; color:#10b981; margin-left:12px;">+{_delta}</span><span style="font-size:14px; color:#94a3b8; margin-left:4px;">({_prev})</span>'
                    elif _delta < 0:
                        _delta_html = f'<span style="font-size:24px; font-weight:700; color:#ef4444; margin-left:12px;">{_delta}</span><span style="font-size:14px; color:#94a3b8; margin-left:4px;">({_prev})</span>'

            st.markdown(f"""
            <div style="text-align:center; margin-top:4px; margin-bottom:10px;">
                <div style="font-size:14px; letter-spacing:2px; color:#666;">TOTAL SCORE</div>
                <div style="font-size:90px; font-weight:800; color:#2E7BE6; line-height:1;">
                    {display_total}
                    <span style="font-size:35px; color:#BBB;">/ 1000</span>
                    {_delta_html}
                </div>
                <!-- axis breakdown available in radar chart below -->
            </div>
            """, unsafe_allow_html=True)

            # 3-Year Risk Indicator (based on backtest of 1,000 companies)
            _risk_bands = [
                (300, 43.8),   # avg of FY2015 31.6% and FY2018 55.9%
                (400, 31.1),   # avg of FY2015 27.5% and FY2018 34.7%
                (500, 22.4),   # avg of FY2015 20.9% and FY2018 23.8%
                (600, 17.6),   # avg of FY2015 16.0% and FY2018 19.2%
                (1001, 9.3),   # avg of FY2015 7.6% and FY2018 11.0%
            ]
            _risk_pct = 9.3
            for _threshold, _pct in _risk_bands:
                if display_total < _threshold:
                    _risk_pct = _pct
                    break
            if _risk_pct >= 30:
                _risk_color = "#ef4444"
                _risk_label = "High"
            elif _risk_pct >= 20:
                _risk_color = "#f59e0b"
                _risk_label = "Moderate"
            else:
                _risk_color = "#22c55e"
                _risk_label = "Low"
            st.markdown(f"""
            <div style="text-align:center; margin: -4px 0 16px;">
                <span style="font-size:12px; color:{_risk_color}; font-weight:700;
                    background:{_risk_color}15; padding:4px 14px; border-radius:20px;">
                    3-Year Risk: {_risk_pct:.1f}% negative outcome ({_risk_label})
                </span>
                <div style="font-size:10px; color:#94a3b8; margin-top:4px;">
                    Based on backtest of 1,000 government contractors (FY2015 + FY2018)
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Radar (left) + Score cards (right)
            col_left, col_right = st.columns([1.5, 1])

            with col_left:
                st.markdown("<div style='font-size: 1.1em; font-weight: bold; color: #333; margin-top: -10px; margin-bottom: 5px;'>I. Intelligence Radar</div>", unsafe_allow_html=True)
                fig = render_radar_chart(
                    data, st.session_state.saved_company_data, AXES_LABELS
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            with col_right:
                st.markdown(
                    "<div style='font-size: 0.9em; font-weight: bold; color: #333; margin-top: -10px; margin-bottom: 15px; border-left: 3px solid #2E7BE6; padding-left: 8px;'>II. ANALYSIS SCORE METRICS</div>",
                    unsafe_allow_html=True,
                )

                for axis in AXES_LABELS:
                    v1 = int(data["axes"].get(axis, 0))
                    v2 = int(st.session_state.saved_company_data["axes"].get(axis, 0)) if st.session_state.saved_company_data else None

                    desc_text = LOGIC_DESC.get(axis, "")

                    score_html = f'<span style="color: #2E7BE6;">{v1}</span><span style="color:#bbb;font-size:0.5em;font-weight:600;"> /200</span>'
                    if v2 is not None:
                        score_html += f' <span style="color: #ccc; font-size: 0.9em; font-weight:bold; margin: 0 6px;">vs</span> <span style="color: #F4A261;">{v2}</span><span style="color:#bbb;font-size:0.5em;font-weight:600;"> /200</span>'

                    st.markdown(
                        f"""
                        <div style="
                            background-color: #FFFFFF;
                            padding: 20px;
                            border-radius: 12px;
                            margin-bottom: 12px;
                            border: 1px solid #E0E0E0;
                            border-left: 8px solid #2E7BE6;
                            box-shadow: 2px 2px 5px rgba(0,0,0,0.07);
                        ">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <span style="font-size: 1.4em; font-weight: 800; color: #333333;">{axis}</span>
                                <span style="font-size: 1.9em; font-weight: 900; line-height: 1;">{score_html}</span>
                            </div>
                            <p style="font-size: 1.05em; color: #777777; margin: 0; line-height: 1.3; font-weight: 500;">{desc_text}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    with st.expander(f"Why {v1}?", expanded=False):
                        if axis == "Contract Volume":
                            _cc_disp = '100+' if data.get('contract_count', 0) >= 100 else data.get('contract_count', 0)
                            st.markdown(f"""
**Formula:** Percentile rank of total contract value (x120) + percentile rank of contract count (x40) + YoY growth bonus (-20 to +40). Capped at 200.
**Raw Data:** Value: {_fmt_dollar(data.get('total_value', 0))} | Contracts: {_cc_disp} | YoY: {data.get('yoy_change', 0):+.1%}
**Source:** USAspending.gov
                            """)
                        elif axis == "Diversification":
                            st.markdown(f"""
**Formula:** Percentile rank of agency count (x120) + percentile rank of prime-contractor count (x80) minus a 30-point penalty if a single agency provides over 80 percent of value. Capped at 200.
**Raw Data:** Agencies: {data.get('agency_count', 0)}
**Source:** USAspending.gov
                            """)
                        elif axis == "Contract Continuity":
                            st.markdown(f"""
**Formula:** Percentile rank of years active (x120) + consecutive-year ratio (x80). Capped at 200.
**Raw Data:** Years active: {data.get('years_active', 0)}
**Source:** USAspending.gov
                            """)
                        elif axis == "Network Position":
                            has_prime = data.get("total_prime_value", 0) > 0
                            st.markdown(f"""
**Formula:** Base 80 if the company is a prime contractor, 40 if sub-only. Plus percentile rank of sub-contractor network size (x80). Plus a hub bonus for primes that also manage many subs. Capped at 200.
**Raw Data:** Is prime: {'Yes' if has_prime else 'No'}
**Source:** USAspending.gov
                            """)
                        elif axis == "Digital Resilience":
                            domain = data.get("domain", "N/A")
                            detail = data.get("digital_score_detail")
                            if detail:
                                st.markdown(f"""
**Formula:** `SSL Health (50%) + Email Security (50%)`
**Raw Data:** Domain: {domain} | SSL: {detail.get('ssl', 'N/A')}/200 | Email: {detail.get('email', 'N/A')}/200
**Source:** Direct SSL/DNS scan of company domain
                                """)
                            else:
                                st.markdown(f"""
**No domain scanned for this company.**
Companies without a scanned domain show a proportionally estimated Digital Resilience score.
To get a real score, view the company in Company Detail (triggers live scan).
Domain guess: {domain}
                                """)

            # Claim this business (domain override)
            domain = data.get("domain")
            st.markdown("")
            with st.expander("Wrong domain? Claim this business"):
                st.markdown("If the auto-detected domain is incorrect or missing, enter the correct domain below to rescan.")
                col_domain, col_scan = st.columns([3, 1])
                with col_domain:
                    override_domain = st.text_input(
                        "Company domain",
                        value=domain or "",
                        placeholder="e.g. lockheedmartin.com",
                        key="domain_override",
                        label_visibility="collapsed",
                    )
                with col_scan:
                    rescan = st.button("Rescan")
                if rescan and override_domain:
                    with st.spinner(f"Scanning {override_domain}..."):
                        from data_logic import _scan_domain_quick
                        cyber_score, cyber_detail = _scan_domain_quick(override_domain)
                    data["domain"] = override_domain
                    data["digital_score_detail"] = cyber_detail
                    four_axes = sum(
                        data["axes"][k] for k in ["Contract Volume", "Diversification",
                                                   "Contract Continuity", "Network Position"]
                    )
                    data["axes"]["Digital Resilience"] = cyber_score
                    data["total"] = four_axes + cyber_score
                    st.success(f"Rescanned {override_domain}. Digital Resilience: {cyber_score}/200. New total: {data['total']}/1000")
                    st.rerun()

            # VP-1000: Vital Signs
            st.markdown("<div class='section-title'>VP-1000: VITAL SIGNS</div>", unsafe_allow_html=True)
            domain = data.get("domain")
            if domain:
                with st.spinner(f"Checking vital signs for {domain}..."):
                    vital = run_vital_pulse(domain)
                    data = apply_vital_pulse_modifier(data, vital)

                # Vital score display
                vs = vital["vital_score"]
                if vs >= 80:
                    vs_color, vs_label = "#10b981", "HEALTHY"
                elif vs >= 50:
                    vs_color, vs_label = "#2E7BE6", "STABLE"
                elif vs >= 30:
                    vs_color, vs_label = "#f59e0b", "WARNING"
                else:
                    vs_color, vs_label = "#ef4444", "CRITICAL"

                vp1, vp2 = st.columns([1, 2])
                with vp1:
                    st.markdown(f"""
                    <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #f8fafc, #e2e8f0); border-radius:16px;">
                        <div style="font-size:0.8em; color:#64748b; font-weight:700; letter-spacing:1px;">VITAL PULSE</div>
                        <div style="font-size:2.5em; font-weight:900; color:{vs_color};">{vs}</div>
                        <div style="font-size:0.9em; font-weight:700; color:{vs_color};">{vs_label}</div>
                        <div style="font-size:0.75em; color:#94a3b8; margin-top:4px;">Score modifier: x{data.get('vital_modifier', 1.0):.1f}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with vp2:
                    # Signal list
                    for signal_name, signal_type in vital["signals"]:
                        if signal_type == "positive":
                            icon, color = "&#9679;", "#10b981"  # green dot
                        elif signal_type == "negative":
                            icon, color = "&#9679;", "#ef4444"  # red dot
                        else:
                            icon, color = "&#9679;", "#94a3b8"  # gray dot
                        st.markdown(
                            f'<div style="display:flex; align-items:center; padding:6px 0;">'
                            f'<span style="color:{color}; font-size:1.2em; margin-right:10px;">{icon}</span>'
                            f'<span style="font-size:0.95em; color:#1e293b;">{signal_name}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    # Detail metrics
                    alive = vital["alive"]
                    careers = vital["careers"]
                    if alive["alive"]:
                        st.caption(f"Response time: {alive['response_time_ms']:.0f}ms")
                    if careers["has_careers"]:
                        st.caption(f"Careers page: {careers['careers_url']}")
            else:
                st.markdown(
                    '<div style="padding:20px; background:#fef2f2; border-radius:10px; border:1px solid #fecaca;">'
                    '<span style="color:#ef4444; font-weight:700;">No domain available.</span> '
                    'Use "Claim this business" above to add a domain and run vital checks.'
                    '</div>',
                    unsafe_allow_html=True,
                )

            # Layer 1 environment cards hidden until we have live cross-product data
            # GOV-1000 / REALESTATE-1000 / PORT-1000 / FRS-1000 integration is on the
            # roadmap. For now, the score is the 5-axis base only.
            # State chip also hidden because state_code from USAspending reflects
            # place of performance, not company HQ.

            # Key metrics
            st.markdown("<div class='section-title'>KEY METRICS</div>", unsafe_allow_html=True)
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Total Contract Value", _fmt_dollar(data.get("total_value", 0)))
            with m2:
                st.metric("Agencies", data.get("agency_count", 0))
            with m3:
                _cc = data.get("contract_count", 0)
                st.metric("Contracts", "100+" if _cc >= 100 else _cc)
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
                    st.markdown("**Prime Contracts (from agencies, FY2024):**")
                    for pc in prime_contracts[:10]:
                        st.markdown(
                            f"- {pc['agency']}: {_fmt_dollar(pc['amount'])}"
                        )
                sub_received = network.get("sub_contracts_received", [])
                if sub_received:
                    st.markdown("**Sub-contracts received (from primes, FY2024):**")
                    for sr in sub_received[:10]:
                        st.markdown(
                            f"- {sr['prime_name']}: {_fmt_dollar(sr['amount'])}"
                        )
            with col_subs:
                sub_given = network.get("sub_contracts_given", [])
                if sub_given:
                    st.markdown("**Sub-contracts given (to subs, FY2024):**")
                    for sg in sub_given[:10]:
                        st.markdown(
                            f"- {sg['sub_name']}: {_fmt_dollar(sg['amount'])}"
                        )

            # --- Sample network: Ego Network + Risk Propagation ---
            sample_G, sample_metrics, _ = load_sample_network()

            # Find matching node in graph (fuzzy match on name)
            graph_node = None
            if sample_G is not None:
                name_upper = data["name"].upper()
                for node in sample_G.nodes:
                    if name_upper in node.upper() or node.upper() in name_upper:
                        graph_node = node
                        break

            if graph_node is not None:
                # Ego network visualization
                st.markdown("<div class='section-title'>SUPPLY CHAIN MAP (Sample Network)</div>", unsafe_allow_html=True)
                st.caption(
                    f"Local network around {graph_node} (2 hops). "
                    f"Blue = target company, dark gray = prime contractors, light gray = sub-contractors."
                )
                _render_ego_network(sample_G, graph_node, radius=2)

                # Risk propagation
                st.markdown("<div class='section-title'>RISK PROPAGATION</div>", unsafe_allow_html=True)
                st.caption(f"What happens if {graph_node} fails? Simulated impact on connected companies.")

                risk = simulate_risk_propagation(sample_G, graph_node, decay_factor=0.7)
                if risk:
                    # Sort by impact descending
                    sorted_risk = sorted(risk.items(), key=lambda x: x[1], reverse=True)
                    for company_name, impact in sorted_risk[:15]:
                        # Determine relationship
                        if sample_G.has_edge(graph_node, company_name):
                            rel = "Direct sub-contractor"
                        elif sample_G.has_edge(company_name, graph_node):
                            rel = "Prime contractor (upstream)"
                        else:
                            rel = "Indirect connection"

                        if impact >= 50:
                            impact_color = "#ef4444"
                        elif impact >= 20:
                            impact_color = "#f59e0b"
                        else:
                            impact_color = "#94a3b8"

                        short_name = company_name[:40] + "..." if len(company_name) > 40 else company_name
                        st.markdown(
                            f"<div class='dna-card'>"
                            f"<div>"
                            f"<span class='dna-label'>{short_name}</span>"
                            f"<span style='font-size:11px; color:#64748b; margin-left:10px;'>{rel}</span>"
                            f"</div>"
                            f"<div class='dna-value' style='color:{impact_color};'>{impact:.0f}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("No significant downstream risk detected for this company.")

                # Network metrics for this company
                if graph_node in sample_metrics:
                    m = sample_metrics[graph_node]
                    st.markdown("<div class='section-title'>NETWORK METRICS</div>", unsafe_allow_html=True)
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    with mc1:
                        st.metric("PageRank", f"{m['pagerank']:.4f}")
                    with mc2:
                        st.metric("Betweenness", f"{m['betweenness_centrality']:.4f}")
                    with mc3:
                        st.metric("Hub Score", f"{m['hub_score']:.4f}")
                    with mc4:
                        st.metric("Authority Score", f"{m['authority_score']:.4f}")

            # (PDF/CSV download buttons are in the top button row)

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

        # Load scores from cache (includes VP-1000 + environment)
        if not all_scores_for_select:
            cached_scores_rank = _load_scores_cache()
            if cached_scores_rank:
                all_scores_for_select = cached_scores_rank
            else:
                with st.spinner("Loading rankings..."):
                    all_scores_for_select = score_all_top_companies(year=2024, limit=50)

        # Toggle for network metrics
        show_net_metrics = st.checkbox("Show network metrics (PageRank, Betweenness)", value=False)
        sample_G_rank, sample_metrics_rank, _ = load_sample_network() if show_net_metrics else (None, {}, [])

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

                # Network metrics row (optional)
                net_metrics_html = ""
                if show_net_metrics and sample_metrics_rank:
                    # Find matching node
                    name_upper = s["name"].upper()
                    matched_node = None
                    for node in sample_metrics_rank:
                        if name_upper in node.upper() or node.upper() in name_upper:
                            matched_node = node
                            break
                    if matched_node:
                        m = sample_metrics_rank[matched_node]
                        net_metrics_html = (
                            f"<div style='display:flex; gap:20px; font-size:11px; color:#2E7BE6; margin-top:6px; padding-top:6px; border-top:1px solid #f1f5f9;'>"
                            f"<span>PageRank: {m['pagerank']:.4f}</span>"
                            f"<span>Betweenness: {m['betweenness_centrality']:.4f}</span>"
                            f"<span>Hub: {m['hub_score']:.4f}</span>"
                            f"<span>Authority: {m['authority_score']:.4f}</span>"
                            f"<span>In: {m['in_degree']} / Out: {m['out_degree']}</span>"
                            f"</div>"
                        )

                # 3-Year Risk for ranking card
                _r_bands = [(300, 43.8), (400, 31.1), (500, 22.4), (600, 17.6), (1001, 9.3)]
                _r_pct = 9.3
                for _rt, _rp in _r_bands:
                    if total < _rt:
                        _r_pct = _rp
                        break
                _r_col = "#ef4444" if _r_pct >= 30 else "#f59e0b" if _r_pct >= 20 else "#22c55e"

                st.markdown(
                    f"<div class='card' style='margin-bottom:12px; padding:18px 24px;'>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>"
                    f"<div>"
                    f"<span style='font-size:20px; font-weight:900; color:#94a3b8; margin-right:12px;'>#{rank}</span>"
                    f"<span style='font-size:18px; font-weight:700; color:#1e293b;'>{s['name']}</span>"
                    f"</div>"
                    f"<div style='text-align:right;'>"
                    f"<div style='font-size:32px; font-weight:900; color:{color};'>{total}</div>"
                    f"<div style='font-size:10px; color:{_r_col}; font-weight:600;'>3Y Risk: {_r_pct:.1f}%</div>"
                    f"</div>"
                    f"</div>"
                    f"<div style='display:flex; gap:20px; font-size:12px; color:#64748b; margin-bottom:10px;'>"
                    f"<span>Value: {_fmt_dollar(s.get('total_value', 0))}</span>"
                    f"<span>Agencies: {s.get('agency_count', 0)}</span>"
                    f"<span>Contracts: {('100+' if s.get('contract_count', 0) >= 100 else s.get('contract_count', 0))}</span>"
                    f"<span>YoY: {s.get('yoy_change', 0):+.0%}</span>"
                    f"</div>"
                    f"{axis_bars}"
                    f"{net_metrics_html}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # Methodology
            with st.expander("Methodology"):
                st.markdown("""
**SUPPLY-1000 Scoring Methodology**

Each company is scored on 5 axes (0-200 each, total 0-1000).

| Axis | Weight | Description |
|------|--------|-------------|
| Contract Volume | 0-200 | Total contract value and count, with YoY growth bonus (-20 to +40) |
| Diversification | 0-200 | Agency diversity and client concentration penalty |
| Contract Continuity | 0-200 | Years active with consecutive-year bonuses |
| Network Position | 0-200 | Prime/sub status and hub importance |
| Digital Resilience | 0-200 | SSL certificate health + email security (SPF/DMARC). Powered by CYBER-1000 engine. |

**Data sources:** USAspending.gov (contract data) + direct SSL/DNS scanning (Digital Resilience). Updated daily by the US Treasury. Digital Resilience is scanned live when viewing Company Detail.
""")
        else:
            st.warning("No scoring data available. Please try again later.")

    # ===================================================================
    # BATCH SCORE TAB
    # ===================================================================
    with tab_batch:
        st.markdown(
            "<div style='font-size:1.5em; font-weight:900; color:#1e3a8a; margin-bottom:5px;'>"
            "Batch Score</div>"
            "<p style='color:#64748b; margin-bottom:20px;'>"
            "Paste a list of company names to score them all at once. "
            "Export as CSV for CRM import (Salesforce, HubSpot, Excel).</p>",
            unsafe_allow_html=True,
        )

        # Backtest report download
        backtest_pdf_path = os.path.join(
            os.path.dirname(__file__),
            "backtest_results",
            "SUPPLY-1000_Backtest_Report.pdf",
        )
        if os.path.exists(backtest_pdf_path):
            with open(backtest_pdf_path, "rb") as _f:
                _pdf_bytes = _f.read()
            st.markdown(
                "<div style='background:#eff6ff; border-left:4px solid #2E7BE6; "
                "padding:14px 18px; border-radius:6px; margin-bottom:18px;'>"
                "<div style='font-size:14px; font-weight:700; color:#1e293b; margin-bottom:4px;'>"
                "Backtest Report Available</div>"
                "<div style='font-size:12px; color:#64748b;'>"
                "We backtested 1,000 government contractors across FY2015 and FY2018. "
                "Low-scoring companies (below 400) had a 27 to 35 percent chance of losing "
                "contracts within 3 years. Download the full report below.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.download_button(
                label="Download Backtest Report (PDF)",
                data=_pdf_bytes,
                file_name="SUPPLY-1000_Backtest_Report.pdf",
                mime="application/pdf",
                key="backtest_pdf_dl",
            )
            st.markdown("<br>", unsafe_allow_html=True)

        batch_input = st.text_area(
            "Enter company names (one per line)",
            height=200,
            placeholder="BOOZ ALLEN HAMILTON INC\nLOCKHEED MARTIN CORPORATION\nGENERAL DYNAMICS INFORMATION TECHNOLOGY, INC.",
        )

        if st.button("Score All Companies", key="batch_score_btn"):
            names = [n.strip() for n in batch_input.strip().split("\n") if n.strip()]
            if not names:
                st.warning("Please enter at least one company name.")
            elif len(names) > 20:
                st.warning("Maximum 20 companies per batch. Please reduce your list.")
            else:
                progress = st.progress(0, text="Starting batch scoring...")
                all_profiles = []
                failed = []

                for i, name in enumerate(names):
                    progress.progress(
                        (i) / len(names),
                        text=f"Fetching data for {name} ({i+1}/{len(names)})...",
                    )
                    try:
                        profile = get_company_profile(name)
                        if profile and (profile["total_prime_value"] + profile["total_sub_value"]) > 0:
                            all_profiles.append(profile)
                        else:
                            failed.append(name)
                    except Exception:
                        failed.append(name)

                if all_profiles:
                    progress.progress(0.9, text="Scoring companies...")
                    scored_results = []
                    for profile in all_profiles:
                        scored = score_company(profile, all_profiles)
                        domain = scored.get("domain")
                        if domain:
                            vital = run_vital_pulse(domain)
                            scored = apply_vital_pulse_modifier(scored, vital)
                        env = calculate_environment_adjustment(
                            scored.get("state_code"),
                            scored.get("naics_code"),
                            scored.get("prime_contractors", [None])[0] if scored.get("prime_contractors") else None,
                        )
                        scored = apply_environment_adjustment(scored, env)
                        scored_results.append(scored)

                    scored_results.sort(key=lambda x: x["total"], reverse=True)
                    progress.progress(1.0, text="Done!")

                    # Build CSV data
                    csv_rows = []
                    for s in scored_results:
                        csv_rows.append({
                            "Account Name": s["name"],
                            "SUPPLY_1000_Score__c": int(s["total"]),
                            "Contract_Volume__c": int(s["axes"].get("Contract Volume", 0)),
                            "Diversification__c": int(s["axes"].get("Diversification", 0)),
                            "Contract_Continuity__c": int(s["axes"].get("Contract Continuity", 0)),
                            "Network_Position__c": int(s["axes"].get("Network Position", 0)),
                            "Digital_Resilience__c": int(s["axes"].get("Digital Resilience", 0)),
                            "Total_Contract_Value__c": round(s.get("total_value", 0), 2),
                            "Agency_Count__c": s.get("agency_count", 0),
                            "Sub_Contractor_Count__c": s.get("sub_contractor_count", 0),
                            "Years_Active__c": s.get("years_active", 0),
                            "YoY_Change__c": round(s.get("yoy_change", 0), 1),
                            "State__c": s.get("state_code", ""),
                            "Domain__c": s.get("domain", ""),
                        })

                    df = pd.DataFrame(csv_rows)

                    # Display results table
                    st.markdown("<div class='section-title'>RESULTS</div>", unsafe_allow_html=True)
                    display_df = df[["Account Name", "SUPPLY_1000_Score__c", "Contract_Volume__c",
                                     "Diversification__c", "Contract_Continuity__c",
                                     "Network_Position__c", "Digital_Resilience__c",
                                     "Total_Contract_Value__c"]].copy()
                    display_df.columns = ["Company", "Total", "Volume", "Diversif.", "Continuity",
                                          "Network", "Digital", "Contract Value"]
                    st.dataframe(display_df, use_container_width=True, hide_index=True)

                    # CSV download
                    csv_bytes = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="Download CSV (Salesforce-ready)",
                        data=csv_bytes,
                        file_name="SUPPLY1000_Batch_Scores.csv",
                        mime="text/csv",
                    )

                    if failed:
                        st.warning(f"Could not find data for: {', '.join(failed)}")
                else:
                    progress.progress(1.0, text="Done.")
                    st.error("No companies found in USAspending.gov. Check the company names and try again.")

        # Salesforce Import Guide download
        st.markdown("<div class='section-title'>SALESFORCE IMPORT GUIDE</div>", unsafe_allow_html=True)
        st.markdown(
            "<p style='color:#64748b; margin-bottom:10px;'>"
            "Download the step-by-step guide to import your CSV into Salesforce. "
            "No IT team needed. 5 minutes.</p>",
            unsafe_allow_html=True,
        )
        from salesforce_guide import generate_salesforce_guide
        guide_pdf = generate_salesforce_guide()
        st.download_button(
            label="Download Salesforce Import Guide (PDF)",
            data=guide_pdf,
            file_name="SUPPLY_1000_Salesforce_Import_Guide.pdf",
            mime="application/pdf",
        )


if __name__ == "__main__":
    main()
