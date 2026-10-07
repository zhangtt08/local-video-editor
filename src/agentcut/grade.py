"""Serial grade nodes: one per-channel polyline is the authority for FFmpeg and the browser LUT.

Every node is a per-channel function, so a whole chain collapses to one transfer table. The FFmpeg
``lutrgb`` expression and the browser ``feComponentTransfer`` table are both sampled from the same
simplified polyline, which keeps native preview and render identical rather than merely similar.
"""

import hashlib

KNOT_GRID = 64
KNOT_BUDGET = 256
HALF_LEVEL = 0.5 / 255
MAX_SPAN = 48.0
TOLERANCE = 0.05
CHANNEL_NAMES = ("r", "g", "b")
CURVE_CHANNELS = {"red": 0, "green": 1, "blue": 2}
BALANCE = (0.30, 0.20, 0.10)


def _clamp(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def _piecewise(pairs):
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]

    def mapping(value: float) -> float:
        if value <= xs[0]:
            return ys[0]
        if value >= xs[-1]:
            return ys[-1]
        for index in range(len(xs) - 1):
            if value <= xs[index + 1]:
                span = xs[index + 1] - xs[index]
                return ys[index] + (value - xs[index]) * (ys[index + 1] - ys[index]) / span
        return ys[-1]

    return mapping


# Transfer functions, in the 0..1 display-referred domain the whole chain works in.
GAMMA_BY_SPACE = {"gamma18": 1.8, "gamma20": 2.0, "gamma22": 2.2, "gamma24": 2.4, "rec709": 2.4}
SRGB_TURN = 0.04045
SRGB_SLOPE = 12.92
SRGB_OFFSET = 0.055
LINEAR_TURN = 0.0031308


def to_linear(space: str, value: float) -> float:
    """Scene-linear light for one display-referred sample."""
    if space == "linear":
        return value
    if space == "srgb":
        if value <= SRGB_TURN:
            return value / SRGB_SLOPE
        return ((value + SRGB_OFFSET) / (1 + SRGB_OFFSET)) ** 2.4
    return value ** GAMMA_BY_SPACE[space]


def from_linear(space: str, value: float) -> float:
    """Inverse of `to_linear`, so a round trip is the identity by construction."""
    if space == "linear":
        return value
    if space == "srgb":
        return (
            SRGB_SLOPE * value
            if value <= LINEAR_TURN
            else (1 + SRGB_OFFSET) * value ** (1 / 2.4) - SRGB_OFFSET
        )
    return value ** (1 / GAMMA_BY_SPACE[space])


# Separable blend functions, the same eight the W3C compositing spec and FFmpeg's `blend` filter
# define, applied to one channel of the node's own input against the node's output. A track blend
# mixes two pictures; a node blend mixes a value with its own transform, which is why the chain
# stays a per-channel function and both renderers keep reading one table.
def _multiply(backdrop: float, picture: float) -> float:
    return backdrop * picture


def _screen(backdrop: float, picture: float) -> float:
    return backdrop + picture - backdrop * picture


def _overlay(backdrop: float, picture: float) -> float:
    if backdrop <= 0.5:
        return 2.0 * backdrop * picture
    return 1.0 - 2.0 * (1.0 - backdrop) * (1.0 - picture)


def _darken(backdrop: float, picture: float) -> float:
    return min(backdrop, picture)


def _lighten(backdrop: float, picture: float) -> float:
    return max(backdrop, picture)


def _difference(backdrop: float, picture: float) -> float:
    return abs(backdrop - picture)


def _exclusion(backdrop: float, picture: float) -> float:
    return backdrop + picture - 2.0 * backdrop * picture


BLEND_FUNCTIONS = {
    "multiply": _multiply,
    "screen": _screen,
    "overlay": _overlay,
    "darken": _darken,
    "lighten": _lighten,
    "difference": _difference,
    "exclusion": _exclusion,
}


def blend_values(mode: str, backdrop: float, picture: float) -> float:
    """One channel of `picture` blended onto `backdrop`; `normal` returns the picture untouched."""
    if mode == "normal":
        return picture
    return BLEND_FUNCTIONS[mode](backdrop, picture)


def lut_function(table):
    """Linearly interpolated lookup for one imported 1D LUT channel, on the 0..1 domain.

    The grid is even at `1/(n-1)` — the `.cube` 1D layout has no per-sample positions — so the
    mapping is the same piecewise shape the curve nodes compile, and the chain composes it like any
    other node.
    """
    count = len(table)
    step = 1 / (count - 1)

    def lookup(value: float) -> float:
        if value <= 0:
            return _clamp(table[0])
        if value >= 1:
            return _clamp(table[-1])
        position = value / step
        index = int(position)
        if index >= count - 1:
            return _clamp(table[-1])
        fraction = position - index
        return _clamp(table[index] + fraction * (table[index + 1] - table[index]))

    return lookup


def _op_function(node, index: int):
    """Per-channel mapping of one operation, or None when it leaves this channel untouched."""
    if node.kind == "curve":
        if node.channel != "rgb" and CURVE_CHANNELS[node.channel] != index:
            return None
        return _piecewise([(point.x, point.y) for point in node.points])
    if node.kind == "lut":
        return lut_function(node.channels[index])
    if node.kind == "transfer":
        source, target = node.input_space, node.output_space

        def transfer(value: float) -> float:
            return _clamp(from_linear(target, to_linear(source, _clamp(value))))

        return transfer
    if node.kind == "white_balance":
        warm, green, shift = BALANCE
        factors = (
            1 + warm * node.temperature + shift * node.tint,
            1 - green * node.tint,
            1 - warm * node.temperature + shift * node.tint,
        )
        factor = factors[index]
        return lambda value, factor=factor: _clamp(value * factor)
    gamma, gain, lift = node.gamma[index], node.gain[index], node.lift[index]
    if (gamma, gain, lift) == (1.0, 1.0, 0.0):
        return None

    def wheels(value: float) -> float:
        return _clamp((max(value, 0.0) ** (1 / gamma)) * gain + lift)

    return wheels


def step_function(node, index: int):
    """One node with its own strength and blend applied to the value entering it.

    Branch objects reach here from `node_function`, and the contract keeps a branch a single
    operation, so there is no recursion beyond one level.
    """
    mapping = node_function(node, index)
    if mapping is None:
        return None
    strength = node.mix
    mode = getattr(node, "blend", "normal")
    return lambda value, inner=mapping, strength=strength, mode=mode: (
        value + strength * (blend_values(mode, value, inner(value)) - value)
    )


def node_function(node, index: int):
    """Per-channel mapping of one node, or None when the node leaves this channel untouched.

    A parallel node outputs the mean of its branch results. A bypassed branch — or one that does
    not touch this channel at all — contributes its input, so disabling a branch fades the average
    toward the remaining branches instead of renumbering them.
    """
    if node.kind != "parallel":
        return _op_function(node, index)
    steps = [
        None if not branch.enabled else step_function(branch, index) for branch in node.branches
    ]
    if not any(steps):
        return None
    count = len(steps)

    def average(value: float) -> float:
        return sum(step(value) if step is not None else value for step in steps) / count

    return average


def _curve_knots(node, index: int):
    """Input positions where a node (or one of its branches) actually bends this channel."""
    operations = node.branches if node.kind == "parallel" else [node]
    for operation in operations:
        if operation.kind == "curve":
            if operation.channel != "rgb" and CURVE_CHANNELS[operation.channel] != index:
                continue
            yield from (point.x for point in operation.points)
        elif operation.kind == "lut":
            count = operation.size
            yield from (step / (count - 1) for step in range(count))


def _channel_points(nodes, index: int) -> list[tuple[float, float]] | None:
    """Composed transfer curve sampled on the component axis, in 0..255 units."""
    mappings = []
    extra = set()
    for node in nodes:
        if not node.enabled or not node.mix:
            continue
        step = step_function(node, index)
        if step is not None:
            mappings.append(step)
        extra.update(_curve_knots(node, index))
    if not mappings:
        return None

    def composed(value: float) -> float:
        for mapping in mappings:
            value = mapping(value)
        return _clamp(value)

    axis = sorted({step / KNOT_GRID for step in range(KNOT_GRID + 1)} | extra)
    return _simplify(_refine(axis, composed))


def _refine(axis, composed, tolerance=HALF_LEVEL, budget=KNOT_BUDGET):
    """Sample the composed function where it actually bends, inside a knot budget.

    A fixed grid is too coarse for a transfer function toe: sRGB-to-gamma-2.4 has an infinite slope
    at black, and 64 evenly spaced knots left the browser table and the FFmpeg expression about five
    levels away from the curve they are meant to reproduce. Refining on midpoint drift keeps both
    renderers within half a level of the published function instead of merely agreeing with each
    other about the wrong number.
    """
    points = [(value, composed(value)) for value in axis]
    while len(points) < budget:
        candidates = []
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            middle = (x0 + x1) / 2
            drift = abs(composed(middle) - (y0 + y1) / 2)
            if drift > tolerance:
                candidates.append((drift, middle))
        if not candidates:
            break
        candidates.sort(reverse=True)
        room = max(1, (budget - len(points)) // 2)
        points = sorted(points + [(middle, composed(middle)) for _, middle in candidates[:room]])
    return [(value * 255, output * 255) for value, output in points]


def _simplify(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept = [points[0]]
    for point in points[1:]:
        while len(kept) >= 2:
            left, middle = kept[-2], kept[-1]
            if point[0] - left[0] > MAX_SPAN or point[0] <= left[0]:
                break
            expected = left[1] + (middle[0] - left[0]) * (point[1] - left[1]) / (point[0] - left[0])
            if abs(middle[1] - expected) > TOLERANCE:
                break
            kept.pop()
        kept.append(point)
    return kept


def _lookup(points: list[tuple[float, float]]) -> list[float]:
    mapping = _piecewise(points)
    return [round(mapping(index) / 255, 9) for index in range(256)]


def _expression(points: list[tuple[float, float]]) -> str:
    if all(abs(output - input_level) < 1e-9 for input_level, output in points):
        # An identity chain must add no stage at all. Checking every knot rather than only the two
        # ends matters because the adaptive refinement leaves several collinear points behind.
        return "val"
    first, second = points[-2], points[-1]
    tail_slope = (second[1] - first[1]) / (second[0] - first[0])
    expression = f"{first[1]:.10g}+{tail_slope:.10g}*(val-{first[0]:.10g})"
    for index in range(len(points) - 2, 0, -1):
        left, right = points[index - 1], points[index]
        slope = (right[1] - left[1]) / (right[0] - left[0])
        head = f"{left[1]:.10g}+{slope:.10g}*(val-{left[0]:.10g})"
        expression = f"if(lt(val,{right[0]:.10g}),{head},{expression})"
    return f"clip({expression},0,255)"


def _polylines(color) -> dict[str, list[tuple[float, float]]] | None:
    channels = {}
    for index, name in enumerate(CHANNEL_NAMES):
        channels[name] = _channel_points(color.grade, index) or [(0.0, 0.0), (255.0, 255.0)]
    return channels if any(node.enabled and node.mix for node in color.grade) else None


def grade_tables(color) -> dict | None:
    """Per-channel 256-entry browser LUT with a stable filter id, or None for a no-op chain."""
    channels = _polylines(color)
    if channels is None:
        return None
    tables = {name: _lookup(points) for name, points in channels.items()}
    if all(
        all(abs(value - index / 255) < 1e-9 for index, value in enumerate(table))
        for table in tables.values()
    ):
        return None
    payload = repr([(name, tables[name]) for name in CHANNEL_NAMES]).encode()
    return {"id": f"g{hashlib.sha1(payload).hexdigest()[:16]}", **tables}


def grade_filter(color) -> str:
    """FFmpeg stage compiled from the same polylines; empty when the chain is a no-op."""
    channels = _polylines(color)
    if channels is None:
        return ""
    stages = {name: _expression(points) for name, points in channels.items()}
    if all(value == "val" for value in stages.values()):
        return ""
    return "lutrgb=" + ":".join(f"{name}='{value}'" for name, value in stages.items())


def parse_1d_cube(text: str, *, title_default: str = "LUT") -> dict:
    """Parse the 1D flavour of an Autodesk `.cube` file into a `GradeLUT` payload.

    Only `LUT_1D_SIZE` is accepted: its rows are independent per-channel ramps, which is exactly
    the per-channel table this chain can hold. A 3D LUT's output depends on all three inputs at
    once, so accepting it here would mean quietly flattening a cross-channel transform into three
    independent ones — refuse with that sentence instead. The samples clamp onto 0..1; rows come
    red-fastest per the format's definition.
    """
    title = title_default
    size = 0
    domain_min, domain_max = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    samples: list[tuple[float, float, float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        upper = stripped.upper()
        if upper.startswith("TITLE"):
            words = stripped.split(None, 1)
            if len(words) > 1:
                title = words[1].strip().strip('"')[:64]
            continue
        if upper.startswith("LUT_1D_SIZE"):
            size = _cube_int(upper.split()[1], "LUT_1D_SIZE")
            continue
        if upper.startswith("LUT_3D_SIZE"):
            raise _cube_error("this is a 3D LUT; cross-channel tables are not supported yet")
        if upper.startswith("DOMAIN_MIN") or upper.startswith("DOMAIN_MAX"):
            values = [_cube_float(item) for item in stripped.split()[1:]]
            if len(values) != 3:
                raise _cube_error("DOMAIN needs three numbers")
            if upper.startswith("DOMAIN_MIN"):
                domain_min = tuple(values)  # type: ignore[assignment]
            else:
                domain_max = tuple(values)  # type: ignore[assignment]
            continue
        parts = stripped.split()
        if len(parts) != 3:
            raise _cube_error(f"cannot read the row {stripped[:40]!r}")
        samples.append(tuple(_cube_float(item) for item in parts))  # type: ignore[arg-type]
    if size < 2:
        raise _cube_error("the file needs a LUT_1D_SIZE of 2 or more")
    if len(samples) != size:
        raise _cube_error(f"expected {size} rows but found {len(samples)}")
    if domain_min != (0.0, 0.0, 0.0) or domain_max != (1.0, 1.0, 1.0):
        raise _cube_error("only the default DOMAIN 0..1 is supported")
    channels = [[_clamp(row[index]) for row in samples] for index in range(3)]
    size_limit = _lut_size_limit()
    if size <= size_limit:
        return {"title": title, "size": size, "channels": channels}
    # More rows than the contract's grid allows — and the table is read as piecewise-linear either
    # way, so resample it evenly rather than refusing a file the user already owns. Nothing is
    # silent: `resampled_from` travels in the reply, and the node says so in the interface.
    step = (size - 1) / (size_limit - 1)
    channels = [
        [_sample(row, position * step) for position in range(size_limit)] for row in channels
    ]
    return {"title": title, "size": size_limit, "channels": channels, "resampled_from": size}


def _lut_size_limit() -> int:
    from .contracts import LUT_SAMPLE_LIMIT

    return LUT_SAMPLE_LIMIT


def _sample(table: list[float], position: float) -> float:
    """The piecewise-linear value of one channel's table at an fractional grid index."""
    index = int(position)
    if index >= len(table) - 1:
        return table[-1]
    fraction = position - index
    return table[index] + fraction * (table[index + 1] - table[index])


def _cube_error(message: str) -> Exception:
    from .contracts import EditorError

    return EditorError("INVALID_LUT", message, 422)


def _cube_int(text: str, what: str) -> int:
    try:
        return int(text)
    except ValueError as error:
        raise _cube_error(f"{what} must be a whole number") from error


def _cube_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise _cube_error(f"cannot read the number {text[:20]!r}") from error
    if value != value or value in (float("inf"), float("-inf")):
        raise _cube_error("LUT numbers must be finite")
    return value
