# pdf_report.py
"""Professional PDF report generator for SUPPLY-1000 Government Contractor Risk Report."""

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# Brand colors
NAVY = colors.HexColor("#1e3a8a")
GRAY = colors.HexColor("#64748b")
LIGHT_GRAY = colors.HexColor("#f1f5f9")
WHITE = colors.white
GREEN = colors.HexColor("#10b981")
AMBER = colors.HexColor("#f59e0b")
RED = colors.HexColor("#ef4444")
DARK_TEXT = colors.HexColor("#1e293b")
BORDER_GRAY = colors.HexColor("#e2e8f0")


BLUE = colors.HexColor("#2E7BE6")


def _score_color(score):
    """Return color object based on score tier (matches app.py thresholds)."""
    if score >= 800:
        return GREEN
    if score >= 600:
        return BLUE
    if score >= 400:
        return AMBER
    return RED


# 3-Year Risk bands (mirrors app.py exactly: avg of FY2015 + FY2018 backtest cohorts)
_RISK_BANDS = [
    (300, 43.8),
    (400, 31.1),
    (500, 22.4),
    (600, 17.6),
    (1001, 9.3),
]


def _risk_pct(score):
    for threshold, pct in _RISK_BANDS:
        if score < threshold:
            return pct
    return 9.3


def _risk_rating(score):
    """Return (label, color) for risk rating (matches app.py 3-Year Risk bands)."""
    pct = _risk_pct(score)
    if pct >= 30:
        return "HIGH RISK", RED
    if pct >= 20:
        return "MODERATE RISK", AMBER
    return "LOW RISK", GREEN


def _risk_advisory(score):
    """Return advisory statement based on score (uses 5-band backtest data)."""
    pct = _risk_pct(score)
    if pct >= 30:
        return (
            f"Elevated risk. Limited contract base, low diversification, or weak "
            f"continuity. Backtest data shows about {pct:.1f} percent of companies in "
            f"this score range experienced a negative outcome within 3 years."
        )
    if pct >= 20:
        return (
            f"Moderate concentration or limited continuity. Backtest data shows "
            f"about {pct:.1f} percent of companies in this score range experienced a "
            f"negative outcome within 3 years."
        )
    return (
        f"Strong contract base and stable diversification across agencies. "
        f"Backtest data shows about {pct:.1f} percent of companies in this score "
        f"range experienced a negative outcome within 3 years."
    )


def _vital_status(vital_score):
    """Return status label for VP-1000 vital score."""
    if vital_score >= 80:
        return "HEALTHY"
    if vital_score >= 50:
        return "STABLE"
    if vital_score >= 30:
        return "WARNING"
    return "CRITICAL"


def _fmt_dollar(amount):
    """Format large dollar amounts."""
    if amount is None:
        return "N/A"
    amount = float(amount)
    if amount >= 1e12:
        return f"${amount / 1e12:.1f}T"
    if amount >= 1e9:
        return f"${amount / 1e9:.1f}B"
    if amount >= 1e6:
        return f"${amount / 1e6:.0f}M"
    if amount >= 1e3:
        return f"${amount / 1e3:.0f}K"
    return f"${amount:,.0f}"


def _safe(val, default="N/A"):
    """Return value or default if None."""
    if val is None:
        return default
    return val


def _build_styles():
    """Build paragraph styles for the report."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        "BrandTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=NAVY,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=NAVY,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "CompanyName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=DARK_TEXT,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "ReportDate",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=GRAY,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "SectionHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=NAVY,
        spaceBefore=14,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=DARK_TEXT,
        leading=13,
    ))
    styles.add(ParagraphStyle(
        "SmallGray",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=GRAY,
        leading=11,
    ))
    styles.add(ParagraphStyle(
        "ScoreLarge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=48,
        leading=52,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "RiskLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        textColor=GRAY,
        leading=10,
    ))
    return styles


def generate_supply_pdf(scored_data: dict, company_name: str = "", all_scores: list = None) -> bytes:
    """Generate a professional PDF report for a scored company.

    Args:
        scored_data: The full scored data dict from score_company + adjustments.
        company_name: Optional company name override for white-labeling.
        all_scores: Optional list of all scored companies (for industry average).

    Returns:
        PDF as bytes (for st.download_button).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = _build_styles()
    elements = []

    name = company_name or scored_data.get("name", "Unknown Company")
    total = int(scored_data.get("total", 0))
    axes = scored_data.get("axes", {})
    now = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Section 1: Header
    # ------------------------------------------------------------------
    elements.append(Paragraph("SCORING PTE. LTD.", styles["BrandTitle"]))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph("SUPPLY-1000 Government Contractor Risk Report", styles["ReportTitle"]))
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(name, styles["CompanyName"]))
    elements.append(Paragraph(
        f"Report Date: {now.strftime('%B %d, %Y')}",
        styles["ReportDate"],
    ))
    elements.append(HRFlowable(
        width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=10,
    ))

    # ------------------------------------------------------------------
    # Section 2: Executive Summary
    # ------------------------------------------------------------------
    elements.append(Paragraph("EXECUTIVE SUMMARY", styles["SectionHeader"]))

    score_color = _score_color(total)
    risk_label, risk_color = _risk_rating(total)
    advisory = _risk_advisory(total)

    score_style = ParagraphStyle(
        "ScoreDisplay",
        parent=styles["ScoreLarge"],
        textColor=score_color,
    )
    elements.append(Paragraph(str(total), score_style))
    elements.append(Paragraph(
        f"<font size='9' color='#94a3b8'>/ 1000</font>",
        styles["ReportBody"],
    ))

    # Top-50 average and rank (if all_scores provided)
    if all_scores:
        avg = int(sum(s.get("total", 0) for s in all_scores) / len(all_scores))
        rank = 1
        for s in all_scores:
            if s.get("total", 0) > total:
                rank += 1
        diff = total - avg
        diff_sign = "+" if diff >= 0 else ""
        elements.append(Paragraph(
            f"<font size='9' color='#64748b'>"
            f"Top-{len(all_scores)} Average: <b>{avg}</b> / 1000 &nbsp;&nbsp; "
            f"Rank: <b>#{rank}</b> of {len(all_scores)} &nbsp;&nbsp; "
            f"vs Average: <b>{diff_sign}{diff}</b>"
            f"</font>",
            styles["ReportBody"],
        ))
    elements.append(Spacer(1, 3 * mm))

    risk_style = ParagraphStyle(
        "RiskDisplay",
        parent=styles["RiskLabel"],
        textColor=risk_color,
    )
    elements.append(Paragraph(f"Risk Rating: {risk_label}", risk_style))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        f"<b>Risk Advisory:</b> {advisory}",
        styles["ReportBody"],
    ))
    elements.append(Spacer(1, 4 * mm))

    # ------------------------------------------------------------------
    # Section 3: 5-Axis Score Breakdown
    # ------------------------------------------------------------------
    elements.append(Paragraph("5-AXIS SCORE BREAKDOWN", styles["SectionHeader"]))

    axis_descriptions = {
        "Contract Volume": "Total government contract value and count, with YoY growth bonus.",
        "Diversification": "Agency diversity and client concentration analysis.",
        "Contract Continuity": "Years of continuous government contracting activity.",
        "Network Position": "Prime vs sub-contractor status and hub importance.",
        "Digital Resilience": "SSL certificate health and email security (SPF/DMARC).",
    }

    axis_table_data = [
        [
            Paragraph("<b>Axis</b>", styles["ReportBody"]),
            Paragraph("<b>Score</b>", styles["ReportBody"]),
            Paragraph("<b>Description</b>", styles["ReportBody"]),
        ]
    ]
    for axis_name in ["Contract Volume", "Diversification", "Contract Continuity",
                      "Network Position", "Digital Resilience"]:
        val = int(axes.get(axis_name, 0))
        desc = axis_descriptions.get(axis_name, "")
        axis_table_data.append([
            Paragraph(axis_name, styles["ReportBody"]),
            Paragraph(f"<b>{val}</b> / 200", styles["ReportBody"]),
            Paragraph(desc, styles["SmallGray"]),
        ])

    axis_table = Table(axis_table_data, colWidths=[110, 70, 290])
    axis_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
    ]))
    elements.append(axis_table)
    elements.append(Spacer(1, 4 * mm))

    # Environment Adjustments section removed until we have live cross-product data.
    # GOV-1000 / REALESTATE-1000 / PORT-1000 / FRS-1000 integration is on the roadmap.

    # ------------------------------------------------------------------
    # Section 5: VP-1000 Vital Signs
    # ------------------------------------------------------------------
    elements.append(Paragraph("VP-1000 VITAL SIGNS", styles["SectionHeader"]))

    vital = scored_data.get("vital_pulse")
    if vital:
        vs = vital.get("vital_score", 0)
        status = _vital_status(vs)
        modifier = scored_data.get("vital_modifier", 1.0)

        elements.append(Paragraph(
            f"Vital Score: <b>{vs}</b> / 100 &nbsp;&nbsp; "
            f"Status: <b>{status}</b> &nbsp;&nbsp; "
            f"Modifier Applied: <b>x{modifier:.1f}</b>",
            styles["ReportBody"],
        ))
        elements.append(Spacer(1, 2 * mm))

        signals = vital.get("signals", [])
        if signals:
            signal_table_data = [
                [
                    Paragraph("<b>Signal</b>", styles["ReportBody"]),
                    Paragraph("<b>Status</b>", styles["ReportBody"]),
                ]
            ]
            for signal_name, signal_type in signals:
                if signal_type == "positive":
                    status_text = "PASS"
                elif signal_type == "negative":
                    status_text = "FAIL"
                else:
                    status_text = "NEUTRAL"
                signal_table_data.append([
                    Paragraph(signal_name, styles["ReportBody"]),
                    Paragraph(status_text, styles["ReportBody"]),
                ])
            signal_table = Table(signal_table_data, colWidths=[300, 170])
            signal_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), WHITE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 1), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
            ]))
            elements.append(signal_table)
    else:
        elements.append(Paragraph(
            "Vital pulse data not available for this company.",
            styles["SmallGray"],
        ))
    elements.append(Spacer(1, 4 * mm))

    # ------------------------------------------------------------------
    # Section 6: Key Metrics
    # ------------------------------------------------------------------
    elements.append(Paragraph("KEY METRICS", styles["SectionHeader"]))

    total_value = scored_data.get("total_value", 0)
    agency_count = scored_data.get("agency_count", 0)
    contract_count = scored_data.get("contract_count", 0)
    years_active = scored_data.get("years_active", 0)
    domain = scored_data.get("domain", "N/A")

    cc_display = "1000+" if (contract_count or 0) >= 1000 else str(_safe(contract_count, "0"))
    metrics_data = [
        ["Total Contract Value", _fmt_dollar(total_value)],
        ["Number of Agencies", str(_safe(agency_count, "0"))],
        ["Contracts (last 12 months)", cc_display],
        ["Years Active", str(_safe(years_active, "0"))],
        ["Domain Scanned", str(_safe(domain, "N/A"))],
    ]

    metrics_table_data = [
        [
            Paragraph("<b>Metric</b>", styles["ReportBody"]),
            Paragraph("<b>Value</b>", styles["ReportBody"]),
        ]
    ]
    for metric_name, metric_val in metrics_data:
        metrics_table_data.append([
            Paragraph(metric_name, styles["ReportBody"]),
            Paragraph(f"<b>{metric_val}</b>", styles["ReportBody"]),
        ])

    metrics_table = Table(metrics_table_data, colWidths=[250, 220])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 6 * mm))

    # ------------------------------------------------------------------
    # Section 7: Data Sources Footer
    # ------------------------------------------------------------------
    elements.append(HRFlowable(
        width="100%", thickness=1, color=BORDER_GRAY, spaceBefore=6, spaceAfter=6,
    ))
    elements.append(Paragraph("DATA INTEGRITY FOOTPRINT", styles["SectionHeader"]))
    elements.append(Paragraph(
        "Sources: USAspending.gov API (federal contract records), "
        "CYBER-1000 SSL/DNS Engine, VP-1000 Vital Pulse",
        styles["SmallGray"],
    ))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "Generated by SCORING PTE. LTD. (UEN: 202613228Z)",
        styles["SmallGray"],
    ))
    elements.append(Paragraph(
        f"Report generated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        styles["Footer"],
    ))

    # Build PDF
    doc.build(elements)
    buf.seek(0)
    return buf.read()
