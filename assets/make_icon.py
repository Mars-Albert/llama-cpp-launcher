"""Build assets/icon.ico and assets/icon.png for the llama.cpp Launcher.

Design: dark slate rounded tile + cream llama silhouette + green "play" badge
(bottom-right). Two variants of the llama artwork are combined in one .ico:

- small sizes (16-48px): SOLID version. The llama glyph from the system emoji
  font (Segoe UI Emoji monochrome base glyph) is line art with thin strokes;
  at 16px the strokes (especially the ear) collapse and the head looks broken.
  Fix: the line-art body outline is NOT closed (a sub-pixel gap at the
  chest/belly junction leaks the interior to the outside), so first dilate the
  mask by 12px (MaxFilter 25) to close the gap — at that radius the gaps
  between the legs are still open — then flood-fill the enclosed interior and
  union it with the mask. The result is a solid silhouette (slightly thicker
  strokes, leg slits preserved, mouth notch survives) and the eye is punched
  back out.
- large sizes (64-256px): DETAIL line-art version (eye, mouth notch, tongue).

Usage:  venv\\Scripts\\python assets\\make_icon.py
Requires: Pillow, Windows (C:\\Windows\\Fonts\\seguiemj.ttf).
"""
import math
import os
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- constants
S = 1024                        # master canvas
SLATE = (30, 41, 59, 255)       # #1e293b tile
CREAM = (249, 238, 216, 255)    # llama
GREEN = (34, 197, 94, 255)      # #22c55e play badge
WHITE = (255, 255, 255, 255)
RADIUS = 228                    # tile corner radius
BADGE_CX, BADGE_CY, BADGE_R, RING = 800, 800, 178, 16
SMALL_SIZES = (16, 20, 24, 32, 40, 48)
LARGE_SIZES = (64, 128, 256)
ALL_SIZES = SMALL_SIZES + LARGE_SIZES
EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"


PADDING = 30  # margin so the 12px dilation in solid_silhouette isn't clipped


def render_lineart() -> Image.Image:
    """Llama line-art alpha mask (the Segoe UI Emoji monochrome base glyph),
    centered on a canvas with PADDING px of empty margin on every side."""
    font = ImageFont.truetype(EMOJI_FONT, 1200)
    tmp = Image.new("L", (2400, 2400), 0)
    d = ImageDraw.Draw(tmp)
    bbox = d.textbbox((0, 0), "\U0001F999", font=font)
    d.text((0, 0), "\U0001F999", font=font, fill=255)
    art = tmp.crop(bbox)
    w, h = art.size
    target_w = 720
    art = art.resize((target_w, int(h * target_w / w)), Image.LANCZOS)
    padded = Image.new("L", (art.width + 2 * PADDING, art.height + 2 * PADDING), 0)
    padded.paste(art, (PADDING, PADDING))
    return padded


def binarize(img: Image.Image, thr: int = 96) -> Image.Image:
    return img.point(lambda p: 255 if p > thr else 0)


def flood_fill_bg(mask: Image.Image) -> Image.Image:
    """Return an L image: 255 where the background is NOT reachable from the
    border (i.e. enclosed interior voids of the line art)."""
    mw, mh = mask.size
    mb = mask.tobytes()
    bg = bytearray(mw * mh)
    dq = deque()

    def seed(j: int) -> None:
        if mb[j] == 0 and not bg[j]:
            bg[j] = 1
            dq.append(j)

    for x in range(mw):
        seed(x)
        seed((mh - 1) * mw + x)
    for y in range(mh):
        seed(y * mw)
        seed(y * mw + mw - 1)

    while dq:
        j = dq.popleft()
        x, y = j % mw, j // mw
        for nb in (j - 1 if x else -1, j + 1 if x < mw - 1 else -1,
                   j - mw if y else -1, j + mw if y < mh - 1 else -1):
            if nb >= 0 and mb[nb] == 0 and not bg[nb]:
                bg[nb] = 1
                dq.append(nb)

    enc = bytearray(mw * mh)
    for i in range(mw * mh):
        if mb[i] == 0 and bg[i] == 0:
            enc[i] = 255
    return Image.frombytes("L", (mw, mh), bytes(enc))


def solid_silhouette(lineart_mask: Image.Image) -> Image.Image:
    """Filled silhouette of the line art.

    The raw mask's body outline has a leak, so flood-filling the raw mask only
    encloses the head. Dilating by 12px closes that gap (while leaving the
    wider gaps between the legs open), after which the interior is enclosed.
    MaxFilter(25) = 12px radius; the jump in enclosed area was verified at 25
    (5.6k -> 55.7k px at this mask's scale).
    """
    mask = binarize(lineart_mask)
    closed = mask.filter(ImageFilter.MaxFilter(25))
    enc = flood_fill_bg(closed)
    solid = ImageChops.lighter(closed, enc)
    filled_px = sum(solid.getdata()) // 255
    line_px = sum(mask.getdata()) // 255
    assert filled_px > line_px * 1.5, (
        f"flood fill failed: solid={filled_px}px not > lineart={line_px}px")
    return solid


def find_eye(solid_or_line_mask: Image.Image):
    """Topmost small separate dot component = the eye. Returns (cx, cy, r)."""
    mask = binarize(solid_or_line_mask)
    mw, mh = mask.size
    mb = mask.tobytes()
    seen = bytearray(mw * mh)
    dots = []
    for start in range(mw * mh):
        if not mb[start] or seen[start]:
            continue
        q = deque([start])
        seen[start] = 1
        comp = [start]
        while q:
            j = q.popleft()
            x, y = j % mw, j // mw
            for nb in (j - 1 if x else -1, j + 1 if x < mw - 1 else -1,
                       j - mw if y else -1, j + mw if y < mh - 1 else -1):
                if nb >= 0 and mb[nb] and not seen[nb]:
                    seen[nb] = 1
                    q.append(nb)
                    comp.append(nb)
                    if len(comp) > 20000:      # main outline — not a dot
                        q.clear()
                        break
        if q:                                   # component blew past the cap
            continue
        if 15 <= len(comp) <= 800:
            cx = sum(c % mw for c in comp) / len(comp)
            cy = sum(c // mw for c in comp) / len(comp)
            dots.append((cx, cy, math.sqrt(len(comp) / math.pi)))
    assert dots, "no eye dot found in line art"
    return min(dots, key=lambda d: d[1])        # topmost = the eye


def compose(llama_mask: Image.Image, eye=None) -> Image.Image:
    """Tile + soft shadow + llama + play badge; optionally punch the eye."""
    lw, lh = llama_mask.size
    lx = (S - lw) // 2 - 40
    ly = (S - lh) // 2 - 16

    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=RADIUS, fill=SLATE)

    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 100), (lx + 10, ly + 22), llama_mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    tile_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=RADIUS, fill=255)
    shadow.putalpha(ImageChops.multiply(shadow.getchannel("A"), tile_mask))
    img = Image.alpha_composite(img, shadow)

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    layer.paste(CREAM, (lx, ly), llama_mask)
    img = Image.alpha_composite(img, layer)

    d = ImageDraw.Draw(img)
    d.ellipse((BADGE_CX - BADGE_R - RING, BADGE_CY - BADGE_R - RING,
               BADGE_CX + BADGE_R + RING, BADGE_CY + BADGE_R + RING), fill=SLATE)
    d.ellipse((BADGE_CX - BADGE_R, BADGE_CY - BADGE_R,
               BADGE_CX + BADGE_R, BADGE_CY + BADGE_R), fill=GREEN)
    cx, cy, tr = BADGE_CX + 16, BADGE_CY, 96
    d.polygon([(cx + int(tr * 0.95), cy), (cx - int(tr * 0.72), cy - int(tr * 0.82)),
               (cx - int(tr * 0.72), cy + int(tr * 0.82))], fill=WHITE)

    if eye:
        ex, ey, er = lx + eye[0], ly + eye[1], max(eye[2], 20) * 1.35
        d.ellipse((ex - er, ey - er, ex + er, ey + er), fill=SLATE)
    return img


def main() -> None:
    lineart = render_lineart()
    solid = solid_silhouette(lineart)
    eye = find_eye(lineart)
    print(f"lineart {lineart.size}, eye {tuple(round(v) for v in eye)}")

    detail = compose(lineart)          # 64/128/256
    small = compose(solid, eye)        # 16..48

    # sanity: torso interior of the small master must be cream, of detail slate
    # (lineart is padded by PADDING, so the body center is offset accordingly)
    lx, ly = (S - lineart.size[0]) // 2 - 40, (S - lineart.size[1]) // 2 - 16
    torso = (lx + 425 + PADDING, ly + 290 + PADDING)
    print("small torso px : ", small.getpixel(torso))
    print("detail torso px:", detail.getpixel(torso))
    assert small.getpixel(torso)[0] > 180, "small master is not solid!"

    frames = {sz: (small if sz in SMALL_SIZES else detail).resize(
        (sz, sz), Image.LANCZOS) for sz in ALL_SIZES}

    # Pillow >= 10 ICO writer: the source image is the size filter gate, so it
    # must be >= every requested size; frames whose size matches exactly are
    # written verbatim. Use the 1024 detail master as a never-used source.
    ico_path = OUT_DIR / "icon.ico"
    detail.save(ico_path, format="ICO",
                sizes=[(s, s) for s in ALL_SIZES],
                append_images=[frames[s] for s in ALL_SIZES])

    detail.resize((512, 512), Image.LANCZOS).save(OUT_DIR / "icon.png")

    # ---- verify what a consumer (e.g. Windows) decodes from the file ----
    for sz in ALL_SIZES:
        im = Image.open(ico_path)
        im.size = (sz, sz)
        im.load()
        px = im.getpixel((int(torso[0] * sz / S), int(torso[1] * sz / S)))
        kind = "solid" if px[0] > 120 else "lineart"
        expect = "solid" if sz in SMALL_SIZES else "lineart"
        status = "ok " if kind == expect else "FAIL"
        print(f"  {sz:3d}px torso={px[:3]} -> {kind} ({status})")
        assert kind == expect, f"{sz}px frame has wrong variant"

    # QA contact sheet (nearest-upscaled, like a pixel-peep)
    cells = []
    for sz in (16, 24, 32, 48, 64, 128):
        im = Image.open(ico_path)
        im.size = (sz, sz)
        im.load()
        up = min(8, 512 // sz)
        cells.append(im.resize((sz * up, sz * up), Image.NEAREST))
    w = sum(c.width for c in cells) + 30 * (len(cells) + 1)
    h = max(c.height for c in cells) + 40
    sheet = Image.new("RGBA", (w, h), (235, 235, 240, 255))
    x = 30
    for c in cells:
        sheet.paste(c, (x, 20), c)
        x += c.width + 30
    sheet.save(OUT_DIR / "icon_qa.png")
    print("done: icon.ico, icon.png, icon_qa.png")


if __name__ == "__main__":
    main()
