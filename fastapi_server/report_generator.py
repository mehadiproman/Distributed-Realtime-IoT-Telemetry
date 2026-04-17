"""
PDF Report Generator for IoT Telemetry Data.
Single-page executive summary. Tight layout targeting A4.
"""
import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


# ── Brand Colors ──
BRAND_PRIMARY = colors.HexColor("#6b00ff")
BRAND_ACCENT = colors.HexColor("#a644ff")
BRAND_GREEN = colors.HexColor("#32d74b")
BRAND_BLUE = colors.HexColor("#0a84ff")
BRAND_RED = colors.HexColor("#ff453a")
BRAND_YELLOW = colors.HexColor("#c89800")
BRAND_CYAN = colors.HexColor("#0096b7")

TEXT_DARK = colors.HexColor("#1d1d1f")
TEXT_SEC = colors.HexColor("#6e6e73")
TEXT_MUTED = colors.HexColor("#aeaeb2")

HDR_BG = colors.HexColor("#1d1d2e")
ALT_ROW = colors.HexColor("#f5f5fa")
BORDER = colors.HexColor("#e5e5ea")
DIVIDER = colors.HexColor("#d2d2d7")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle('RTitle', parent=s['Title'], fontSize=24, spaceAfter=1,
        textColor=BRAND_PRIMARY, fontName='Helvetica-Bold', alignment=TA_CENTER, leading=28))
    s.add(ParagraphStyle('RSub', parent=s['Normal'], fontSize=9, spaceAfter=1,
        textColor=TEXT_SEC, alignment=TA_CENTER, leading=13))
    s.add(ParagraphStyle('RSec', parent=s['Normal'], fontSize=12, spaceBefore=0, spaceAfter=4,
        textColor=BRAND_PRIMARY, fontName='Helvetica-Bold', leading=15))
    s.add(ParagraphStyle('RFoot', parent=s['Normal'], fontSize=7, textColor=TEXT_MUTED,
        alignment=TA_CENTER, leading=10))
    return s


def _stats(records, field):
    vals = []
    for r in records:
        v = r.get(field)
        if v is not None:
            try: vals.append(float(v))
            except: pass
    if not vals:
        return {"min": "—", "max": "—", "avg": "—", "count": 0}
    return {"min": round(min(vals), 2), "max": round(max(vals), 2),
            "avg": round(sum(vals) / len(vals), 2), "count": len(vals)}


def _f(v, u):
    return "—" if v == "—" else f"{v} {u}"


def _highlights(stats_list):
    cells = []
    for name, unit, clr, st in stats_list[:5]:
        v = _f(st['avg'], unit)
        top = Paragraph(f'<b>{v}</b>', ParagraphStyle('hv', fontName='Helvetica-Bold',
            fontSize=15, textColor=clr, alignment=TA_CENTER, leading=18))
        bot = Paragraph(name, ParagraphStyle('hl', fontSize=7,
            textColor=TEXT_MUTED, alignment=TA_CENTER))
        mini = Table([[top], [bot]], colWidths=[90], rowHeights=[22, 12])
        mini.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('BOX', (0,0), (-1,-1), 0.7, BORDER),
            ('BACKGROUND', (0,0), (-1,-1), ALT_ROW),
        ]))
        cells.append(mini)
    row = Table([cells], colWidths=[96]*len(cells))
    row.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 2),
    ]))
    return row


def _stat_table(stats_list):
    ps = lambda fn, fs, c, a=TA_CENTER: ParagraphStyle(f'_{id(c)}_{fs}', fontName=fn, fontSize=fs, textColor=c, alignment=a, leading=fs+3)
    hdr = [
        Paragraph('<b>Metric</b>', ps('Helvetica-Bold', 9, colors.white, TA_LEFT)),
        Paragraph('<b>Min</b>', ps('Helvetica-Bold', 9, colors.white)),
        Paragraph('<b>Max</b>', ps('Helvetica-Bold', 9, colors.white)),
        Paragraph('<b>Average</b>', ps('Helvetica-Bold', 9, colors.white)),
        Paragraph('<b>Samples</b>', ps('Helvetica-Bold', 9, colors.white)),
    ]
    rows = [hdr]
    for name, unit, clr, st in stats_list:
        rows.append([
            Paragraph(f'<b>{name}</b>', ps('Helvetica-Bold', 9, clr, TA_LEFT)),
            Paragraph(_f(st['min'], unit), ps('Helvetica', 9, TEXT_DARK)),
            Paragraph(_f(st['max'], unit), ps('Helvetica', 9, TEXT_DARK)),
            Paragraph(f'<b>{_f(st["avg"], unit)}</b>', ps('Helvetica-Bold', 9, TEXT_DARK)),
            Paragraph(str(st['count']), ps('Helvetica', 9, TEXT_SEC)),
        ])
    t = Table(rows, colWidths=[115, 85, 85, 95, 65], rowHeights=[24] + [22]*len(stats_list))
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), HDR_BG),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, ALT_ROW]),
        ('LINEBELOW', (0,0), (-1,0), 1.5, BRAND_PRIMARY),
        ('LINEBELOW', (0,1), (-1,-2), 0.4, BORDER),
        ('BOX', (0,0), (-1,-1), 0.7, BORDER),
        ('LINEAFTER', (0,0), (-2,-1), 0.4, BORDER),
    ]))
    return t


def _counts(sensor_n, soil_n):
    total = sensor_n + soil_n
    ps_l = ParagraphStyle('cl', fontSize=7, textColor=TEXT_MUTED, alignment=TA_CENTER)
    ps_v = lambda fs: ParagraphStyle(f'cv{fs}', fontSize=fs, fontName='Helvetica-Bold', textColor=TEXT_DARK, alignment=TA_CENTER, leading=fs+4)
    t = Table([
        [Paragraph('Total Records', ps_l), Paragraph('Sensor Records', ps_l), Paragraph('Soil Records', ps_l)],
        [Paragraph(f'<b>{total}</b>', ps_v(16)), Paragraph(f'{sensor_n}', ps_v(13)), Paragraph(f'{soil_n}', ps_v(13))],
    ], colWidths=[150, 140, 140], rowHeights=[14, 22])
    t.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LINEAFTER', (0,0), (-2,-1), 0.4, BORDER),
    ]))
    return t


def generate_pdf_report(sensor_data: list, soil_data: list,
                        start_str: str, end_str: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        topMargin=15*mm, bottomMargin=12*mm,
        leftMargin=18*mm, rightMargin=18*mm,
        title="IoT Telemetry Report")

    st = _styles()
    el = []

    # ── HEADER ──
    el.append(Paragraph("IoT Telemetry Report", st['RTitle']))
    el.append(Paragraph("Environmental Monitoring &amp; Analytics Platform", st['RSub']))
    el.append(HRFlowable(width="100%", thickness=2, color=BRAND_ACCENT, spaceBefore=2, spaceAfter=2))
    el.append(Paragraph(
        f"Period: <b>{start_str}</b>  →  <b>{end_str}</b>"
        f"&nbsp;&nbsp;|&nbsp;&nbsp;"
        f"Generated: <b>{datetime.now().strftime('%b %d, %Y – %I:%M %p')}</b>",
        st['RSub']))
    el.append(Spacer(1, 10))

    # ── STATS ──
    temp = _stats(sensor_data, 'temperature')
    hum = _stats(sensor_data, 'pressure')
    aqi = _stats(sensor_data, 'air_quality')
    light = _stats(sensor_data, 'light_intensity')
    soil = _stats(soil_data, 'moisture')

    sl = [
        ("Temperature", "°C", BRAND_RED, temp),
        ("Humidity", "%", BRAND_BLUE, hum),
        ("Air Quality", "AQI", BRAND_GREEN, aqi),
        ("Light", "lux", BRAND_YELLOW, light),
        ("Soil Moisture", "%", BRAND_CYAN, soil),
    ]

    # ── KEY METRICS ──
    el.append(Paragraph("Key Metrics at a Glance", st['RSec']))
    el.append(_highlights(sl))
    el.append(Spacer(1, 12))

    # ── SUMMARY TABLE ──
    el.append(Paragraph("Summary Statistics", st['RSec']))
    el.append(_stat_table(sl))
    el.append(Spacer(1, 12))

    # ── COUNTS ──
    el.append(HRFlowable(width="100%", thickness=0.4, color=DIVIDER, spaceBefore=4, spaceAfter=6))
    el.append(_counts(len(sensor_data), len(soil_data)))

    # ── FOOTER ──
    el.append(Spacer(1, 14))
    el.append(HRFlowable(width="100%", thickness=0.6, color=DIVIDER, spaceBefore=4, spaceAfter=4))
    el.append(Paragraph(
        "Auto-generated by IoT Environmental Monitoring System  ·  "
        "Smart Agriculture Dashboard  ·  Distributed Real-time IoT Telemetry",
        st['RFoot']))

    doc.build(el)
    return buf.getvalue()
