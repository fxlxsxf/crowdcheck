"""The 1600x900 PNG card. This is the thing people screenshot.

Three visual weights only: bold white, regular white, regular grey. Smallest
text is 24px, so it stays readable as a thumbnail.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..metrics import fmt_duration
from ..models import MetricName, MetricResult, Report

WIDTH, HEIGHT = 1600, 900
MARGIN_X, MARGIN_Y = 90, 80
BG = (11, 13, 16)
FG = (236, 238, 240)
DIM = (128, 136, 146)
MIN_FONT = 24

FONT_DIR = Path(__file__).parent / "fonts"
REGULAR = FONT_DIR / "DejaVuSansMono.ttf"
BOLD = FONT_DIR / "DejaVuSansMono-Bold.ttf"


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _nv(label: str, r: MetricResult | None) -> str:
    reason = r.reason if r and r.reason else "not computed"
    return f"{label}: not visible ({reason})"


def card_lines(report: Report) -> list[str]:
    """The body lines, in the order the spec shows them."""
    by = {r.name: r for r in report.results}
    lines: list[str] = []

    tr = by.get(MetricName.TRACK_RECORD)
    if tr and tr.visible:
        n = tr.raw["prior_mints"]
        lines.append(f"{n} token{'s' if n != 1 else ''} held before this one"
                     + (" (capped)" if tr.raw["cap_hit"] else ""))
        lines.append(f"{tr.raw['survived']} survived 30 days"
                     + (f" ({tr.raw['resolved']} of {n} resolved)" if tr.raw["resolved"] < n else ""))
    else:
        lines.append(_nv("prior tokens", tr))

    wa = by.get(MetricName.WALLET_AGE)
    lines.append(f"{wa.raw['share_under_24h'] * 100:.0f}% of wallets created today"
                 if wa and wa.visible else _nv("wallet age", wa))

    dp = by.get(MetricName.DEPLOYER)
    if dp and dp.visible:
        lines.append(f"deployer linked to {dp.raw['linked_mints']} prior mints, "
                     f"median outcome {dp.raw['median_outcome_pct']:+.0f}%")
    else:
        lines.append(_nv("deployer", dp))

    ht = by.get(MetricName.HOLD_TIME)
    lines.append(f"median prior position: {fmt_duration(ht.raw['median_seconds'])}"
                 if ht and ht.visible else _nv("hold time", ht))
    return lines


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for w in words:
        trial = f"{current} {w}".strip()
        if font.getlength(trial) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def render_card(report: Report, path: str | Path) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    usable = WIDTH - 2 * MARGIN_X

    title = f"CROWD REPORT · ${report.symbol}" if report.symbol else "CROWD REPORT"
    subtitle = f"top {report.holders_found} holders"
    body = card_lines(report)
    verdict = f"VERDICT: {report.verdict}"
    footer_left = f"{report.mint[:6]}…{report.mint[-6:]}"
    footer_right = ("history score "
                    + (f"{report.score.total:.0f}/100" if report.score.total is not None else "not printed")
                    + " · descriptive, not advice")

    # Shrink the body size until the block fits vertically and horizontally.
    for size in range(40, MIN_FONT - 1, -2):
        title_f, body_f, bold_f = _font(BOLD, int(size * 1.5)), _font(REGULAR, size), _font(BOLD, size)
        small_f = _font(REGULAR, max(MIN_FONT, int(size * 0.7)))
        verdict_lines = _wrap(verdict, bold_f, usable)
        line_h = int(size * 1.45)
        height = (int(size * 1.5) + 14 + small_f.size + 36 + line_h * (len(body) + len(verdict_lines) + 2)
                  + 30 + small_f.size)
        too_wide = any(body_f.getlength(line) > usable for line in body)
        if height <= HEIGHT - 2 * MARGIN_Y and not too_wide:
            break

    y = MARGIN_Y
    draw.text((MARGIN_X, y), title, font=title_f, fill=FG)
    y += title_f.size + 14
    draw.text((MARGIN_X, y), subtitle, font=small_f, fill=DIM)
    y += small_f.size + 36
    for line in body:
        draw.text((MARGIN_X, y), line, font=body_f, fill=FG if "not visible" not in line else DIM)
        y += line_h
    y += line_h // 2
    for line in verdict_lines:
        draw.text((MARGIN_X, y), line, font=bold_f, fill=FG)
        y += line_h
    y += line_h // 4
    draw.text((MARGIN_X, y), report.closing_line, font=bold_f, fill=FG)

    fy = HEIGHT - MARGIN_Y // 2 - small_f.size
    draw.text((MARGIN_X, fy), footer_left, font=small_f, fill=DIM)
    draw.text((WIDTH - MARGIN_X - small_f.getlength(footer_right), fy), footer_right, font=small_f, fill=DIM)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
