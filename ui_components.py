# ui_components.py
"""Reusable UI components for SUPPLY-1000."""
import streamlit as st
import plotly.graph_objects as go


def inject_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
        .block-container { max-width: 1600px; padding-top: 1rem; background-color: #FFFFFF; font-family: 'Inter', sans-serif; }

        .total-score-container { text-align: center; padding: 20px; margin-bottom: 20px; border-bottom: 2px solid #F0F0F0; }
        .total-score-label { font-size: 16px; color: #666; font-weight: 700; letter-spacing: 2px; }
        .total-score-val { font-size: 90px; font-weight: 900; color: #2E7BE6; line-height: 1; }

        .dna-card { background:#ffffff; border-radius:10px; padding:15px 20px; border:1px solid #EDEDED; margin-bottom:12px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 10px rgba(0,0,0,0.02); }
        .dna-label { font-size:14px; color:#444; font-weight:600; }
        .dna-value { font-size:26px; font-weight:900; color:#1A1C1E; }

        .section-title { font-size:16px; font-weight:700; color:#2E7BE6; text-transform: uppercase; letter-spacing: 1px; margin:30px 0 15px; }
        .card { background:#ffffff; border-radius:15px; padding:20px; border:1px solid #E0E0E0; box-shadow: 0 4px 20px rgba(0,0,0,0.05); }
        </style>
    """, unsafe_allow_html=True)


def render_radar_chart(data, saved_data, axes_labels):
    """5-axis radar chart with optional comparison overlay."""
    fig = go.Figure()
    v = list(data["axes"].values()) + [list(data["axes"].values())[0]]
    fig.add_trace(go.Scatterpolar(
        r=v, theta=axes_labels + [axes_labels[0]], fill='toself',
        fillcolor='rgba(46, 123, 230, 0.1)', line_color='#2E7BE6',
        line=dict(width=4), name=data['name']
    ))
    if saved_data:
        v_s = list(saved_data["axes"].values()) + [list(saved_data["axes"].values())[0]]
        fig.add_trace(go.Scatterpolar(
            r=v_s, theta=axes_labels + [axes_labels[0]], fill='toself',
            fillcolor='rgba(244, 162, 97, 0.1)', line_color='#F4A261',
            line=dict(width=3), name=saved_data['name']
        ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 200], gridcolor="#F0F0F0"),
            angularaxis=dict(rotation=90, direction="clockwise"),
            bgcolor='white'
        ),
        showlegend=True, margin=dict(l=50, r=50, t=20, b=20), height=500,
        clickmode='none', dragmode=False
    )
    return fig
