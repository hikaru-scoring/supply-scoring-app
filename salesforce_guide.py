# salesforce_guide.py
"""Generate Salesforce Import Guide PDF."""

import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

NAVY = colors.HexColor("#1e3a8a")
GRAY = colors.HexColor("#64748b")
LIGHT_GRAY = colors.HexColor("#f1f5f9")
WHITE = colors.white
DARK_TEXT = colors.HexColor("#1e293b")
BORDER_GRAY = colors.HexColor("#e2e8f0")
BLUE = colors.HexColor("#2E7BE6")


def generate_salesforce_guide() -> bytes:
    """Generate a 3-page Salesforce Import Guide PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "GuideTitle", parent=styles["Title"],
        fontSize=22, textColor=NAVY, spaceAfter=4 * mm,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "GuideSubtitle", parent=styles["Normal"],
        fontSize=11, textColor=GRAY, spaceAfter=8 * mm,
    )
    heading_style = ParagraphStyle(
        "GuideHeading", parent=styles["Heading2"],
        fontSize=14, textColor=NAVY, spaceBefore=6 * mm, spaceAfter=3 * mm,
        fontName="Helvetica-Bold",
    )
    step_style = ParagraphStyle(
        "GuideStep", parent=styles["Heading3"],
        fontSize=12, textColor=BLUE, spaceBefore=4 * mm, spaceAfter=2 * mm,
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "GuideBody", parent=styles["Normal"],
        fontSize=10, textColor=DARK_TEXT, spaceAfter=3 * mm,
        leading=14,
    )
    note_style = ParagraphStyle(
        "GuideNote", parent=styles["Normal"],
        fontSize=9, textColor=GRAY, spaceAfter=3 * mm,
        leading=12, leftIndent=10 * mm,
    )
    footer_style = ParagraphStyle(
        "GuideFooter", parent=styles["Normal"],
        fontSize=8, textColor=GRAY, spaceBefore=6 * mm,
    )

    elements = []

    # --- Header ---
    elements.append(Paragraph("SCORING PTE. LTD.", subtitle_style))
    elements.append(Paragraph("SUPPLY-1000", title_style))
    elements.append(Paragraph("Salesforce Import Guide", ParagraphStyle(
        "GuideSub2", parent=styles["Normal"],
        fontSize=16, textColor=NAVY, spaceAfter=4 * mm,
    )))
    elements.append(Paragraph(
        "How to import SUPPLY-1000 scores into your Salesforce CRM in 5 minutes.",
        subtitle_style,
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=6 * mm))

    # --- What You Need ---
    elements.append(Paragraph("What You Need", heading_style))
    elements.append(Paragraph(
        "1. The CSV file from SUPPLY-1000 (supply_1000_batch_scores.csv)<br/>"
        "2. Salesforce login with admin or import permissions<br/>"
        "3. 5 minutes",
        body_style,
    ))

    # --- Step 1 ---
    elements.append(Paragraph("Step 1: Create Custom Fields (one-time setup)", step_style))
    elements.append(Paragraph(
        "Before importing, create custom fields on the Account object to store the scores. "
        "Go to Setup > Object Manager > Account > Fields & Relationships > New.",
        body_style,
    ))

    field_data = [
        ["CSV Column", "Salesforce Field Name", "Field Type"],
        ["SUPPLY_1000_Score__c", "SUPPLY-1000 Score", "Number"],
        ["Contract_Volume__c", "Contract Volume", "Number"],
        ["Diversification__c", "Diversification", "Number"],
        ["Contract_Continuity__c", "Contract Continuity", "Number"],
        ["Network_Position__c", "Network Position", "Number"],
        ["Digital_Resilience__c", "Digital Resilience", "Number"],
        ["Total_Contract_Value__c", "Total Contract Value", "Currency"],
        ["Agency_Count__c", "Agency Count", "Number"],
        ["Sub_Contractor_Count__c", "Sub-Contractor Count", "Number"],
        ["Years_Active__c", "Years Active", "Number"],
        ["YoY_Change__c", "YoY Change %", "Percent"],
        ["State__c", "State", "Text"],
        ["Domain__c", "Domain", "URL"],
    ]

    field_table = Table(field_data, colWidths=[55 * mm, 50 * mm, 30 * mm])
    field_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    elements.append(field_table)
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(
        "Note: You only need to create these fields once. After that, every import will use the same fields.",
        note_style,
    ))

    # --- Step 2 ---
    elements.append(Paragraph("Step 2: Open Data Import Wizard", step_style))
    elements.append(Paragraph(
        "1. In Salesforce, click the gear icon (top right) > Setup<br/>"
        "2. In the Quick Find box, type \"Data Import Wizard\"<br/>"
        "3. Click Data Import Wizard<br/>"
        "4. Click Launch Wizard",
        body_style,
    ))

    # --- Step 3 ---
    elements.append(Paragraph("Step 3: Select Import Settings", step_style))
    elements.append(Paragraph(
        "1. Select \"Accounts and Contacts\"<br/>"
        "2. Choose \"Add new and update existing records\"<br/>"
        "3. Match by: Account Name<br/>"
        "4. Click Next",
        body_style,
    ))
    elements.append(Paragraph(
        "Note: \"Match by Account Name\" ensures that if the company already exists in your CRM, "
        "the scores will be added to the existing record instead of creating a duplicate.",
        note_style,
    ))

    # --- Step 4 ---
    elements.append(Paragraph("Step 4: Upload CSV and Map Fields", step_style))
    elements.append(Paragraph(
        "1. Upload the CSV file (supply_1000_batch_scores.csv)<br/>"
        "2. Salesforce will show a mapping screen<br/>"
        "3. Map each CSV column to the matching Salesforce field:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;Account Name > Account Name<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;SUPPLY_1000_Score__c > SUPPLY-1000 Score<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;Contract_Volume__c > Contract Volume<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;(repeat for all columns)<br/>"
        "4. Click Next",
        body_style,
    ))

    # --- Step 5 ---
    elements.append(Paragraph("Step 5: Start Import", step_style))
    elements.append(Paragraph(
        "1. Review the summary<br/>"
        "2. Click Start Import<br/>"
        "3. Wait for completion (usually a few seconds)<br/>"
        "4. Done. Open any Account record and you will see the SUPPLY-1000 scores.",
        body_style,
    ))

    # --- After Import ---
    elements.append(Paragraph("After Import", heading_style))
    elements.append(Paragraph(
        "Once imported, SUPPLY-1000 scores will appear on every matched Account record. "
        "Your team can use these scores in:<br/><br/>"
        "- List Views: Filter accounts by SUPPLY-1000 Score<br/>"
        "- Reports: Build reports on contractor risk across your portfolio<br/>"
        "- Dashboards: Visualize score distribution<br/>"
        "- Workflow Rules: Trigger alerts when scores drop below thresholds",
        body_style,
    ))

    # --- Need Help ---
    elements.append(Paragraph("Need Help?", heading_style))
    elements.append(Paragraph(
        "Send us your company list (just names). We will score them and return a "
        "Salesforce-ready CSV within 24 hours. Free.<br/><br/>"
        "Email: founder@scoring.global<br/>"
        "Web: https://bit.ly/supply-1000",
        body_style,
    ))

    # --- Footer ---
    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceBefore=6 * mm))
    elements.append(Paragraph(
        "SCORING PTE. LTD. | scoring.global | founder@scoring.global",
        footer_style,
    ))

    doc.build(elements)
    buf.seek(0)
    return buf.read()
