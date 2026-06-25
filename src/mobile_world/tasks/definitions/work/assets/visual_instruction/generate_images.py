"""Pre-render the whiteboard images for MattermostVisualInstructionResponseTask.

Run once to (re)produce the committed PNGs; they are served statically by the
mobile-world server so the task no longer depends on placehold.co (unreliable +
cropped the longest line). Keep the data below in sync with the task class.

    python generate_images.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent

# Keep in sync with MattermostVisualInstructionResponseTask.{CONTACTS,ALARMS}_DATA
CONTACTS_DATA = [
    {"name": "Dr. Smith", "phone": "555-1010"},
    {"name": "Safety Officer", "phone": "555-2020"},
]
ALARMS_DATA = [
    {"label": "Morning Shift", "time_str": "08:00 AM"},
    {"label": "Evening Shift", "time_str": "08:00 PM"},
]

FRAME = "#9aa0a6"   # aluminium whiteboard frame
BOARD = "#fcfcf7"   # off-white board surface
INK = "#1a1a2e"     # marker (title)
LINE_INK = "#15366b"  # marker (body)

FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"


def _make_board(title: str, lines: list[str], out_path: Path) -> None:
    title_font = ImageFont.truetype(FONT_BOLD, 56)
    line_font = ImageFont.truetype(FONT_REG, 44)

    pad = 56          # inner padding inside the board
    frame_w = 26      # whiteboard frame thickness
    title_gap = 36    # gap below title rule
    line_h = 78       # per-line height

    def _w(text, font):
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]

    content_w = max([_w(title, title_font)] + [_w(t, line_font) for t in lines])
    board_w = content_w + 2 * pad
    board_h = pad + 64 + title_gap + line_h * len(lines) + pad
    img_w = board_w + 2 * frame_w
    img_h = board_h + 2 * frame_w

    img = Image.new("RGB", (img_w, img_h), FRAME)
    draw = ImageDraw.Draw(img)
    draw.rectangle([frame_w, frame_w, frame_w + board_w, frame_w + board_h], fill=BOARD)

    x = frame_w + pad
    y = frame_w + pad
    draw.text((x, y), title, font=title_font, fill=INK)
    rule_y = y + 64 + 8
    draw.line([(x, rule_y), (x + content_w, rule_y)], fill=INK, width=4)

    y = rule_y + title_gap
    for text in lines:
        draw.text((x, y), text, font=line_font, fill=LINE_INK)
        y += line_h

    img.save(out_path)
    print(f"wrote {out_path} ({img_w}x{img_h})")


def main() -> None:
    _make_board(
        "EMERGENCY CONTACTS",
        [f"{c['name']}: {c['phone']}" for c in CONTACTS_DATA],
        OUT_DIR / "emergency_contacts.png",
    )
    _make_board(
        "SHIFT SCHEDULE",
        [f"{a['label']}: {a['time_str']}" for a in ALARMS_DATA],
        OUT_DIR / "shift_schedule.png",
    )


if __name__ == "__main__":
    main()
