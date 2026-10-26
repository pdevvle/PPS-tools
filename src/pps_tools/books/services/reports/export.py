"""Report exports: CSV and PDF."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from pps_tools.books.services.reports.engine import Report


def _plain(value, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return f"{int(value) / 100:.2f}"
    if kind in ("qty", "rate", "pct"):
        return format(value, "f") if hasattr(value, "as_tuple") else str(value)
    if kind == "date":
        return value.strftime("%m/%d/%Y") if hasattr(value, "strftime") else str(value)
    return str(value)


def to_csv(report: Report) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([report.company])
    w.writerow([report.title])
    if report.subtitle:
        w.writerow([report.subtitle])
    if report.basis:
        w.writerow([f"{report.basis.title()} basis"])
    w.writerow([])
    w.writerow([c.label for c in report.columns])
    first = report.columns[0].key if report.columns else None
    for row in report.rows:
        if row.kind == "blank":
            w.writerow([])
            continue
        cells = []
        for c in report.columns:
            text = _plain(row.cells.get(c.key), c.kind)
            if c.key == first and row.level and text:
                text = "  " * row.level + text
            cells.append(text)
        w.writerow(cells)
    for note in report.notes:
        w.writerow([])
        w.writerow([note])
    return buf.getvalue()


def to_pdf(report: Report) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from pps_tools.books.web.filters import report_cell

    wide = len(report.columns) > 6
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter) if wide else letter, leftMargin=0.5 * inch,
                            rightMargin=0.5 * inch, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title=report.title, author=report.company)
    center = ParagraphStyle("c", fontName="Helvetica", fontSize=9, alignment=1, textColor=colors.HexColor("#555555"))
    head = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=14, alignment=1, spaceAfter=2)
    comp = ParagraphStyle("co", fontName="Helvetica-Bold", fontSize=10, alignment=1)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10)
    story = [Paragraph(_esc(report.company), comp), Paragraph(_esc(report.title), head)]
    if report.subtitle:
        story.append(Paragraph(_esc(report.subtitle), center))
    if report.basis:
        story.append(Paragraph(f"{report.basis.title()} basis", center))
    story.append(Spacer(1, 10))
    data = [[Paragraph(f"<b>{_esc(c.label)}</b>", cell) if c.align == "left" else c.label for c in report.columns]]
    styles = [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
              ("FONT", (0, 1), (-1, -1), "Helvetica", 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
    for i, c in enumerate(report.columns):
        if c.align == "right":
            styles.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
    first = report.columns[0].key if report.columns else None
    for r_i, row in enumerate(report.rows, start=1):
        cells = []
        for c in report.columns:
            text = report_cell(row.cells.get(c.key), c.kind)
            if c.align == "left":
                indent = "&nbsp;" * (3 * row.level) if c.key == first else ""
                bold = row.kind in ("section", "subtotal", "total", "grand")
                cells.append(Paragraph(f"{indent}{'<b>' if bold else ''}{_esc(text)}{'</b>' if bold else ''}", cell))
            else:
                cells.append(text)
        data.append(cells)
        if row.kind in ("subtotal", "total"):
            styles += [("LINEABOVE", (1, r_i), (-1, r_i), 0.5, colors.black), ("FONT", (0, r_i), (-1, r_i), "Helvetica-Bold", 8)]
        elif row.kind == "grand":
            styles += [("LINEABOVE", (1, r_i), (-1, r_i), 0.8, colors.black),
                       ("LINEBELOW", (1, r_i), (-1, r_i), 1.2, colors.black), ("FONT", (0, r_i), (-1, r_i), "Helvetica-Bold", 8)]
        elif row.kind == "section":
            styles.append(("FONT", (0, r_i), (-1, r_i), "Helvetica-Bold", 8))
    avail = doc.width
    n = len(report.columns)
    text_cols = [i for i, c in enumerate(report.columns) if c.align == "left"]
    num_w = min(1.1 * inch, avail / max(n, 1))
    rest = avail - num_w * (n - len(text_cols))
    widths = [rest / max(len(text_cols), 1) if i in text_cols else num_w for i in range(n)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(styles))
    story.append(table)
    for note in report.notes:
        story += [Spacer(1, 8), Paragraph(_esc(note), cell)]
    story += [Spacer(1, 12), Paragraph(f"Generated {datetime.now():%m/%d/%Y %I:%M %p}", center)]
    doc.build(story)
    return buf.getvalue()


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
