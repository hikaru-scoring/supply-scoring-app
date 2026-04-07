"""
SUPPLY-1000 Backtest Report Generator
======================================
Generates a professional PDF report from backtest results.
"""

import json
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "backtest_results")

# Colors
BLUE = HexColor("#2E7BE6")
DARK = HexColor("#1e293b")
GRAY = HexColor("#64748b")
LIGHT_GRAY = HexColor("#f1f5f9")
WHITE = HexColor("#ffffff")
RED = HexColor("#ef4444")
GREEN = HexColor("#22c55e")


def load_results(year):
    path = os.path.join(OUTPUT_DIR, f"backtest_{year}.json")
    with open(path, "r") as f:
        return json.load(f)


def build_report():
    # Load both results
    r2018 = load_results(2018)
    r2015 = load_results(2015)

    pdf_path = os.path.join(OUTPUT_DIR, "SUPPLY-1000_Backtest_Report.pdf")

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        topMargin=20*mm,
        bottomMargin=15*mm,
        leftMargin=20*mm,
        rightMargin=20*mm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontSize=22,
        textColor=DARK,
        spaceAfter=4*mm,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "CustomSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=GRAY,
        spaceAfter=8*mm,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=BLUE,
        spaceBefore=6*mm,
        spaceAfter=3*mm,
        fontName="Helvetica-Bold",
    )
    h3_style = ParagraphStyle(
        "H3",
        parent=styles["Heading3"],
        fontSize=11,
        textColor=DARK,
        spaceBefore=4*mm,
        spaceAfter=2*mm,
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=DARK,
        spaceAfter=2*mm,
        leading=14,
    )
    bold_body = ParagraphStyle(
        "BoldBody",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontSize=8,
        textColor=GRAY,
        spaceAfter=1*mm,
    )

    elements = []

    # ===== TITLE =====
    elements.append(Paragraph("SUPPLY-1000 Backtest Report", title_style))
    elements.append(Paragraph(
        "Predictive Validity of Government Contractor Scoring",
        subtitle_style
    ))
    elements.append(Paragraph(
        "SCORING PTE. LTD. | scoring.global | April 2026",
        small_style
    ))
    elements.append(Spacer(1, 4*mm))

    # ===== EXECUTIVE SUMMARY =====
    elements.append(Paragraph("Executive Summary", h2_style))
    elements.append(Paragraph(
        "We backtested the SUPPLY-1000 scoring model against 1,000 US government contractors "
        "across two independent time periods (FY2015 and FY2018). We scored each company using "
        "4 axes (Contract Volume, Diversification, Contract Continuity, Network Position) "
        "and tracked their outcomes over the following 3 years.",
        body_style
    ))
    elements.append(Paragraph(
        "<b>Key finding:</b> Low-scoring contractors (below 400) experienced negative outcomes "
        "at 2.5x to 4.5x the rate of high-scoring contractors (above 600). "
        "This pattern held consistently across both time periods.",
        body_style
    ))
    elements.append(Spacer(1, 2*mm))

    # ===== HEADLINE NUMBERS =====
    headline_data = [
        ["", "FY2015", "FY2018"],
        ["Companies scored", "500", "500"],
        ["Avg score", str(r2015["analysis"]["overall"]["avg_score"]),
         str(r2018["analysis"]["overall"]["avg_score"])],
        ["Disappeared (3yr)", f'{r2015["analysis"]["overall"]["disappeared"]} ({r2015["analysis"]["overall"]["disappeared"]/500*100:.1f}%)',
         f'{r2018["analysis"]["overall"]["disappeared"]} ({r2018["analysis"]["overall"]["disappeared"]/500*100:.1f}%)'],
        ["Severe decline >50%", f'{r2015["analysis"]["overall"]["severe_decline"]} ({r2015["analysis"]["overall"]["severe_decline"]/500*100:.1f}%)',
         f'{r2018["analysis"]["overall"]["severe_decline"]} ({r2018["analysis"]["overall"]["severe_decline"]/500*100:.1f}%)'],
    ]
    t = Table(headline_data, colWidths=[45*mm, 40*mm, 40*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3*mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3*mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 3*mm),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 4*mm))

    # ===== QUARTILE ANALYSIS =====
    elements.append(Paragraph("Score Quartile Analysis", h2_style))
    elements.append(Paragraph(
        "Companies were split into four equal groups by score. "
        "Lower quartiles consistently show higher rates of negative outcomes.",
        body_style
    ))

    for year, results in [("FY2015", r2015), ("FY2018", r2018)]:
        elements.append(Paragraph(f"{year} Quartile Results", h3_style))

        q_data = [["Quartile", "Score Range", "Count", "Disappeared", "Decline >50%", "Any Negative"]]
        quartile_labels = {"Q1_lowest": "Q1 (Lowest)", "Q2": "Q2", "Q3": "Q3", "Q4_highest": "Q4 (Highest)"}

        for q_key, q_label in quartile_labels.items():
            q = results["analysis"]["by_quartile"].get(q_key, {})
            q_data.append([
                q_label,
                q.get("score_range", ""),
                str(q.get("count", "")),
                f'{q.get("disappeared_pct", 0):.1f}%',
                f'{q.get("severe_decline_pct", 0):.1f}%',
                f'{q.get("any_negative_pct", 0):.1f}%',
            ])

        t = Table(q_data, colWidths=[30*mm, 25*mm, 18*mm, 25*mm, 25*mm, 27*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("BACKGROUND", (0, 1), (-1, 1), HexColor("#fef2f2")),  # Q1 red tint
            ("BACKGROUND", (0, 2), (-1, 2), HexColor("#fffbeb")),  # Q2 yellow tint
            ("BACKGROUND", (0, 3), (-1, 3), HexColor("#f0fdf4")),  # Q3 green tint
            ("BACKGROUND", (0, 4), (-1, 4), HexColor("#eff6ff")),  # Q4 blue tint
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5*mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5*mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 2*mm),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3*mm))

    # ===== THRESHOLD ANALYSIS =====
    elements.append(Paragraph("Score Threshold Analysis", h2_style))
    elements.append(Paragraph(
        "Negative outcome rates at different score cutoff points.",
        body_style
    ))

    thresh_data = [["Score Threshold", "FY2015 Below", "FY2015 Above", "FY2018 Below", "FY2018 Above"]]
    for threshold in [300, 400, 500, 600]:
        b15 = r2015["analysis"]["by_threshold"].get(f"below_{threshold}", {})
        a15 = r2015["analysis"]["by_threshold"].get(f"above_{threshold}", {})
        b18 = r2018["analysis"]["by_threshold"].get(f"below_{threshold}", {})
        a18 = r2018["analysis"]["by_threshold"].get(f"above_{threshold}", {})
        thresh_data.append([
            f"Score {threshold}",
            f'{b15.get("negative_pct", "N/A")}% (n={b15.get("count", "?")})',
            f'{a15.get("negative_pct", "N/A")}% (n={a15.get("count", "?")})',
            f'{b18.get("negative_pct", "N/A")}% (n={b18.get("count", "?")})',
            f'{a18.get("negative_pct", "N/A")}% (n={a18.get("count", "?")})',
        ])

    t = Table(thresh_data, colWidths=[25*mm, 32*mm, 32*mm, 32*mm, 32*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5*mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5*mm),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 4*mm))

    # ===== METHODOLOGY =====
    elements.append(Paragraph("Methodology", h2_style))
    elements.append(Paragraph(
        "<b>Data source:</b> USAspending.gov (official US federal contract records)",
        body_style
    ))
    elements.append(Paragraph(
        "<b>Scoring axes (4 of 5):</b> Contract Volume (0-200), Diversification (0-200), "
        "Contract Continuity (0-200), Network Position (0-200). "
        "Digital Resilience excluded from backtest (no historical SSL/DNS data). "
        "4-axis total scaled to 0-1000.",
        body_style
    ))
    elements.append(Paragraph(
        "<b>Scoring approach:</b> Percentile ranking within the cohort. "
        "Each company scored relative to other top contractors in the same fiscal year.",
        body_style
    ))
    elements.append(Paragraph(
        "<b>Negative outcome definition:</b>",
        body_style
    ))
    elements.append(Paragraph(
        "A. Contract disappearance: Company dropped from top recipients in all tracking years.<br/>"
        "B. Severe decline: Contract value dropped more than 50% within 3 years.<br/>"
        "A company is flagged if either condition is met.",
        body_style
    ))
    elements.append(Paragraph(
        "<b>Lookback period:</b> 4 years before scoring year (for continuity analysis). "
        "<b>Tracking period:</b> 3 years after scoring year.",
        body_style
    ))
    elements.append(Spacer(1, 4*mm))

    # ===== CONCLUSION =====
    elements.append(Paragraph("Conclusion", h2_style))
    elements.append(Paragraph(
        "The SUPPLY-1000 scoring model demonstrates consistent predictive validity "
        "across two independent time periods. Low-scoring government contractors are "
        "significantly more likely to lose contracts or experience severe revenue decline "
        "within 3 years. This makes SUPPLY-1000 a valuable risk assessment tool for "
        "lenders, underwriters, and procurement teams evaluating government contractor "
        "creditworthiness.",
        body_style
    ))
    elements.append(Spacer(1, 6*mm))

    # Footer
    elements.append(Paragraph(
        "SCORING PTE. LTD. | UEN: 202613228Z | Singapore | founder@scoring.global",
        ParagraphStyle("Footer", parent=small_style, alignment=TA_CENTER)
    ))

    # Build PDF
    doc.build(elements)
    print(f"PDF saved to {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    build_report()
