"""Generate the writeup figures with high-definition vector-sharp clarity.

    python scripts/make_figures.py

Writes docs/figures/card.png (560x280, the Kaggle card) and
docs/figures/architecture.png (2400x1320, 2K control loop diagram).
"""
from __future__ import annotations

import pathlib
from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "figures"

# Dark slate palette
BG = (11, 17, 32)
PANEL = (22, 33, 54)
PANEL_BORDER = (51, 65, 85)
INK = (241, 245, 249)
MUTED = (148, 163, 184)
ACCENT = (56, 189, 248)       # Cyan
ACCENT_BG = (18, 44, 74)
GATE_COLOR = (251, 146, 60)    # Amber/orange
GATE_BG = (45, 28, 16)
ACQ_COLOR = (52, 211, 153)     # Emerald/green
ACQ_BG = (16, 42, 36)

FONT_FAMILY = "C:/Windows/Fonts/segoeui.ttf"
FONT_BOLD = "C:/Windows/Fonts/seguisb.ttf"
FONT_MONO = "C:/Windows/Fonts/consola.ttf"


def get_font(size: int, bold: bool = False, mono: bool = False):
    try:
        path = FONT_MONO if mono else (FONT_BOLD if bold else FONT_FAMILY)
        return ImageFont.truetype(path, size)
    except OSError:
        try:
            return ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf", size)
        except OSError:
            return ImageFont.load_default()


def draw_box(draw, xy, fill, outline=None, width=2, radius=16):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_arrow(draw, start, end, colour=MUTED, width=4, tip_size=12):
    draw.line([start, end], fill=colour, width=width)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        draw.polygon([
            (x2, y2),
            (x2 - direction * tip_size, y2 - tip_size * 0.6),
            (x2 - direction * tip_size, y2 + tip_size * 0.6)
        ], fill=colour)
    else:
        direction = 1 if y2 > y1 else -1
        draw.polygon([
            (x2, y2),
            (x2 - tip_size * 0.6, y2 - direction * tip_size),
            (x2 + tip_size * 0.6, y2 - direction * tip_size)
        ], fill=colour)


def card() -> None:
    # 560x280 at 2x supersampling for extreme sharpness
    scale = 2
    w, h = 560 * scale, 280 * scale
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    # Accent top bar
    draw.rectangle([0, 0, w, 8 * scale], fill=ACCENT)

    draw.text((28 * scale, 24 * scale), "PLE 2026  ·  AGENT HARNESS", font=get_font(13 * scale, bold=True), fill=ACCENT)
    draw.text((28 * scale, 48 * scale), "Gated Harness", font=get_font(38 * scale, bold=True), fill=INK)
    draw.text((28 * scale, 100 * scale), "The gate re-opens every deliverable", font=get_font(16 * scale), fill=MUTED)
    draw.text((28 * scale, 124 * scale), "and recomputes it from disk.", font=get_font(16 * scale), fill=MUTED)

    steps = ["model", "harness", "gate", "deliverable"]
    x = 28 * scale
    for index, step in enumerate(steps):
        bw = 112 * scale
        colour = GATE_COLOR if step == "gate" else PANEL
        b_outline = GATE_COLOR if step == "gate" else PANEL_BORDER
        draw_box(draw, [x, 160 * scale, x + bw, 204 * scale], fill=colour, outline=b_outline, width=2 * scale, radius=10 * scale)
        label_colour = BG if step == "gate" else INK
        draw.text((x + 16 * scale, 172 * scale), step, font=get_font(15 * scale, bold=True), fill=label_colour)
        if index < len(steps) - 1:
            draw_arrow(draw, (x + bw + 4 * scale, 182 * scale), (x + bw + 18 * scale, 182 * scale), ACCENT, width=3 * scale, tip_size=8 * scale)
        x += bw + 22 * scale

    draw.text((28 * scale, 224 * scale), "Strict pass · signed failure · bounded repair", font=get_font(13 * scale), fill=MUTED)
    draw.text((28 * scale, 250 * scale), "github.com/hedephilip/ple-harness", font=get_font(12 * scale, bold=True), fill=ACCENT)

    # Downsample to target 560x280 with Lanczos for razor-sharp antialiasing
    final_card = img.resize((560, 280), Image.Resampling.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    final_card.save(OUT / "card.png", quality=100)


def architecture() -> None:
    # 2K Resolution: 2400 x 1320 (2x of 1200x660)
    scale = 2
    w, h = 1200 * scale, 660 * scale
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    # Header
    draw.text((40 * scale, 32 * scale), "Gated Harness — control loop", font=get_font(28 * scale, bold=True), fill=INK)
    draw.text((40 * scale, 74 * scale), "The model proposes. Python re-reads the artifact and disposes.",
              font=get_font(15 * scale), fill=MUTED)

    # 1. Evaluator Box (Top Left)
    draw_box(draw, [40 * scale, 120 * scale, 310 * scale, 305 * scale], fill=PANEL, outline=PANEL_BORDER, width=2 * scale, radius=14 * scale)
    draw.text((58 * scale, 136 * scale), "Evaluator", font=get_font(18 * scale, bold=True), fill=INK)
    lines_eval = [
        "task frame (instruction,",
        "workdir, limits)",
        "exec · read_file",
        "write_file · http"
    ]
    for idx, l in enumerate(lines_eval):
        draw.text((58 * scale, 172 * scale + idx * 28 * scale), l, font=get_font(13 * scale), fill=MUTED)

    # 2. serve.py · harness.py Box (Top Center - Highlighted Cyan)
    draw_box(draw, [370 * scale, 120 * scale, 680 * scale, 305 * scale], fill=ACCENT_BG, outline=ACCENT, width=3 * scale, radius=14 * scale)
    draw.text((390 * scale, 136 * scale), "serve.py  ·  harness.py", font=get_font(18 * scale, bold=True), fill=ACCENT)
    lines_serve = [
        "WebSocket v1, ping_interval=None",
        "one agent turn per round",
        "tool calls → protocol requests",
        "budget: rounds, not wall clock"
    ]
    for idx, l in enumerate(lines_serve):
        draw.text((390 * scale, 172 * scale + idx * 28 * scale), l, font=get_font(13 * scale), fill=INK)

    # 3. Model (sponsored) Box (Top Right)
    draw_box(draw, [740 * scale, 120 * scale, 1040 * scale, 230 * scale], fill=PANEL, outline=PANEL_BORDER, width=2 * scale, radius=14 * scale)
    draw.text((760 * scale, 136 * scale), "Model (sponsored)", font=get_font(18 * scale, bold=True), fill=INK)
    draw.text((760 * scale, 172 * scale), "egress proxy, model endpoint", font=get_font(13 * scale), fill=MUTED)
    draw.text((760 * scale, 196 * scale), "only reachable host", font=get_font(13 * scale), fill=MUTED)

    # Connectors between serve.py and Model
    draw_arrow(draw, (684 * scale, 168 * scale), (734 * scale, 168 * scale), ACCENT, width=3 * scale, tip_size=10 * scale)
    draw_arrow(draw, (734 * scale, 195 * scale), (684 * scale, 195 * scale), MUTED, width=3 * scale, tip_size=10 * scale)

    # 4. Acquisition Box (Middle Left - Green Accent)
    draw_box(draw, [40 * scale, 345 * scale, 310 * scale, 485 * scale], fill=ACQ_BG, outline=ACQ_COLOR, width=2 * scale, radius=14 * scale)
    draw.text((58 * scale, 360 * scale), "Acquisition", font=get_font(18 * scale, bold=True), fill=ACQ_COLOR)
    lines_acq = [
        "paths from the prompt",
        "find /app /filesystem -newer",
        "folders enumerated",
        "zip · docx · xlsx opened"
    ]
    for idx, l in enumerate(lines_acq):
        draw.text((58 * scale, 394 * scale + idx * 26 * scale), l, font=get_font(13 * scale), fill=MUTED)
    draw_arrow(draw, (314 * scale, 415 * scale), (364 * scale, 415 * scale), ACQ_COLOR, width=3 * scale, tip_size=10 * scale)

    # 5. Task Container Box (Middle Center)
    draw_box(draw, [370 * scale, 345 * scale, 680 * scale, 485 * scale], fill=PANEL, outline=PANEL_BORDER, width=2 * scale, radius=14 * scale)
    draw.text((390 * scale, 360 * scale), "Task container", font=get_font(18 * scale, bold=True), fill=INK)
    draw.text((390 * scale, 394 * scale), "/app  ·  /filesystem", font=get_font(13 * scale, bold=True), fill=ACCENT)
    draw.text((390 * scale, 422 * scale), "corpus, spreads, CAD, mail", font=get_font(13 * scale), fill=MUTED)
    draw.text((390 * scale, 448 * scale), "2 CPU · 4 GB · 6 h", font=get_font(13 * scale), fill=MUTED)

    # Connectors between serve.py and Task container
    draw_arrow(draw, (515 * scale, 310 * scale), (515 * scale, 340 * scale), MUTED, width=3 * scale, tip_size=10 * scale)
    draw_arrow(draw, (545 * scale, 340 * scale), (545 * scale, 310 * scale), MUTED, width=3 * scale, tip_size=10 * scale)

    # 6. Gate Registry Box (Middle Right - Amber Accent)
    draw_box(draw, [740 * scale, 345 * scale, 1040 * scale, 485 * scale], fill=GATE_BG, outline=GATE_COLOR, width=3 * scale, radius=14 * scale)
    draw.text((760 * scale, 360 * scale), "Gate registry", font=get_font(18 * scale, bold=True), fill=GATE_COLOR)
    lines_gate = [
        "13 discipline gates",
        "6 cross-cutting gates",
        "applies(ctx) — declines, not fails",
        "signed (gate, cause, obs, limit)"
    ]
    for idx, l in enumerate(lines_gate):
        draw.text((760 * scale, 394 * scale + idx * 26 * scale), l, font=get_font(13 * scale), fill=INK)
    draw_arrow(draw, (684 * scale, 415 * scale), (734 * scale, 415 * scale), GATE_COLOR, width=3 * scale, tip_size=10 * scale)
    draw_arrow(draw, (734 * scale, 445 * scale), (684 * scale, 445 * scale), MUTED, width=3 * scale, tip_size=10 * scale)

    # 7. Repair, Bounded Box (Bottom Center)
    draw_box(draw, [370 * scale, 530 * scale, 680 * scale, 625 * scale], fill=PANEL, outline=PANEL_BORDER, width=2 * scale, radius=14 * scale)
    draw.text((390 * scale, 544 * scale), "Repair, bounded", font=get_font(18 * scale, bold=True), fill=INK)
    draw.text((390 * scale, 574 * scale), "failures → one lesson → retry", font=get_font(13 * scale), fill=MUTED)
    draw.text((390 * scale, 598 * scale), "then stop: no unbounded self-correction", font=get_font(13 * scale), fill=MUTED)

    # Connectors to Repair
    draw_arrow(draw, (525 * scale, 490 * scale), (525 * scale, 525 * scale), MUTED, width=3 * scale, tip_size=10 * scale)
    draw_arrow(draw, (684 * scale, 575 * scale), (745 * scale, 510 * scale), MUTED, width=3 * scale, tip_size=10 * scale)

    # Footer note
    draw.text((40 * scale, 634 * scale), "Verdict goes to a log frame; final_message carries the agent's words to the grader.",
              font=get_font(13 * scale), fill=MUTED)

    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "architecture.png", quality=100)
    print(f"Saved {OUT / 'architecture.png'} ({w}x{h})")


if __name__ == "__main__":
    card()
    architecture()
