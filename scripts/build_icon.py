#!/usr/bin/env python3
"""Regenerate every AgentCut icon artifact from desktop/build/icon.svg.

The SVG is the single source of truth; everything else (ICO + PNG rasters + the
light/dark surface variants) is derived, so a designer can retune the mark once
and rebuild all sizes.

Run it (Pillow is injected ephemerally, project deps in pyproject.toml untouched):

    uv run --with pillow python scripts/build_icon.py

or, if the active interpreter already has Pillow:

    python scripts/build_icon.py

Rasterization happens in Chromium (Playwright python API when importable, else a
chromium / chrome-headless-shell binary from %LOCALAPPDATA%/ms-playwright, else
chrome/msedge on PATH). Vectors are rasterized on the exact target pixel grid,
which is why the 16px entry is a real 16px vector render and not a downscale.

Outputs
    desktop/build/icon.ico                  16/24/32/48/64/128 BMP + 256 PNG
    desktop/build/icons/<size>.png          16 24 32 48 64 128 256 512 1024
    desktop/build/icons/mark-512.png        flat-ink mark for the light in-app UI
    desktop/build/icons/mark-20.png         same mark at titlebar size
    desktop/build/icons/icon@dark.png       boosted rim/blue for dark surfaces
    desktop/build/icons/installer-256.png   full-bleed square, zero transparency

The script finishes by parsing its own output: ICONDIR table straight from bytes,
PNG dimensions, distinct-colour counts and an ASCII dump of the 16px render.
"""

from __future__ import annotations

import glob
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: run `uv run --with pillow python scripts/build_icon.py`")

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "desktop" / "build"
ICONS = BUILD / "icons"
MASTER_SVG = BUILD / "icon.svg"
ICO_PATH = BUILD / "icon.ico"

PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# >=256 is stored as PNG inside the ICO (Vista+); the rest as 32bpp BMP/DIB so
# GDI, NSIS wizard pages and old Explorer views can still read the entry.
PNG_IN_ICO = 256

FIELD_BOX = (120, 120, 784, 784)  # x, y, w, h of #field — used by the installer tile
ICONDIR_SIZE = 6  # reserved + type + count
ICO_ENTRY_SIZE = 16  # bWidth bHeight bColorCount bReserved wPlanes wBitCount dwBytes dwOffset

# --------------------------------------------------------------------------- #
# variants: colour overrides on one geometry (token -> replacement)
# --------------------------------------------------------------------------- #
VARIANTS: dict[str, dict[str, str]] = {
    # taskbar / alt-tab / installer: subtle gradient field + hairline rim so the
    # square never dissolves into a near-black Windows taskbar
    "master": {},
    # in-app brand mark on #f6f6f8 / #ffffff surfaces: mockup ink, no gradient,
    # no rim, single flat signal blue
    "mark": {
        "#34343e": "#1c1c21",
        "#17171d": "#1c1c1f",
        'stroke-opacity="0.34"': 'stroke-opacity="0"',
        "#3b6ce4": "#2b59d8",
    },
    # dark chrome (tray on dark taskbar, future dark theme header): lift the
    # field, strengthen the rim, brighten the playhead
    "dark": {
        "#34343e": "#454553",
        "#17171d": "#232330",
        'stroke-opacity="0.34"': 'stroke-opacity="0.55"',
        "#3b6ce4": "#6f95f8",
        "#2b59d8": "#3d6de6",
    },
}


def variant_svg(name: str) -> str:
    text = MASTER_SVG.read_text(encoding="utf-8")
    for token, replacement in VARIANTS[name].items():
        if token not in text:
            raise SystemExit(f"variant {name!r}: token {token!r} missing from {MASTER_SVG}")
        text = text.replace(token, replacement)
    return text


def tile_svg(text: str) -> str:
    """Full-bleed opaque square for installer / tile bitmaps: crop the viewBox to
    the field, square off its corners, paint the field behind everything so the
    clipped playhead has no transparent surround."""
    x, y, w, h = FIELD_BOX
    text = text.replace('viewBox="0 0 1024 1024"', f'viewBox="{x} {y} {w} {h}"', 1)
    text = text.replace(
        "<!-- timeline field -->",
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#fieldGrad)"/>'
        "\n  <!-- timeline field -->",
        1,
    )
    # #field itself goes square; the rim is dropped (it would trace a phantom inset)
    text = re.sub(r'(<rect id="field"[^>]*?)rx="\d+"', r'\1rx="0"', text, count=1)
    text = text.replace('stroke-opacity="0.34"', 'stroke-opacity="0"', 1)
    return text


# --------------------------------------------------------------------------- #
# rasterizer
# --------------------------------------------------------------------------- #
def page_for(svg_text: str, size: int) -> str:
    sized = svg_text.replace('width="1024" height="1024"', f'width="{size}" height="{size}"', 1)
    if f'height="{size}"' not in sized:
        raise SystemExit("could not re-size the master SVG (width/height attrs changed?)")
    return (
        "<!doctype html><meta charset=utf-8>"
        "<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden}"
        "svg{display:block}</style>" + sized
    )


def find_chromium() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", str(Path.home()))
    patterns = [
        Path(local) / "ms-playwright/chromium-*/chrome-*/chrome.exe",
        Path(local) / "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-win64/*.exe",
    ]
    for pat in patterns:
        hits = sorted(glob.glob(str(pat)))
        hits = [h for h in hits if Path(h).name in ("chrome.exe", "chrome-headless-shell.exe")]
        if hits:
            return Path(hits[-1])
    for exe in ("chromium", "chrome", "msedge"):
        found = shutil.which(exe)
        if found:
            return Path(found)
    return None


def rasterize(jobs: list[tuple[str, int, Path]]) -> str:
    """jobs = [(svg_text, size, out_path)] -> backend description."""
    chromium = find_chromium()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright = None  # type: ignore[assignment]

    if sync_playwright is not None:
        with sync_playwright() as pw:
            launch = dict(headless=True)
            if chromium and chromium.name != "chrome.exe":
                launch["executable_path"] = str(chromium)
            try:
                browser = pw.chromium.launch(**launch)
            except Exception:
                browser = pw.chromium.launch(executable_path=str(chromium), headless=True)
            for text, size, out in jobs:
                page = browser.new_page(
                    viewport={"width": size, "height": size}, device_scale_factor=1
                )
                page.set_content(page_for(text, size), wait_until="load")
                page.screenshot(path=str(out), omit_background=True)
                page.close()
            browser.close()
        return f"playwright(chromium) -> {chromium.name if chromium else 'bundled'}"

    if chromium is None:
        raise SystemExit("no Chromium/Playwright available to rasterize the SVG")

    backend = chromium.name
    with tempfile.TemporaryDirectory() as tmp:
        for text, size, out in jobs:
            html_path = Path(tmp) / f"r{size}.html"
            html_path.write_text(page_for(text, size), encoding="utf-8")
            cmd = [
                str(chromium),
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-sandbox",
                "--force-device-scale-factor=1",
                "--default-background-color=00000000",
                f"--window-size={size},{size}",
                f"--screenshot={out}",
                html_path.as_uri(),
            ]
            for headless in ("--headless=new", "--headless"):
                res = subprocess.run([cmd[0], headless, *cmd[1:]], capture_output=True, text=True)
                if res.returncode == 0 and out.exists():
                    break
            else:
                raise SystemExit(f"chromium screenshot failed for {size}px:\n{res.stderr[:400]}")
    return f"{backend} (headless CLI)"


# --------------------------------------------------------------------------- #
# ICO container (written by hand: full control over BMP vs PNG payloads)
# --------------------------------------------------------------------------- #
def dib_payload(img: Image.Image) -> bytes:
    """32bpp BI_RGB DIB: BITMAPINFOHEADER + bottom-up BGRA + 1bpp AND mask."""
    w, h = img.size
    rgba = img.convert("RGBA").tobytes()
    bgra = bytearray(len(rgba))
    bgra[0::4] = rgba[2::4]  # B
    bgra[1::4] = rgba[1::4]  # G
    bgra[2::4] = rgba[0::4]  # R
    bgra[3::4] = rgba[3::4]  # A
    rows = [bytes(bgra[y * w * 4 : (y + 1) * w * 4]) for y in range(h)]
    pixels = b"".join(reversed(rows))
    mask_row = ((w + 31) // 32) * 4
    mask = b"\x00" * mask_row * h  # AND mask all zero = source pixels win
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        w,
        h * 2,
        1,
        32,
        0,
        len(pixels) + len(mask),
        0,
        0,
        0,
        0,
    )
    return header + pixels + mask


def png_payload(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def build_ico(pngs: dict[int, Path], out: Path) -> None:
    entries: list[tuple[int, bytes]] = []
    for size in ICO_SIZES:
        img = Image.open(pngs[size])
        if img.size != (size, size):
            raise SystemExit(f"{pngs[size]} is {img.size}, expected {size}x{size}")
        payload = png_payload(img) if size >= PNG_IN_ICO else dib_payload(img)
        entries.append((size, payload))

    count = len(entries)
    directory = struct.pack("<HHH", 0, 1, count)
    offset = 6 + ICO_ENTRY_SIZE * count
    images, dir_bytes = bytearray(), bytearray()
    for size, payload in entries:
        dim = 0 if size >= 256 else size
        dir_bytes += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(payload), offset)
        images += payload
        offset += len(payload)
    out.write_bytes(directory + bytes(dir_bytes) + bytes(images))


# --------------------------------------------------------------------------- #
# verification
# --------------------------------------------------------------------------- #
def verify_ico(path: Path) -> None:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    print(f"\n== {path.relative_to(ROOT).as_posix()} — parsed ICONDIR ==")
    print(f"file size : {len(data):,} bytes")
    print(f"ICONDIR   : reserved={reserved} (must be 0) type={kind} (1=icon) count={count}")
    if (reserved, kind) != (0, 1):
        raise SystemExit("bad ICONDIR header")
    rows, offsets = [], []
    for i in range(count):
        entry = struct.unpack_from("<BBBBHHII", data, ICONDIR_SIZE + ICO_ENTRY_SIZE * i)
        w, h, ncolors, res, planes, bpp, size, off = entry
        px_w, px_h = (256 if w == 0 else w), (256 if h == 0 else h)
        payload = data[off : off + size]
        if payload[:8] == b"\x89PNG\r\n\x1a\n":
            fmt = f"PNG  {len(payload):,}B  idat-crc-ok={png_ok(payload)}"
        elif len(payload) >= 40 and struct.unpack_from("<I", payload, 0)[0] == 40:
            bi_w, bi_h, bi_p, bi_b, bi_c, bi_imgs = struct.unpack_from("<iiHHII", payload, 4)
            fmt = (
                f"BMP  {len(payload):,}B  dib={bi_w}x{bi_h}(planes {bi_p}, {bi_b}bpp, comp {bi_c})"
            )
            if bi_h != 2 * px_h:
                fmt += " !! biHeight != 2*h"
        else:
            fmt = "UNKNOWN PAYLOAD"
        rows.append((i + 1, px_w, px_h, bpp, planes, ncolors, res, size, off, fmt))
        offsets.append((off, off + size))
    print(
        f"{'#':>3} {'W':>5} {'H':>5} {'bpp':>4} {'pl':>3} {'ncol':>5} {'res':>4} "
        f"{'bytes':>9} {'offset':>8}  payload"
    )
    for r in rows:
        print(
            f"{r[0]:>3} {r[1]:>5} {r[2]:>5} {r[3]:>4} {r[4]:>3} {r[5]:>5} {r[6]:>4} "
            f"{r[7]:>9,} {r[8]:>8,}  {r[9]}"
        )
    contiguous, cursor = True, ICONDIR_SIZE + ICO_ENTRY_SIZE * count
    for start, end in sorted(offsets):
        if start != cursor:
            contiguous = False
        cursor = end
    print(
        f"checks    : sizes={sorted(x[1] for x in rows)} contiguous={contiguous} "
        f"no gaps/overlaps={len(set(offsets)) == len(offsets)} tail={cursor == len(data)}"
    )
    required = {16, 24, 32, 48, 64, 128, 256}
    have = {x[1] for x in rows}
    missing = required - have
    status = "ALL PRESENT" if not missing else "MISSING " + str(sorted(missing))
    print(f"required  : {sorted(required)} -> {status}")
    bad = (
        sorted(missing)
        + ([] if contiguous else ["entries not contiguous"])
        + ([] if len(set(offsets)) == len(offsets) else ["overlapping payloads"])
        + ([] if cursor == len(data) else ["trailing bytes"])
        + [f"entry {r[0]}: {r[9]}" for r in rows if "UNKNOWN" in r[9] or "!!" in r[9]]
    )
    if bad:
        raise SystemExit(f"icon.ico failed its own directory parse: {bad}")


def png_ok(blob: bytes) -> bool:
    import zlib

    pos, idat = 8, b""
    while pos + 8 <= len(blob):
        length, ctype = struct.unpack_from(">I4s", blob, pos)
        body = blob[pos + 8 : pos + 8 + length]
        crc = struct.unpack_from(">I", blob, pos + 8 + length)[0]
        if crc != zlib.crc32(ctype + body) & 0xFFFFFFFF:
            return False
        if ctype == b"IDAT":
            idat += body
        pos += 12 + length
        if ctype == b"IEND":
            break
    if idat:
        try:
            zlib.decompress(idat)
        except zlib.error:
            return False
    return True


def audit_png(path: Path) -> tuple[str, int, int]:
    img = Image.open(path)
    rgba = img.convert("RGBA")
    raw = rgba.tobytes()
    colors = rgba.getcolors(maxcolors=1 << 24) or []
    opaque = [(r, g, b, a) for _, (r, g, b, a) in colors if a > 8]
    rgb_distinct = len({(r, g, b) for r, g, b, _ in opaque})
    coverage = sum(1 for i in range(3, len(raw), 4) if raw[i] > 8) / (rgba.width * rgba.height)
    bbox = rgba.split()[3].getbbox()
    verdict = "OK"
    if len(colors) < 8 or rgb_distinct < 4:
        verdict = f"SOLID/BLANK ({len(colors)} rgba, {rgb_distinct} rgb)"
    if bbox and (bbox[2] - bbox[0]) < rgba.width * 0.5:
        verdict += " NARROW-BBOX"
    print(
        f"  {path.relative_to(ROOT).as_posix():<34} {img.size[0]:>4}x{img.size[1]:<4} "
        f"{img.mode:<4} rgba-colors={len(colors):>6}  rgb(opaque)={rgb_distinct:>4}  "
        f"alpha-coverage={coverage:5.1%}  bbox={bbox}  {verdict}"
    )
    return verdict, len(colors), rgb_distinct


def dump_image(img: Image.Image, size: int, title: str, gate: bool = True) -> None:
    """ASCII-render an icon at `size` and assert the three shape classes survived
    the trip to that pixel grid (no mush, no dropped playhead)."""
    img = img.convert("RGBA")
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    px = img.load()
    print(f"\n== {title} — {size}x{size}, each char = one device pixel ==")
    print(
        "  legend: '#' white play glyph   '|' signal-blue playhead   "
        "'+' mid seam / rim   '.' dark field   ' ' transparent"
    )
    colors = len(img.getcolors(maxcolors=1 << 24) or [])
    tally = {" ": 0, "|": 0, "#": 0, "+": 0, ".": 0}
    for y in range(size):
        line = []
        for x in range(size):
            r, g, b, a = px[x, y]
            if a < 40:
                ch = " "
            elif b > r + 40 and b > 110:
                ch = "|"
            elif (r + g + b) / 3 > 205:
                ch = "#"
            elif (r + g + b) / 3 > 120:
                ch = "+"
            else:
                ch = "."
            tally[ch] += 1
            line.append(ch)
        print("  " + "".join(line))
    lum = sorted(set(img.convert("L").tobytes()))
    total = size * size
    print(
        f"  distinct RGBA values: {colors}   luminance steps: {len(lum)}   "
        + "  ".join(f"{k!r}={v}({v / total:.1%})" for k, v in tally.items())
    )
    if gate:
        weak = [
            f"{k!r} covers {tally[k] / total:.1%} (need >= {need:.0%})"
            for k, need in (("#", 0.03), ("|", 0.04), (".", 0.25))
            if tally[k] / total < need
        ]
        if colors < 40 or weak:
            raise SystemExit(
                f"{title} is not legible at {size}px: distinct RGBA={colors}"
                + "".join(f"; {w}" for w in weak)
            )


def ascii_dump(path: Path, size: int = 16, title: str | None = None) -> None:
    dump_image(Image.open(path), size, title or path.name)


def dib_to_image(payload: bytes) -> Image.Image:
    """Decode a 32bpp BI_RGB DIB icon entry (bottom-up BGRA + 1bpp AND mask)."""
    bi_size, w, bi_h, planes, bpp, comp = struct.unpack_from("<IiiHHI", payload, 0)
    if (bi_size, planes, bpp, comp) != (40, 1, 32, 0):
        raise SystemExit(f"unexpected DIB header: {bi_size} {planes} {bpp} {comp}")
    h = abs(bi_h) // 2
    body = payload[40 : 40 + w * h * 4]
    # ystep=-1: the DIB stores rows bottom-up; raw decoder "BGRA" swaps to RGBA
    return Image.frombytes("RGBA", (w, h), body, "raw", "BGRA", 0, -1)


def ico_roundtrip(path: Path, pngs: dict[int, Path]) -> None:
    """Independent decode: Pillow's own ICO reader plus my manual DIB decoder,
    compared pixel-for-pixel against the source PNGs."""
    mismatches: list[str] = []
    with Image.open(path) as ico:
        sizes = sorted(ico.ico.sizes())
        print(f"\nPillow ICO reader: formats={ico.format} sizes={sizes}")
        for size in sizes:
            sub = ico.ico.getimage(size).convert("RGBA")
            src = Image.open(pngs[size[0]]).convert("RGBA")
            same = sub.tobytes() == src.tobytes()
            print(
                f"  getimage({size[0]:>3}x{size[1]}) -> {sub.size} colors="
                f"{len(sub.getcolors(maxcolors=1 << 24) or []):>5}  "
                f"identical to {size[0]}.png: {same}"
            )
            if not same:
                mismatches.append(f"pillow {size[0]}px")
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    for i in range(count):
        w, h = data[6 + 16 * i], data[7 + 16 * i]
        size = 256 if w == 0 else w
        if h != w:
            raise SystemExit(f"entry #{i + 1} is not square: {w}x{h}")
        nbytes, off = struct.unpack_from("<II", data, 6 + 16 * i + 8)
        payload = data[off : off + nbytes]
        if payload[:8] == b"\x89PNG\r\n\x1a\n":
            dec = Image.open(io.BytesIO(payload)).convert("RGBA")
            kind = "PNG entry"
        else:
            dec = dib_to_image(payload)
            kind = "BMP entry"
        src = Image.open(pngs[size]).convert("RGBA")
        same = dec.tobytes() == src.tobytes()
        print(
            f"  manual #{i + 1} {size:>3}px {kind}: decoded={dec.size} "
            f"bytes={nbytes:,} matches source PNG={same}"
        )
        if not same or dec.size != (size, size):
            mismatches.append(f"manual {size}px {kind}")
    if mismatches:
        raise SystemExit(f"icon.ico entries do not round-trip: {mismatches}")


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    masters = {name: variant_svg(name) for name in VARIANTS}
    masters["tile"] = tile_svg(variant_svg("master"))

    jobs: list[tuple[str, int, Path]] = []
    for size in PNG_SIZES:
        jobs.append((masters["master"], size, ICONS / f"{size}.png"))
    jobs.append((masters["mark"], 512, ICONS / "mark-512.png"))
    jobs.append((masters["mark"], 20, ICONS / "mark-20.png"))  # titlebar reference
    jobs.append((masters["dark"], 512, ICONS / "icon@dark.png"))
    jobs.append((masters["tile"], 256, ICONS / "installer-256.png"))

    backend = rasterize(jobs)

    pngs = {size: ICONS / f"{size}.png" for size in ICO_SIZES}
    build_ico(pngs, ICO_PATH)

    print("regenerate   : uv run --with pillow python scripts/build_icon.py")
    print(f"rasterizer   : {backend}")
    print(f"source svg   : {MASTER_SVG.relative_to(ROOT).as_posix()}")
    print("\n== artifacts ==")
    for f in [MASTER_SVG, ICO_PATH, *sorted(ICONS.iterdir())]:
        if f.exists():
            print(f"  {f.relative_to(ROOT).as_posix():<40} {f.stat().st_size:>9,} bytes")

    print("\n== PNG audit (dimensions + non-blank check) ==")
    blank = [f.name for f in sorted(ICONS.glob("*.png")) if not audit_png(f)[0].startswith("OK")]
    if blank:
        raise SystemExit(f"blank/solid rasters produced: {blank}")

    verify_ico(ICO_PATH)
    ico_roundtrip(ICO_PATH, pngs)
    ascii_dump(ICONS / "16.png", 16)
    with Image.open(ICO_PATH) as ico:
        dump_image(ico.ico.getimage((16, 16)), 16, "icon.ico entry #1 decoded by Pillow")
    ascii_dump(ICONS / "24.png", 24)
    ascii_dump(ICONS / "32.png", 32)
    ascii_dump(ICONS / "mark-20.png", 20, "mark-20.png (in-app titlebar size)")
    print("\nALL CHECKS PASSED — icon.ico and every PNG are structurally and visually sound.")


if __name__ == "__main__":
    sys.exit(main())
