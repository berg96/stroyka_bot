"""Смета в PDF — то, что мастер отправляет заказчику.

Ресёрч по рынку: заказчик уходит к тому, кто прислал понятную расшифровку, а не
голую цифру в мессенджере. Поэтому PDF на одну страницу: работы, материалы, итог.
"""

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from tilebot.core.estimate import Estimate, money

FONT = "DejaVu"
FONT_BOLD = "DejaVu-Bold"
_FONTS_READY = False


def _ensure_fonts() -> None:
    """Кириллица в reportlab не работает без TTF — регистрируем DejaVu один раз."""
    global _FONTS_READY
    if _FONTS_READY:
        return
    pdfmetrics.registerFont(TTFont(FONT, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdfmetrics.registerFont(
        TTFont(FONT_BOLD, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    )
    _FONTS_READY = True


def render_estimate_pdf(
    est: Estimate,
    *,
    master_name: str = "",
    master_phone: str = "",
    schemes: list[bytes] | None = None,
) -> bytes:
    """Смета в PDF. Схемы раскладки, если есть, идут отдельными страницами."""
    _ensure_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Смета — {est.title}",
    )

    base = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "h1", parent=base["Heading1"], fontName=FONT_BOLD, fontSize=17, spaceAfter=2
    )
    h2 = ParagraphStyle(
        "h2", parent=base["Heading2"], fontName=FONT_BOLD, fontSize=12, spaceBefore=10, spaceAfter=4
    )
    small = ParagraphStyle("small", parent=base["Normal"], fontName=FONT, fontSize=9,
                           textColor=colors.HexColor("#64748B"))

    story = [Paragraph(f"Смета — {est.title}", h1)]
    header = [date.today().strftime("%d.%m.%Y")]
    if master_name:
        header.append(master_name)
    if master_phone:
        header.append(master_phone)
    story.append(Paragraph(" · ".join(header), small))

    def table(rows: list[list[str]], widths: list[float], total_row: bool = False) -> Table:
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        style = [
            ("FONTNAME", (0, 0), (-1, -1), FONT),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        if total_row:
            style += [
                ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#94A3B8")),
            ]
        t.setStyle(TableStyle(style))
        return t

    if est.works:
        story.append(Paragraph("Работы", h2))
        rows = [["Наименование", "Кол-во", "Цена", "Сумма"]]
        for w in est.works:
            qty = f"{w.qty:g} {w.unit}".strip() if w.unit else "—"
            price = money(w.price) if w.unit else "—"
            rows.append([w.name, qty, price, money(w.total)])
        rows.append(["Итого работы", "", "", money(est.works_total)])
        story.append(table(rows, [90 * mm, 25 * mm, 25 * mm, 28 * mm], total_row=True))

    if est.materials:
        story.append(Paragraph("Материалы", h2))
        rows = [["Наименование", "Кол-во", "Стоимость"]]
        for m in est.materials:
            cost = est.material_costs.get(m.name)
            rows.append([
                f"{m.name}" + (f" ({m.note})" if m.note else ""),
                f"{m.format_qty()} {m.unit}",
                money(cost) if cost else "—",
            ])
        if est.materials_total:
            rows.append(["Итого материалы", "", money(est.materials_total)])
        story.append(
            table(rows, [110 * mm, 28 * mm, 30 * mm], total_row=bool(est.materials_total))
        )

    story.append(Spacer(1, 10))
    total = Table(
        [["ВСЕГО", money(est.grand_total)]], colWidths=[138 * mm, 30 * mm], hAlign="LEFT"
    )
    total.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 12),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(total)

    if est.note:
        story.append(Spacer(1, 8))
        story.append(Paragraph(est.note, small))

    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "Расход материалов — расчётный, по средним нормам производителей; "
            "фактический зависит от основания и партии смеси.",
            small,
        )
    )

    for png in schemes or []:
        story.append(Spacer(1, 14))
        img = Image(io.BytesIO(png))
        # Вписываем схему в ширину полосы, пропорции сохраняем.
        max_w = doc.width
        scale = min(1.0, max_w / img.drawWidth)
        img.drawWidth *= scale
        img.drawHeight *= scale
        story.append(img)

    doc.build(story)
    return buf.getvalue()
