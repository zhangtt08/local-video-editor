"""One normalized geometry, native SVG and FFmpeg alpha outputs; its box can be keyframed.

Rectangle and ellipse masks compile to a `geq` alpha expression and to SVG gradients, and their
center and size accept keyframes: the exporter gets frame-time expressions, the browser scales one
unit image with the same curve. A free-form path cannot be tested edge by edge for every pixel of
every frame, so the same vertex list is rasterised once into a grayscale PNG (even-odd scanline
coverage plus a separable Gaussian for the feather) and merged into the layer alpha by FFmpeg. The
browser receives the identical geometry as an SVG path with the same Gaussian radius in isotropic
units.
"""

from math import ceil, cos, radians, sin, sqrt
from struct import pack
from urllib.parse import quote
from zlib import compress as zlib_compress
from zlib import crc32

from .contracts import MASK_FIELDS, ShapeMask

RASTER_WIDTH = 512
SUB_ROWS = 4
FLATNESS = 0.2
FEATHER_FACTOR = 0.25
MAX_SIGMA = 8.0


def alpha_expression(
    mask: ShapeMask,
    values: dict[str, str] | None = None,
    box: tuple[float, float, float, float] | None = None,
) -> str:
    """Alpha of one pixel. `values` may replace the geometry with FFmpeg expressions of frame time.

    The ramp is measured inward from the box edge in box units, the same normalization the browser's
    unit mask image uses, so keyframed geometry stays one formula on both sides.

    `box` is the picture box — `(offset_x, offset_y, width, height)` in the pixels the
    expression is evaluated over. Mask coordinates are fractions of the picture the user
    drew on, never of a padded delivery frame: with `contain` into a taller aspect, `X/W`
    alone would stretch the shape and slide it out of the picture, which is what 1.102
    fixes. `None` (or a frame that the picture fills) keeps
    the 1.45-era `X/W`, byte for byte.
    """
    if mask.shape == "path":
        return ""
    taken = {name: str(getattr(mask, field)) for name, field in MASK_FIELDS.items()}
    taken.update(values or {})
    nx = f"((X-{box[0]:.4f})/{box[2]:.4f})" if box else "X/W"
    ny = f"((Y-{box[1]:.4f})/{box[3]:.4f})" if box else "Y/H"
    if mask.rotation:
        # The box's two fractions are measured against different edge lengths, so an angle is only
        # honest after the offset is in one unit: `k` is picture height over picture width, the very
        # factor the browser stretches its image by. Turning the *sample point* back by the mask's
        # angle is how a shape drawn rotated answers for the pixel standing where it stands.
        dx = f"(({nx})-({taken['mask_x']}))"
        dy = f"(({ny})-({taken['mask_y']}))"
        theta = radians(mask.rotation)
        cos_t, sin_t = f"{cos(theta):.9f}", f"{sin(theta):.9f}"
        k = f"{box[3] / box[2]:.9f}" if box else "(H/W)"
        rx = f"({dx}*{cos_t}+{dy}*{k}*{sin_t})"
        ry = f"({dy}*{k}*{cos_t}-{dx}*{sin_t})"
        x = f"abs({rx}*2/({taken['mask_width']}))"
        y = f"abs({ry}/{k}*2/({taken['mask_height']}))"
    else:
        x = f"abs(({nx}-({taken['mask_x']}))*2/({taken['mask_width']}))"
        y = f"abs(({ny}-({taken['mask_y']}))*2/({taken['mask_height']}))"
    if mask.shape == "ellipse":
        radius = f"sqrt(pow({x},2)+pow({y},2))"
        value = f"clip((1-{radius})/{mask.feather},0,1)" if mask.feather else f"lte({radius},1)"
    elif mask.feather:
        value = f"clip((1-{x})/{mask.feather},0,1)*clip((1-{y})/{mask.feather},0,1)"
    else:
        value = f"lte({x},1)*lte({y},1)"
    return f"(1-({value}))" if mask.inverted else value


def svg_image(mask: ShapeMask) -> str:
    """Luminance gradients implement the same inward linear feather as the alpha expression."""
    x = (mask.center_x - mask.width / 2) * 100
    y = (mask.center_y - mask.height / 2) * 100
    w, h = mask.width * 100, mask.height * 100
    box = f'x="{x}" y="{y}" width="{w}" height="{h}"'
    full = 'x="0" y="0" width="100" height="100"'
    outer, inner = ("white", "black") if mask.inverted else ("black", "white")
    defs, paint = "", ""
    if mask.shape == "ellipse":
        if mask.feather:
            defs = (
                '<radialGradient id="fade"><stop offset="0" stop-color="white"/>'
                f'<stop offset="{1 - mask.feather}" stop-color="white"/>'
                '<stop offset="1" stop-color="black"/></radialGradient>'
                f'<mask id="shape" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
                f'<rect {box} fill="url(#fade)"/></mask>'
            )
            paint = f'<rect {full} fill="{inner}" mask="url(#shape)"/>'
        else:
            paint = (
                f'<ellipse cx="{mask.center_x * 100}" cy="{mask.center_y * 100}" '
                f'rx="{w / 2}" ry="{h / 2}" fill="{inner}"/>'
            )
    elif mask.feather:
        stops = (
            '<stop offset="0" stop-color="black"/>'
            f'<stop offset="{mask.feather / 2}" stop-color="white"/>'
            f'<stop offset="{1 - mask.feather / 2}" stop-color="white"/>'
            '<stop offset="1" stop-color="black"/>'
        )
        defs = (
            f'<linearGradient id="fx" x1="0" x2="1">{stops}</linearGradient>'
            f'<linearGradient id="fy" x1="0" y1="0" x2="0" y2="1">{stops}</linearGradient>'
            f'<mask id="axis" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
            f'<rect {box} fill="url(#fx)"/></mask>'
            f'<mask id="shape" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
            f'<rect {box} fill="url(#fy)" mask="url(#axis)"/></mask>'
        )
        paint = f'<rect {full} fill="{inner}" mask="url(#shape)"/>'
    else:
        paint = f'<rect {box} fill="{inner}"/>'
    document = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
        'preserveAspectRatio="none"><defs>' + defs + "</defs>"
        f'<mask id="result" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
        f'<rect {full} fill="{outer}"/>{paint}</mask>'
        f'<rect {full} fill="white" mask="url(#result)"/></svg>'
    )
    return 'url("data:image/svg+xml,' + quote(document, safe="") + '")'


def cover_svg_image(mask, frame_width: int, frame_height: int) -> str:
    """One rotated box on a canvas with the picture's own aspect, spanning the whole picture.

    `svg_image` builds a unit box the browser stretches into whatever rectangle the mask occupies,
    which is exactly right for geometry measured in box fractions and exactly wrong for an angle:
    a non-uniform stretch turns 45° into whatever it lands on (measured). Here the canvas is
    isotropic with the picture, so `mask-size: 100% 100%` scales it uniformly, the angle stays the
    angle a person set, and the browser has only one job left - translate this one image by the same
    centre curves the alpha expression reads. The feather ramps stay in box units, as everywhere.
    """
    unit = 1000.0
    tall = unit * frame_height / frame_width
    cx, cy = mask.center_x * unit, mask.center_y * tall
    full = f'x="0" y="0" width="{unit:.4f}" height="{tall:.4f}"'
    turn = f' transform="rotate({mask.rotation:.6f} {cx:.4f} {cy:.4f})"'
    box = (
        f'x="{cx - mask.width * unit / 2:.4f}" y="{cy - mask.height * tall / 2:.4f}" '
        f'width="{mask.width * unit:.4f}" height="{mask.height * tall:.4f}"'
    )
    outer, inner = ("white", "black") if mask.inverted else ("black", "white")
    defs, paint = "", ""
    if mask.shape == "ellipse":
        if mask.feather:
            defs = (
                '<radialGradient id="fade"><stop offset="0" stop-color="white"/>'
                f'<stop offset="{1 - mask.feather}" stop-color="white"/>'
                '<stop offset="1" stop-color="black"/></radialGradient>'
                f'<mask id="shape" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
                f'<g{turn}><rect {box} fill="url(#fade)"/></g></mask>'
            )
            paint = f'<rect {full} fill="{inner}" mask="url(#shape)"/>'
        else:
            paint = (
                f'<ellipse cx="{cx:.4f}" cy="{cy:.4f}" rx="{mask.width * unit / 2:.4f}" '
                f'ry="{mask.height * tall / 2:.4f}" fill="{inner}"{turn}/>'
            )
    elif mask.feather:
        stops = (
            '<stop offset="0" stop-color="black"/>'
            f'<stop offset="{mask.feather / 2}" stop-color="white"/>'
            f'<stop offset="{1 - mask.feather / 2}" stop-color="white"/>'
            '<stop offset="1" stop-color="black"/>'
        )
        defs = (
            f'<linearGradient id="fx" x1="0" x2="1">{stops}</linearGradient>'
            f'<linearGradient id="fy" x1="0" y1="0" x2="0" y2="1">{stops}</linearGradient>'
            f'<mask id="axis" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
            f'<g{turn}><rect {box} fill="url(#fx)"/></g></mask>'
            f'<mask id="shape" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
            f'<g{turn}><rect {box} fill="url(#fy)" mask="url(#axis)"/></g></mask>'
        )
        paint = f'<rect {full} fill="{inner}" mask="url(#shape)"/>'
    else:
        paint = f'<rect {box} fill="{inner}"{turn}/>'
    document = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {unit:.4f} {tall:.4f}" preserveAspectRatio="none"><defs>' + defs + "</defs>"
        f'<mask id="result" maskUnits="userSpaceOnUse" {full} mask-type="luminance">'
        f'<rect {full} fill="{outer}"/>{paint}</mask>'
        f'<rect {full} fill="white" mask="url(#result)"/></svg>'
    )
    return 'url("data:image/svg+xml,' + quote(document, safe="") + '")'


def animated_mask_image(mask, width: int, height: int) -> str:
    """The same geometry with its box filling the frame, for the browser to scale and move.

    The ramp is defined relative to the box in both the SVG and the FFmpeg expression, so one unit
    image serves every keyframed size; the outside of a non-inverted mask is transparent, which is
    exactly what the alpha expression gives past the box edge. A free-form mask's unit image is its
    outline stretched over the box, which is the same one raster the exporter overlays.
    """
    if mask.shape == "path":
        return path_svg_image(unit_path(mask), *raster_size(width, height))
    if mask.rotation:
        # Drawn at the canvas centre with its real proportions: the browser's own translation by
        # `mask_x/mask_y` is then the same move the exporter makes inside the alpha expression.
        return cover_svg_image(
            mask.model_copy(update={"center_x": 0.5, "center_y": 0.5}), width, height
        )
    unit = mask.model_copy(update={"center_x": 0.5, "center_y": 0.5, "width": 1.0, "height": 1.0})
    return svg_image(unit)


def mask_image(mask, frame_width: int, frame_height: int) -> str:
    """One entry point: a path needs the frame size to keep its raster isotropic.

    A static path is drawn exactly where its outline was — the box fields are only the editor's
    handle — while a keyframed one is previewed through `animated_mask_image`, which the browser
    moves with the same curves the exporter's overlay reads.
    """
    if mask.shape == "path":
        return path_svg_image(mask, *raster_size(frame_width, frame_height))
    if mask.rotation:
        return cover_svg_image(mask, frame_width, frame_height)
    return svg_image(mask)


def feather_sigma(width: int, height: int, feather: float) -> float:
    """Gaussian radius in raster pixels; the browser uses the same radius in isotropic units."""
    return feather * FEATHER_FACTOR * min(width, height)


def raster_size(frame_width: int, frame_height: int) -> tuple[int, int]:
    width = min(RASTER_WIDTH, max(16, frame_width))
    height = max(16, round(width * frame_height / frame_width))
    return width, height


def path_bounds(mask) -> tuple[float, float, float, float]:
    """The polygon's own box in picture coordinates, taken from its flattened outline.

    Handles bulge the shape past its nodes, so the bounds come from the flattened curve rather than
    from the vertex list alone — otherwise a curved corner would be clipped by its own box.
    """
    outline = _segments(mask, 1.0, 1.0)
    xs = [point[0] for point in outline]
    ys = [point[1] for point in outline]
    return min(xs), min(ys), max(xs), max(ys)


def unit_path(mask, fill_x: float = 1.0, fill_y: float = 1.0):
    """A copy whose outline fills the unit square, so the box fields can place it.

    The exporter scales this one raster and the browser scales this one SVG image; a free-form mask
    therefore moves with the same `mask_x/mask_y` curves a rectangle already uses, instead of
    needing a raster per frame. `fill` shrinks the outline to that fraction of the raster and keeps
    it centred, which is how the exporter leaves room for a feather outside the shape's own bounds.
    """
    left, top, right, bottom = path_bounds(mask)
    width = max(right - left, 1e-6)
    height = max(bottom - top, 1e-6)
    vertices = [
        vertex.model_copy(
            update={
                "x": (vertex.x - left) / width * fill_x + (1 - fill_x) / 2,
                "y": (vertex.y - top) / height * fill_y + (1 - fill_y) / 2,
                "handle_out": [
                    vertex.handle_out[0] / width * fill_x,
                    vertex.handle_out[1] / height * fill_y,
                ],
                "handle_in": [
                    vertex.handle_in[0] / width * fill_x,
                    vertex.handle_in[1] / height * fill_y,
                ],
            }
        )
        for vertex in (mask.vertices or [])
    ]
    return mask.model_copy(
        update={
            "vertices": vertices,
            "center_x": 0.5,
            "center_y": 0.5,
            "width": fill_x,
            "height": fill_y,
        }
    )


def fit_box(mask):
    """A copy whose box is the outline's own bounds.

    A stored path mask has to sit exactly where it was drawn before any of this was possible, so the
    box starts life as the outline's bounds: mapping the unit outline back onto that box is the
    identity, and every later change to the box is a deliberate move.
    """
    left, top, right, bottom = path_bounds(mask)
    return mask.model_copy(
        update={
            "center_x": min(1.0, max(0.0, (left + right) / 2)),
            "center_y": min(1.0, max(0.0, (top + bottom) / 2)),
            "width": min(2.0, max(0.01, right - left)),
            "height": min(2.0, max(0.01, bottom - top)),
        }
    )


def box_of(mask) -> tuple[float, float, float, float]:
    """Where the mask sits, as left/top/right/bottom in picture coordinates."""
    return (
        mask.center_x - mask.width / 2,
        mask.center_y - mask.height / 2,
        mask.center_x + mask.width / 2,
        mask.center_y + mask.height / 2,
    )


def _segments(mask, width: int, height: int) -> list[tuple[float, float]]:
    """Closed outline flattened to points in raster pixel coordinates."""
    nodes = [(vertex.x * width, vertex.y * height) for vertex in mask.vertices]
    handles = [
        (
            (vertex.handle_out[0] * width, vertex.handle_out[1] * height),
            (vertex.handle_in[0] * width, vertex.handle_in[1] * height),
        )
        for vertex in mask.vertices
    ]
    outline: list[tuple[float, float]] = []
    for index in range(len(nodes)):
        start = nodes[index]
        end = nodes[(index + 1) % len(nodes)]
        leaving = handles[index][0]
        entering = handles[(index + 1) % len(nodes)][1]
        outline.append(start)
        if leaving == (0.0, 0.0) and entering == (0.0, 0.0):
            continue
        first = (start[0] + leaving[0], start[1] + leaving[1])
        second = (end[0] + entering[0], end[1] + entering[1])
        outline.extend(_cubic(start, first, second, end))
    return outline


def _cubic(start, first, second, end) -> list[tuple[float, float]]:
    """Subdivide until the chord error drops below FLATNESS pixels; the start point is excluded."""
    limit = FLATNESS + sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) * 0.02
    output: list[tuple[float, float]] = []
    stack: list[tuple[list, int]] = [([start, first, second, end], 0)]
    while stack:
        control, depth = stack.pop()
        p0, p1, p2, p3 = control
        d1x, d1y = 3 * p0[0] - 6 * p1[0] + 3 * p2[0], 3 * p0[1] - 6 * p1[1] + 3 * p2[1]
        d2x, d2y = 3 * p1[0] - 6 * p2[0] + 3 * p3[0], 3 * p1[1] - 6 * p2[1] + 3 * p3[1]
        error = max(abs(d1x - d2x), abs(d1y - d2y)) / 8
        if error <= limit or depth > 12:
            output.append(p3)
            continue
        stack.append((_split(p0, p1, p2, p3, False), depth + 1))
        stack.append((_split(p0, p1, p2, p3, True), depth + 1))
    return output


def _split(p0, p1, p2, p3, left: bool):
    a = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    b = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    c = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
    d = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    e = ((b[0] + c[0]) / 2, (b[1] + c[1]) / 2)
    f = ((d[0] + e[0]) / 2, (d[1] + e[1]) / 2)
    return [p0, a, d, f] if left else [f, e, c, p3]


def coverage(mask, width: int, height: int) -> bytearray:
    """Even-odd scanline coverage in 0..255, antialiased by sub-rows and edge fractions."""
    outline = _segments(mask, width, height)
    edges = []
    for index in range(len(outline)):
        left = outline[index]
        right = outline[(index + 1) % len(outline)]
        if left[1] != right[1]:
            edges.append((min(left[1], right[1]), max(left[1], right[1]), left, right))
    weight = 1 / SUB_ROWS
    values = bytearray(width * height)
    for y in range(height):
        row = [0.0] * width
        for step in range(SUB_ROWS):
            sample = y + (step + 0.5) * weight
            crossings = []
            for low, high, left, right in edges:
                if low <= sample < high:
                    ratio = (sample - left[1]) / (right[1] - left[1])
                    crossings.append(left[0] + ratio * (right[0] - left[0]))
            crossings.sort()
            for index in range(0, len(crossings) - 1, 2):
                _span(row, crossings[index], crossings[index + 1], weight, width)
        offset = y * width
        for x in range(width):
            values[offset + x] = min(255, int(row[x] * 255 + 0.5))
    return values


def _span(row, low: float, high: float, weight: float, width: int) -> None:
    first = max(0, int(low))
    last = min(width - 1, int(high))
    for x in range(first, last + 1):
        left = max(low, x)
        right = min(high, x + 1)
        if right > left:
            row[x] += (right - left) * weight


def _blur(values: bytearray, width: int, height: int, sigma: float) -> bytearray:
    radius = max(1, ceil(sigma * 3))
    kernel = [
        pow(2.718281828459045, -(step * step) / (2 * sigma * sigma)) for step in range(radius + 1)
    ]
    total = sum(kernel) * 2 - kernel[0]
    kernel = [value / total for value in kernel]
    source = [value / 255 for value in values]
    horizontal = [0.0] * len(source)
    for y in range(height):
        offset = y * width
        for x in range(width):
            acc = source[offset + x] * kernel[0]
            for step in range(1, radius + 1):
                left = x - step if x - step >= 0 else 0
                right = x + step if x + step < width else width - 1
                acc += (source[offset + left] + source[offset + right]) * kernel[step]
            horizontal[offset + x] = acc
    result = bytearray(len(source))
    for x in range(width):
        for y in range(height):
            acc = horizontal[y * width + x] * kernel[0]
            for step in range(1, radius + 1):
                up = y - step if y - step >= 0 else 0
                down = y + step if y + step < height else height - 1
                acc += (horizontal[up * width + x] + horizontal[down * width + x]) * kernel[step]
            result[y * width + x] = min(255, int(round(acc * 255)))
    return result


def mask_png(mask, width: int, height: int) -> bytes:
    """Grayscale PNG of the path coverage; FFmpeg merges it into the layer alpha.

    A wide feather is blurred on a proportionally smaller grid instead of a huge kernel: the
    raster is already isotropic with the frame, so the caller's `scale2ref` upsample restores it.
    """
    sigma = feather_sigma(width, height, mask.feather)
    out_w, out_h = width, height
    values = coverage(mask, width, height)
    if sigma > 0.05:
        step = max(1.0, sigma / MAX_SIGMA)
        if step > 1.0:
            out_w = max(32, int(width / step))
            out_h = max(18, int(height / step))
            values = coverage(mask, out_w, out_h)
            sigma /= step
        values = _blur(values, out_w, out_h, sigma)
    if mask.inverted:
        values = bytearray(255 - value for value in values)
    return _png(out_w, out_h, values)


def _png(width: int, height: int, values: bytearray) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return pack(">I", len(body)) + tag + body + pack(">I", crc32(tag + body) & 0xFFFFFFFF)

    header = pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(values[y * width : (y + 1) * width]) for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib_compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def path_svg_image(mask, width: int, height: int) -> str:
    """Browser mask for a path raster: identical geometry and Gaussian radius in isotropic units."""
    scale = 1000 / width
    outline = _segments(mask, width, height)
    sigma = feather_sigma(width, height, mask.feather) * scale
    inside = "black" if mask.inverted else "white"
    outside = "white" if mask.inverted else "black"
    box_width = 1000.0
    box_height = height * scale
    blur = ' filter="url(#soft)"' if sigma > 0.05 else ""
    defs = (
        '<filter id="soft" x="-50%" y="-50%" width="200%" height="200%" '
        f'filterUnits="userSpaceOnUse"><feGaussianBlur stdDeviation="{sigma:.4f}"/></filter>'
    )
    steps = [f"M {outline[0][0] * scale:.4f} {outline[0][1] * scale:.4f}"]
    steps.extend(f"L {point[0] * scale:.4f} {point[1] * scale:.4f}" for point in outline[1:])
    steps.append("Z")
    document = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {box_width:.4f} {box_height:.4f}" preserveAspectRatio="none">'
        f"<defs>{defs}</defs>"
        f'<rect x="0" y="0" width="{box_width:.4f}" height="{box_height:.4f}" fill="{outside}"/>'
        f'<path d="{" ".join(steps)}" fill="{inside}"{blur}/></svg>'
    )
    return 'url("data:image/svg+xml,' + quote(document, safe="") + '")'
