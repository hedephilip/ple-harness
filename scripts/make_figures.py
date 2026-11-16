"""Generate the writeup figures that do not depend on dev-set results.

    python scripts/make_figures.py

Writes docs/figures/card.png (560x280, the Kaggle card) and
docs/figures/architecture.png (the control loop). Figures that need measured
data — failure breakdown, score vs cost — are not here by design: they can only
be drawn after `eval/run.py`, and inventing them would misrepresent the entry.
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "figures"
BG = (15, 23, 42)
PANEL = (30, 41, 59)
INK = (226, 232, 240)
MUTED = (148, 163, 184)
ACCENT = (56, 189, 248)
WARN = (248, 180, 90)

FONT = "C:/Windows/Fonts/arial.ttf"
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def box(draw, xy, fill, outline=None, width=1, radius=8):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def arrow(draw, start, end, colour=MUTED, width=2):
    draw.line([start, end], fill=colour, width=width)
    (x1, y1), (x2, y2) = start, end
    if abs(x2 - x1) >= abs(y2 - y1):
        tip = 6 if x2 > x1 else -6
        draw.polygon([(x2, y2), (x2 - tip, y2 - 4), (x2 - tip, y2 + 4)], fill=colour)
    else:
        tip = 6 if y2 > y1 else -6
        draw.polygon([(x2, y2), (x2 - 4, y2 - tip), (x2 + 4, y2 - tip)], fill=colour)


def card() -> None:
    image = Image.new("RGB", (560, 280), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 560, 5], fill=ACCENT)

    draw.text((28, 24), "PLE 2026  ·  AGENT HARNESS", font=font(13), fill=ACCENT)
    draw.text((28, 48), "Gated Harness", font=font(38, True), fill=INK)
    draw.text((28, 96), "The gate re-opens every deliverable", font=font(16), fill=MUTED)
    draw.text((28, 118), "and recomputes it from disk.", font=font(16), fill=MUTED)

    steps = ["model", "harness", "gate", "deliverable"]
    x = 28
    for index, step in enumerate(steps):
        width = 112
        colour = WARN if step == "gate" else PANEL
        box(draw, [x, 158, x + width, 200], colour)
        label_colour = BG if step == "gate" else INK
        draw.text((x + 14, 172), step, font=font(14, True), fill=label_colour)
        if index < len(steps) - 1:
            arrow(draw, (x + width + 4, 179), (x + width + 18, 179), ACCENT)
        x += width + 22

    draw.text((28, 222), "Strict pass · signed failure · bounded repair", font=font(13), fill=MUTED)
    draw.text((28, 248), "github.com/hedephilip/ple-harness", font=font(12), fill=ACCENT)
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / "card.png")


def architecture() -> None:
    image = Image.new("RGB", (1200, 660), BG)
    draw = ImageDraw.Draw(image)
    draw.text((36, 30), "Gated Harness — control loop", font=font(26, True), fill=INK)
    draw.text((36, 66), "The model proposes. Python re-reads the artifact and disposes.",
              font=font(14), fill=MUTED)

    # evaluator
    box(draw, [36, 120, 300, 300], PANEL, outline=(71, 85, 105))
    draw.text((52, 134), "Evaluator", font=font(16, True), fill=INK)
    for index, line in enumerate(["task frame (instruction,", "workdir, limits)",
                                  "exec · read_file", "write_file · http"]):
        draw.text((52, 162 + index * 24), line, font=font(12), fill=MUTED)

    # serve + harness
    box(draw, [360, 120, 660, 300], PANEL, outline=ACCENT, width=2)
    draw.text((376, 134), "serve.py  ·  harness.py", font=font(16, True), fill=ACCENT)
    for index, line in enumerate(["WebSocket v1, ping_interval=None",
                                  "one agent turn per round",
                                  "tool calls → protocol requests",
                                  "budget: rounds, not wall clock"]):
        draw.text((376, 162 + index * 24), line, font=font(12), fill=MUTED)

    # model
    box(draw, [720, 120, 1000, 220], PANEL, outline=(71, 85, 105))
    draw.text((736, 134), "Model (sponsored)", font=font(16, True), fill=INK)
    draw.text((736, 162), "egress proxy, model endpoint", font=font(12), fill=MUTED)
    draw.text((736, 184), "only reachable host", font=font(12), fill=MUTED)
    arrow(draw, (664, 176), (714, 176), ACCENT)
    arrow(draw, (714, 200), (664, 200), MUTED)

    # task container
    box(draw, [360, 340, 660, 470], PANEL, outline=(71, 85, 105))
    draw.text((376, 354), "Task container", font=font(16, True), fill=INK)
    draw.text((376, 382), "/app  ·  /filesystem", font=font(12), fill=MUTED)
    draw.text((376, 404), "corpus, spreads, CAD, mail", font=font(12), fill=MUTED)
    draw.text((376, 430), "2 CPU · 4 GB · 6 h", font=font(12), fill=MUTED)
    arrow(draw, (510, 304), (510, 334), MUTED)
    arrow(draw, (540, 334), (540, 304), MUTED)

    # acquisition
    box(draw, [36, 340, 300, 470], (24, 49, 44), outline=(45, 120, 100))
    draw.text((52, 354), "Acquisition", font=font(16, True), fill=(134, 239, 172))
    for index, line in enumerate(["paths from the prompt",
                                  "find /app /filesystem -newer",
                                  "folders enumerated",
                                  "zip · docx · xlsx opened"]):
        draw.text((52, 382 + index * 22), line, font=font(12), fill=MUTED)
    arrow(draw, (306, 405), (354, 405), (45, 120, 100))

    # gate
    box(draw, [720, 340, 1000, 470], (49, 38, 24), outline=WARN, width=2)
    draw.text((736, 354), "Gate registry", font=font(16, True), fill=WARN)
    for index, line in enumerate(["13 discipline gates",
                                  "6 cross-cutting gates",
                                  "applies(ctx) — declines, not fails",
                                  "signed (gate, cause, obs, limit)"]):
        draw.text((736, 382 + index * 22), line, font=font(12), fill=MUTED)
    arrow(draw, (666, 405), (714, 405), WARN)
    arrow(draw, (714, 430), (666, 430), MUTED)

    # repair loop
    box(draw, [360, 520, 660, 610], PANEL, outline=(71, 85, 105))
    draw.text((376, 534), "Repair, bounded", font=font(16, True), fill=INK)
    draw.text((376, 562), "failures → one lesson → retry", font=font(12), fill=MUTED)
    draw.text((376, 584), "then stop: no unbounded self-correction", font=font(12), fill=MUTED)
    arrow(draw, (510, 474), (510, 514), MUTED)
    arrow(draw, (664, 560), (716, 500), MUTED)

    draw.text((36, 628), "Verdict goes to a log frame; final_message carries the "
                         "agent's words to the grader.", font=font(12), fill=MUTED)
    image.save(OUT / "architecture.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    card()
    architecture()
    for name in ("card.png", "architecture.png"):
        path = OUT / name
        with Image.open(path) as image:
            print(f"{name}: {image.size[0]}x{image.size[1]}  {path.stat().st_size // 1024} KiB")
