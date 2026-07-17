"""Native, server-side PDF report generation (ReportLab).

Produces a polished, paginated Design Thinking report from a run's metadata +
artifacts — a real document (cover, per-phase sections, per-artifact cards with
content) rather than a browser print. Used by ``GET /v1/runs/{id}/export.pdf``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_PHASE_ORDER = ["discover", "define", "ideate", "prototype", "validate"]
_PHASE_COLOR = {
    "discover": colors.HexColor("#3f6fe0"),
    "define": colors.HexColor("#8a4fe0"),
    "ideate": colors.HexColor("#c9930f"),
    "prototype": colors.HexColor("#199aa8"),
    "validate": colors.HexColor("#1c9e77"),
}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=24, spaceAfter=6,
                                 textColor=colors.HexColor("#12203f")),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=11,
                               textColor=colors.HexColor("#556")),
        "phase": ParagraphStyle("p", parent=base["Heading1"], fontSize=15, spaceBefore=10,
                                 spaceAfter=4),
        "art": ParagraphStyle("a", parent=base["Heading2"], fontSize=11.5, spaceBefore=8,
                              spaceAfter=1, textColor=colors.HexColor("#1a2a4a")),
        "meta": ParagraphStyle("m", parent=base["Normal"], fontSize=8,
                               textColor=colors.HexColor("#777"), alignment=TA_LEFT),
        "code": ParagraphStyle("c", parent=base["Code"], fontSize=7.5, leading=9.5,
                               textColor=colors.HexColor("#16233d")),
    }


def render_run_pdf(summary: dict[str, Any], artifacts: list[dict[str, Any]]) -> bytes:
    """Return a PDF (bytes) for a run summary + artifacts."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title="Design Thinking Run Report",
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
    )
    st = _styles()
    flow: list[Any] = []

    # --- Cover ---
    flow.append(Paragraph("Design Thinking Run — Report", st["title"]))
    flow.append(Paragraph(summary.get("problem", ""), st["sub"]))
    flow.append(Spacer(1, 8))
    flow.append(HRFlowable(width="100%", color=colors.HexColor("#dde3ee")))
    flow.append(Spacer(1, 8))

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    meta_rows = [
        ["Run id", summary.get("run_id", "")],
        ["Status", summary.get("status", "")],
        ["Depth", summary.get("depth", "")],
        ["Artifacts", str(summary.get("artifacts", 0))],
        ["Tokens", f"{summary.get('tokens_in', 0) + summary.get('tokens_out', 0):,}"],
        ["Est. cost", f"${summary.get('est_cost_usd', 0)}"],
        ["Loops", str(summary.get("loop_count", 0))],
        ["Generated", generated],
    ]
    tbl = Table(meta_rows, colWidths=[35 * mm, 130 * mm])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#667")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#122")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#eef1f7")),
    ]))
    flow.append(tbl)
    flow.append(Spacer(1, 6))

    # --- Per-phase sections ---
    for phase in _PHASE_ORDER:
        group = [a for a in artifacts if a.get("phase") == phase]
        if not group:
            continue
        pstyle = ParagraphStyle("ph", parent=st["phase"], textColor=_PHASE_COLOR[phase])
        flow.append(Paragraph(f"{phase.title()} &nbsp;·&nbsp; {len(group)} artifacts", pstyle))
        flow.append(HRFlowable(width="100%", color=_PHASE_COLOR[phase], thickness=1.2))
        flow.append(Spacer(1, 3))
        for a in group:
            flow.append(Paragraph(f"[{a.get('type')}] {a.get('title', '')}", st["art"]))
            flow.append(Paragraph(
                f"Producer: {a.get('producer')} &nbsp;·&nbsp; Model: {a.get('model')} "
                f"&nbsp;·&nbsp; Confidence: {a.get('confidence')}", st["meta"]))
            body = json.dumps(a.get("content", {}), indent=2, default=str)
            if len(body) > 3500:
                body = body[:3500] + "\n… (truncated)"
            flow.append(Preformatted(body, st["code"]))
            flow.append(Spacer(1, 4))
        flow.append(PageBreak())

    if not any(a.get("phase") in _PHASE_ORDER for a in artifacts):
        flow.append(Paragraph("No artifacts were produced for this run.", st["sub"]))

    doc.build(flow)
    return buf.getvalue()
