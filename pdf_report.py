# pdf_report.py
"""SMB-1000 Strategic Credit Report -- PDF generation."""
import io
import math
from datetime import datetime

from fpdf import FPDF

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NAVY = (30, 58, 138)       # #1e3a8a
DARK = (30, 41, 59)        # #1e293b
GRAY = (100, 116, 139)     # #64748b
LIGHT_GRAY = (241, 245, 249)  # #f1f5f9
WHITE = (255, 255, 255)
GREEN = (16, 185, 129)     # #10b981
BLUE = (46, 123, 230)      # #2E7BE6
ORANGE = (245, 158, 11)    # #f59e0b
RED = (239, 68, 68)        # #ef4444

AXES_LABELS = [
    "Contract Volume",
    "Diversification",
    "Contract Continuity",
    "Network Position",
    "Digital Resilience",
]


def _score_color(total: int):
    if total >= 800:
        return GREEN
    if total >= 600:
        return BLUE
    if total >= 400:
        return ORANGE
    return RED


def _rating_label(total: int) -> tuple[str, tuple]:
    if total >= 700:
        return "LOW RISK", GREEN
    if total >= 400:
        return "CAUTION", ORANGE
    return "HIGH RISK", RED


def _risk_advisory(total: int) -> str:
    if total > 700:
        return (
            "Favorable external environment and strong digital infrastructure "
            "indicate stable growth prospects. Continued monitoring recommended "
            "on a quarterly basis."
        )
    if total >= 400:
        return (
            "Deteriorating external factors (PORT/GOV) may compress cash flow. "
            "Elevated concentration risk or digital infrastructure gaps warrant "
            "close monitoring and contingency planning."
        )
    return (
        "Extreme survival risk detected. Digital infrastructure neglect "
        "combined with logistics disruption and weak state fiscal environment "
        "suggest imminent operational stress. Early asset recovery is advised."
    )


def _killshot_line(data: dict) -> str:
    """Generate a one-line risk statement targeting the weakest axis."""
    axes = data.get("axes", {})
    if not axes:
        return ""
    weakest_axis = min(axes, key=axes.get)
    env = data.get("environment", {})

    parts = []
    if weakest_axis == "Contract Volume":
        parts.append("contract revenue decline and limited deal flow")
    elif weakest_axis == "Diversification":
        parts.append("dangerous client concentration with single-agency dependency")
    elif weakest_axis == "Contract Continuity":
        parts.append("short operating history and gaps in contract continuity")
    elif weakest_axis == "Network Position":
        parts.append("weak network position with minimal sub-contractor leverage")
    elif weakest_axis == "Digital Resilience":
        parts.append("critical digital infrastructure failures (SSL/email security)")

    port_adj = env.get("port_adjustment", 0) if env else 0
    if port_adj < 0:
        parts.append("port congestion risk impacting supply chain")

    gov_adj = env.get("gov_adjustment", 0) if env else 0
    if gov_adj < 0:
        parts.append("state fiscal weakness threatening contract stability")

    return f"Primary risk drivers: {'; '.join(parts)}."


def _fmt_dollar(val: float) -> str:
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:,.0f}"


def _draw_radar_chart(pdf: "CreditReportPDF", data: dict, cx: float, cy: float, radius: float):
    """Draw a 5-axis radar chart directly on the PDF.

    cx, cy: center of the chart in mm.
    radius: max radius in mm (corresponds to score 200).
    """
    n = len(AXES_LABELS)
    vals = [data["axes"].get(a, 0) for a in AXES_LABELS]

    def _polar(index: int, r: float):
        angle = math.radians(90 - index * (360 / n))
        return cx + r * math.cos(angle), cy - r * math.sin(angle)

    # Grid rings
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.15)
    for ring_val in (50, 100, 150, 200):
        ring_r = radius * ring_val / 200
        pts = [_polar(i, ring_r) for i in range(n)]
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            pdf.line(x1, y1, x2, y2)

    # Axis spokes
    pdf.set_draw_color(203, 213, 225)
    pdf.set_line_width(0.2)
    for i in range(n):
        x, y = _polar(i, radius)
        pdf.line(cx, cy, x, y)

    # Data polygon
    data_pts = [_polar(i, radius * vals[i] / 200) for i in range(n)]
    pdf.set_fill_color(46, 123, 230)
    pdf.set_draw_color(46, 123, 230)
    pdf.set_line_width(0.5)
    pdf.polygon(data_pts, style="DF")

    # Data point dots
    for px, py in data_pts:
        pdf.set_fill_color(46, 123, 230)
        pdf.ellipse(px - 1, py - 1, 2, 2, "F")

    # Axis labels -- positioned by index
    pdf.set_font("Helvetica", "B", 6.5)
    pdf.set_text_color(*DARK)
    for i, label in enumerate(AXES_LABELS):
        lx, ly = _polar(i, radius + 5)
        w = pdf.get_string_width(label)
        if i == 0:        # top center (Contract Volume)
            pdf.text(lx - w / 2, ly - 2, label)
        elif i == 1:      # upper-right (Diversification)
            pdf.text(lx + 1, ly + 1, label)
        elif i == 2:      # lower-right (Contract Continuity)
            pdf.text(lx + 1, ly + 3, label)
        elif i == 3:      # lower-left (Network Position)
            pdf.text(lx - w - 1, ly + 3, label)
        elif i == 4:      # upper-left (Digital Resilience)
            pdf.text(max(pdf.l_margin, lx - w - 1), ly + 1, label)

    # Ring value labels along top spoke
    pdf.set_font("Helvetica", "", 5.5)
    pdf.set_text_color(*GRAY)
    for ring_val in (100, 200):
        ring_r = radius * ring_val / 200
        pdf.text(cx + 1.5, cy - ring_r + 2.5, str(ring_val))


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

class CreditReportPDF(FPDF):
    """Custom PDF layout for the SMB-1000 Strategic Credit Report."""

    def header(self):
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 210, 3.5, "F")

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 6.5)
        self.set_text_color(*GRAY)
        self.cell(0, 3.5, f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  |  SMB-1000 Strategic Credit Report", align="C")
        self.ln(3.5)
        self.cell(0, 3.5, "Source: USAspending API / Port Authority Data / VP-1000 / CYBER-1000 / GOV-1000 / REALESTATE-1000", align="C")

    def _section_title(self, title: str):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*NAVY)
        self.line(self.l_margin, self.get_y(), 200, self.get_y())
        self.ln(2)

    def _kv_row(self, label: str, value: str, bold_value: bool = False):
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GRAY)
        self.cell(45, 4.5, label, new_x="END")
        self.set_text_color(*DARK)
        self.set_font("Helvetica", "B" if bold_value else "", 8)
        self.cell(0, 4.5, value, new_x="LMARGIN", new_y="NEXT")


def generate_pdf(data: dict) -> bytes:
    """Generate the full SMB-1000 Strategic Credit Report as PDF bytes."""
    total = int(data.get("total", 0))
    name = data.get("name", "Unknown")
    rating_text, rating_color = _rating_label(total)
    score_color = _score_color(total)

    pdf = CreditReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # ---- Title block ----
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, "SMB-1000 Strategic Credit Report", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 4, "Supply Chain Health Assessment  |  Confidential",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ---- Company name + score banner ----
    y_banner = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.rect(10, y_banner, 190, 22, "F")

    pdf.set_xy(14, y_banner + 3)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*DARK)
    pdf.cell(110, 7, name)

    # State + Domain on same line
    state = data.get("state_code", "")
    domain = data.get("domain", "")
    info_parts = []
    if state:
        info_parts.append(f"State: {state}")
    if domain:
        info_parts.append(f"Domain: {domain}")
    if info_parts:
        pdf.set_xy(14, y_banner + 12)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.cell(110, 4, "  |  ".join(info_parts))

    # Score (right)
    pdf.set_xy(140, y_banner + 1)
    pdf.set_font("Helvetica", "B", 32)
    pdf.set_text_color(*score_color)
    pdf.cell(55, 12, str(total), align="R")
    pdf.set_xy(140, y_banner + 14)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*rating_color)
    pdf.cell(55, 5, rating_text, align="R")

    pdf.set_y(y_banner + 26)

    # ---- Risk Advisory ----
    pdf._section_title("RISK ADVISORY")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*DARK)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(190, 4, _risk_advisory(total))
    killshot = _killshot_line(data)
    if killshot:
        pdf.set_font("Helvetica", "BI", 8)
        pdf.set_text_color(*RED if total < 400 else (ORANGE if total < 700 else DARK))
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(190, 4, killshot)
    pdf.ln(2)

    # ---- Radar chart + Axis scores (side by side) ----
    y_chart_start = pdf.get_y()
    chart_radius = 26
    chart_cx = 52
    chart_cy = y_chart_start + 34

    with pdf.local_context(fill_opacity=0.15):
        _draw_radar_chart(pdf, data, chart_cx, chart_cy, chart_radius)

    # Axis scores (right side)
    pdf.set_xy(105, y_chart_start)
    pdf._section_title("5-AXIS BREAKDOWN")
    for axis in AXES_LABELS:
        val = int(data["axes"].get(axis, 0))
        pct = val / 200
        pdf.set_x(105)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*GRAY)
        pdf.cell(38, 4, axis, new_x="END")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*DARK)
        pdf.cell(15, 4, f"{val}/200", new_x="LMARGIN", new_y="NEXT")

        bar_x = 105
        bar_y = pdf.get_y()
        bar_w = 90
        bar_h = 2.5
        pdf.set_fill_color(*LIGHT_GRAY)
        pdf.rect(bar_x, bar_y, bar_w, bar_h, "F")
        pdf.set_fill_color(*_score_color(val * 5))
        pdf.rect(bar_x, bar_y, bar_w * pct, bar_h, "F")
        pdf.set_y(bar_y + 5)

    # Move below chart area
    pdf.set_y(max(pdf.get_y(), y_chart_start + 66) + 2)

    # ---- Two-column: Layer 1 (left) + Key Metrics (right) ----
    y_cols = pdf.get_y()
    col_left_x = 10
    col_right_x = 112

    # -- LEFT: Layer 1 --
    pdf.set_xy(col_left_x, y_cols)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*NAVY)
    pdf.cell(95, 6, "LAYER 1: ENVIRONMENT RISK FACTORS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*NAVY)
    pdf.line(col_left_x, pdf.get_y(), 102, pdf.get_y())
    pdf.ln(2)

    env = data.get("environment", {})
    if env and env.get("details"):
        for system, desc in env["details"].items():
            adj_val = 0
            if system == "GOV-1000":
                adj_val = env.get("gov_adjustment", 0)
            elif system == "REALESTATE-1000":
                adj_val = env.get("realestate_adjustment", 0)
            elif system == "PORT-1000":
                adj_val = env.get("port_adjustment", 0)
            elif system == "FRS-1000":
                adj_val = env.get("frs_adjustment", 0)

            color = GREEN if adj_val > 0 else (RED if adj_val < 0 else GRAY)
            pdf.set_x(col_left_x + 2)
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_text_color(*NAVY)
            pdf.cell(28, 4, system, new_x="END")
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_text_color(*color)
            sign = "+" if adj_val >= 0 else ""
            pdf.cell(10, 4, f"{sign}{adj_val}", new_x="END")
            pdf.set_text_color(*DARK)
            pdf.set_font("Helvetica", "", 7.5)
            pdf.cell(55, 4, desc, new_x="LMARGIN", new_y="NEXT")

        total_adj = env.get("total_adjustment", 0)
        pdf.set_x(col_left_x + 2)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*NAVY)
        sign = "+" if total_adj >= 0 else ""
        pdf.cell(95, 5, f"Net Adjustment: {sign}{total_adj} pts",
                 new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.cell(95, 4, "No environment data.", new_x="LMARGIN", new_y="NEXT")

    y_after_left = pdf.get_y()

    # -- RIGHT: Key Metrics --
    pdf.set_xy(col_right_x, y_cols)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*NAVY)
    pdf.cell(88, 6, "KEY METRICS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*NAVY)
    pdf.line(col_right_x, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    metrics = [
        ("Contract Value", _fmt_dollar(data.get("total_value", 0)), True),
        ("  Prime Awards", _fmt_dollar(data.get("total_prime_value", 0)), False),
        ("  Sub-Awards", _fmt_dollar(data.get("total_sub_value", 0)), False),
        ("Contracts", str(data.get("contract_count", 0)), False),
        ("Agencies", str(data.get("agency_count", 0)), False),
        ("Sub-Contractors", str(data.get("sub_contractor_count", 0)), False),
        ("Years Active", str(data.get("years_active", 0)), False),
        ("YoY Growth", f"{data.get('yoy_change', 0):+.1%}", False),
    ]
    for label, value, bold in metrics:
        pdf.set_x(col_right_x + 2)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*GRAY)
        pdf.cell(30, 4, label, new_x="END")
        pdf.set_text_color(*DARK)
        pdf.set_font("Helvetica", "B" if bold else "", 7.5)
        pdf.cell(50, 4, value, new_x="LMARGIN", new_y="NEXT")

    y_after_right = pdf.get_y()
    pdf.set_y(max(y_after_left, y_after_right) + 3)

    # ---- VP-1000 / CYBER-1000 ----
    pdf._section_title("LAYER 2: DIGITAL HEALTH (VP-1000 / CYBER-1000)")

    vital = data.get("vital_pulse")
    cyber_detail = data.get("digital_score_detail")

    if vital or cyber_detail:
        # Two-column: VP-1000 left, CYBER-1000 right
        y_vp = pdf.get_y()

        if vital:
            vs = vital.get("vital_score", 0)
            vs_label = "HEALTHY" if vs >= 80 else ("STABLE" if vs >= 50 else ("WARNING" if vs >= 30 else "CRITICAL"))
            vs_color = GREEN if vs >= 80 else (BLUE if vs >= 50 else (ORANGE if vs >= 30 else RED))

            pdf.set_x(col_left_x + 2)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*NAVY)
            pdf.cell(20, 4, "VP-1000", new_x="END")
            pdf.set_text_color(*vs_color)
            modifier = data.get("vital_modifier", 1.0)
            pdf.cell(75, 4, f"{vs}/100 ({vs_label})  |  Modifier: x{modifier:.1f}",
                     new_x="LMARGIN", new_y="NEXT")

            signals = vital.get("signals", [])
            for signal_name, signal_type in signals:
                marker_color = GREEN if signal_type == "positive" else (RED if signal_type == "negative" else GRAY)
                marker = "+" if signal_type == "positive" else ("-" if signal_type == "negative" else " ")
                pdf.set_x(col_left_x + 4)
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*marker_color)
                pdf.cell(4, 3.5, marker, new_x="END")
                pdf.set_text_color(*DARK)
                pdf.cell(85, 3.5, signal_name, new_x="LMARGIN", new_y="NEXT")

        y_after_vp = pdf.get_y()

        if cyber_detail:
            pdf.set_xy(col_right_x + 2, y_vp)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*NAVY)
            pdf.cell(20, 4, "CYBER-1000", new_x="LMARGIN", new_y="NEXT")

            pdf.set_x(col_right_x + 4)
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*GRAY)
            pdf.cell(22, 4, "SSL Health:", new_x="END")
            pdf.set_text_color(*DARK)
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.cell(30, 4, f"{cyber_detail.get('ssl', 'N/A')}/200", new_x="LMARGIN", new_y="NEXT")

            pdf.set_x(col_right_x + 4)
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*GRAY)
            pdf.cell(22, 4, "Email Sec:", new_x="END")
            pdf.set_text_color(*DARK)
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.cell(30, 4, f"{cyber_detail.get('email', 'N/A')}/200", new_x="LMARGIN", new_y="NEXT")
            y_after_vp = max(y_after_vp, pdf.get_y())

        pdf.set_y(y_after_vp)
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 4, "Digital health scan not performed.", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)

    # ---- Disclaimer ----
    pdf.set_font("Helvetica", "I", 6.5)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(0, 3,
        "Disclaimer: This report is generated by the SMB-1000 engine for informational "
        "purposes only and does not constitute financial advice. Scores are derived from "
        "publicly available data (USAspending.gov, DNS/SSL records, state fiscal data) and "
        "proprietary algorithms. Independent verification is recommended before making "
        "credit or investment decisions.")

    # Output
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
