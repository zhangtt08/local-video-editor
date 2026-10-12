"""Grade nodes compiled into an ordered stage list that both FFmpeg and the browser walk.

Per-channel nodes — curves, levels, white balance, wheels, transfer functions, imported 1D tables —
still collapse: a run of them is one transfer curve per channel, exported as an FFmpeg ``lutrgb``
expression and as a browser ``feComponentTransfer`` table sampled from the same simplified polyline.
A cross-channel node (the channel mixer) breaks the run, because a matrix sandwiched between two
per-channel curves is not itself a per-channel curve. Order is preserved and both renderers read the
same list, so preview and render stay one authority rather than merely similar.
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
LEVELS_NEUTRAL = (0.0, 1.0, 1.0)


def _levels_function(node, index: int):
    """Input-range stretch on one channel: black point, white point, then midtone gamma.

    This is the levels control every grading surface has (Resolve's colour wheel panels, Photoshop's
    Levels, 剪映's 色阶), and it stays a per-channel function, so adding it costs the chain nothing:
    the browser table and the FFmpeg expression are still sampled from one polyline.
    """
    black, white, gamma = node.black, node.white, node.gamma
    if node.channel != "rgb" and CURVE_CHANNELS[node.channel] != index:
        return None
    if (black, white, gamma) == LEVELS_NEUTRAL:
        return None
    span = white - black
    inverse = 1 / gamma

    def levels(value: float) -> float:
        stretched = _clamp((value - black) / span)
        return _clamp(stretched**inverse)

    return levels


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
    if node.kind == "levels":
        return _levels_function(node, index)
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

    A parallel node outputs the **weighted** mean of its branch results (1.120): with no weights
    given, every branch counts the same, which is the mean this code has always produced. A
    bypassed branch — or one that does not touch this channel at all — contributes its input, so
    disabling a branch fades the average toward the remaining branches instead of renumbering them.
    Weights are positional and the contract makes them cover every branch or none, so a slot can
    never be silently dropped from the sum. Every weight at 0 means nothing is being added: that is
    this node leaving the picture alone, not a black frame, so it returns None. Each branch may also
    carry a blend mode (1.122) that composites its result onto the value entering the node with the
    very same `blend_values` the node-level blend uses; all-normal reproduces 1.120 bit for bit.
    """
    if node.kind != "parallel":
        return _op_function(node, index)
    steps = [
        None if not branch.enabled else step_function(branch, index) for branch in node.branches
    ]
    if not any(steps):
        return None
    weights = list(node.weights) if node.weights else [1.0] * len(steps)
    modes = list(node.blends) if node.blends else ["normal"] * len(steps)
    total = sum(weights)
    if total <= 0:
        return None

    def average(value: float) -> float:
        # 一份加权平均，没有第二条路：乘 1.0 在二进制里是精确的，所以没给权重时这一句算出来的就是
        # 1.119 那条均分——兼容性由 `grade_check` 逐位钉住，而不是靠这里多写一条分支。
        # 1.122 的分支混合方式用的就是节点级混合那个同一份 `blend_values`：全 normal 时它原样交回
        # 该支结果，于是这一版与 1.120 逐位相同。停用的一支交回进来的那个值本身，它的模式不参与——
        # 「停用即直通」不能因为一个没人看的下拉而改名。
        return (
            sum(
                (blend_values(mode, value, step(value)) if step is not None else value) * weight
                for step, mode, weight in zip(steps, modes, weights, strict=True)
            )
            / total
        )

    return average


def _leaf_operations(node):
    """这台节点真正做的那些操作——一层或多层混频台都只数叶子。

    采样网格要知道曲线上每一个折点，1.124 起折点可能藏在第二层、第三层混频台的某一支里，所以这里
    跟着树走；不然嵌套进去的那条曲线就只能被弦线近似，两端读的就不再是同一张表。
    """
    if node.kind != "parallel":
        yield node
        return
    for branch in node.branches:
        yield from _leaf_operations(branch)


def _curve_knots(node, index: int):
    """Input positions where a node (or one of its branches) actually bends this channel."""
    operations = list(_leaf_operations(node))
    for operation in operations:
        if operation.kind == "curve":
            if operation.channel != "rgb" and CURVE_CHANNELS[operation.channel] != index:
                continue
            yield from (point.x for point in operation.points)
        elif operation.kind == "lut":
            count = operation.size
            yield from (step / (count - 1) for step in range(count))
        elif operation.kind == "levels":
            # The two input points are where this node's slope changes, so the sampling grid has to
            # break there; without them a steep stretch is approximated by chords across the knee.
            if operation.channel == "rgb" or CURVE_CHANNELS[operation.channel] == index:
                yield operation.black
                yield operation.white


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


def _matrix_of(node):
    """The node's 3x3 with its own strength folded in, or None when it leaves the picture alone.

    Strength is a linear blend toward the input, and a blend of a matrix with the identity is still
    a matrix — so `mix` costs nothing here. A *blend mode* would not be linear in the inputs
    (`in × matrix(in)` is quadratic), which is why the node has no `blend` field to send at all.
    """
    if not node.enabled or not node.mix:
        return None
    mix = node.mix
    folded = [
        (1.0 if row == column else 0.0)
        + mix * (node.coefficients[row * 3 + column] - (1.0 if row == column else 0.0))
        for row in range(3)
        for column in range(3)
    ]
    identity = [1.0 if row == column else 0.0 for row in range(3) for column in range(3)]
    if all(abs(value - neutral) < 1e-12 for value, neutral in zip(folded, identity)):
        return None
    return folded


def grade_stages(color) -> list[dict] | None:
    """The compiled chain as an ordered list of stages, or None when nothing would change.

    Consecutive per-channel nodes still collapse into one table per channel. A cross-channel node
    breaks the run, because a matrix sandwiched between two per-channel curves is not itself a
    per-channel curve — and the order is kept, so `curve → matrix` and `matrix → curve` compile to
    different graphs. Both renderers walk this one list.
    """
    stages: list[dict] = []
    group: list = []

    def flush() -> None:
        if not group:
            return
        if any(node.enabled and node.mix for node in group):
            channels = {
                name: _channel_points(group, index) or [(0.0, 0.0), (255.0, 255.0)]
                for index, name in enumerate(CHANNEL_NAMES)
            }
            stages.append({"type": "lut", **channels})
        del group[:]

    for node in color.grade:
        if node.kind == "lut3d":
            flush()
            if node.enabled:
                stages.append(
                    {"type": "lut3d", "title": node.title, "size": node.size, "cells": node.cells}
                )
            continue
        if node.kind == "matrix":
            flush()
            matrix = _matrix_of(node)
            if matrix is not None:
                stages.append({"type": "matrix", "m": matrix})
            continue
        if node.kind == "composite":
            # 这一条不是一幅进一幅出的每通道函数：它读两幅画，所以先把攒下的段落结成一张表，
            # 再把这条边原样交给编译方（`render.py` 在那里劈图与相合）。
            flush()
            if node.enabled:
                stages.append({"type": "composite", "mode": node.mode, "mix": node.mix})
            continue
        group.append(node)
    flush()
    return stages or None


def composite_stages(color) -> list[dict]:
    """这条链上的第二输入边，按链里的顺序交回来；没有就交回空表。

    只有一条判断「有没有」的地方才可信：`render.py` 决定要不要劈图、`compile` 决定要不要
    在分层项目上点名拒绝，问的都是这一个函数。
    """
    return [
        {"mode": stage["mode"], "mix": stage["mix"]}
        for stage in (grade_stages(color) or [])
        if stage["type"] == "composite"
    ]


def _lut_stage(points: dict) -> dict | None:
    """A browser table for one LUT stage, or None when every channel is the identity."""
    tables = {name: _lookup(points[name]) for name in CHANNEL_NAMES}
    if all(
        all(abs(value - index / 255) < 1e-9 for index, value in enumerate(table))
        for table in tables.values()
    ):
        return None
    return {"type": "lut", **tables}


def _stage_id(payload) -> str:
    return hashlib.sha1(repr(payload).encode()).hexdigest()[:12]


def grade_tables(color) -> dict | None:
    """The ordered stage list the browser builds primitives from, or None for a no-op chain.

    The chain's id covers every stage, so one `filter: url(#id)` still references the whole grade
    and two clips with the same look still share one filter definition.
    """
    stages = grade_stages(color)
    if not stages:
        return None
    built = []
    for stage in stages:
        if stage["type"] == "lut3d":
            # The browser has no primitive for a cross-channel cube, so the stage travels
            # without its data; `preview: false` is what the interface labels 预览不生效.
            built.append(
                {
                    "type": "lut3d",
                    "id": f"d{_stage_id([stage['size'], stage['title']])}",
                    "title": stage["title"],
                    "size": stage["size"],
                    "preview": False,
                }
            )
            continue
        if stage["type"] == "composite":
            # 浏览器的一条滤镜链没有第二个画面输入，所以这一级带着 `preview: False` 出门，
            # 由 `preview_grade` 整条丢掉、由界面写明「预览不生效、导出生效」——与 3D LUT 同一条路。
            built.append(
                {
                    "type": "composite",
                    "id": f"c{_stage_id([stage['mode'], stage['mix']])}",
                    "mode": stage["mode"],
                    "mix": stage["mix"],
                    "preview": False,
                }
            )
            continue
        if stage["type"] == "lut":
            table = _lut_stage(stage)
            if table is None:
                continue
            built.append(dict(table, id=f"l{_stage_id(table['r'] + table['g'] + table['b'])}"))
        else:
            built.append({"type": "matrix", "m": stage["m"], "id": f"m{_stage_id(stage['m'])}"})
    if not built:
        return None
    payload = repr(built).encode()
    return {"id": f"g{hashlib.sha1(payload).hexdigest()[:16]}", "stages": built}


def preview_grade(color) -> dict | None:
    """The stage list the browser can composite, or None when the chain has nothing it can draw.

    `preview: false` is the engine's own flag on a cross-channel stage, and this is the one place
    that reads it. A stage the browser cannot evaluate must not travel into the manifest at all:
    the interface draws every stage it receives, so a cube would come out as a filter primitive
    holding no numbers — that is a vanished picture, not the documented 预览不生效.
    """
    tables = grade_tables(color)
    if tables is None:
        return None
    stages = [stage for stage in tables["stages"] if stage.get("preview", True)]
    if not stages:
        return None
    return {**tables, "stages": stages}


def grade_filter(color, plan=None) -> str:
    """The FFmpeg stage list compiled from the same stages; empty when the chain is a no-op.

    A 3D LUT needs a file on disk for `lut3d=file=…`, so the compiler writes the cube into the
    job directory (the same `text_files` mechanism the oversized filter graphs already use) and
    asks for tetrahedral interpolation. Without a plan there is nowhere to put that file, and
    saying so beats emitting a graph that quietly drops the node.
    """
    stages = grade_stages(color)
    if not stages:
        return ""
    parts = []
    for stage in stages:
        if stage["type"] == "lut3d":
            if plan is None:
                from .contracts import EditorError

                raise EditorError(
                    "LUT3D_NO_PLAN",
                    "a 3D LUT can only be compiled by a render plan that writes its cube file",
                    422,
                    title=stage["title"],
                )
            body = cube_text(stage["title"], stage["size"], stage["cells"])
            name = "lut3d-" + hashlib.sha1(body.encode()).hexdigest()[:16] + ".cube"
            plan.text_files[name] = body
            parts.append(f"lut3d=file={name}:interp=tetrahedral")
            continue
        if stage["type"] == "composite":
            # 这条边由调用方编成 `split` + 两段 `blend`（见 `render.py` 的 cut 路径），
            # 在这里必须整条跳过：掉进下面那个「按矩阵拼 colorchannelmixer」的分支会 KeyError。
            continue
        if stage["type"] == "lut":
            expressions = {name: _expression(stage[name]) for name in CHANNEL_NAMES}
            if all(value == "val" for value in expressions.values()):
                continue
            parts.append(
                "lutrgb=" + ":".join(f"{name}='{value}'" for name, value in expressions.items())
            )
        else:
            names = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
            parts.append(
                "colorchannelmixer="
                + ":".join(f"{name}={value:.10g}" for name, value in zip(names, stage["m"]))
                + ":aa=1"
            )
    return ",".join(parts)


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
    for number, line in enumerate(text.splitlines(), start=1):
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
            size = _cube_int(upper.split()[1], "LUT_1D_SIZE", line=number)
            continue
        if upper.startswith("LUT_3D_SIZE"):
            raise _cube_error("this is a 3D LUT; parse_cube reads it as a lut3d node", line=number)
        if upper.startswith("DOMAIN_MIN") or upper.startswith("DOMAIN_MAX"):
            values = [_cube_float(item, line=number) for item in stripped.split()[1:]]
            if len(values) != 3:
                raise _cube_error("DOMAIN needs three numbers", line=number)
            if upper.startswith("DOMAIN_MIN"):
                domain_min = tuple(values)  # type: ignore[assignment]
            else:
                domain_max = tuple(values)  # type: ignore[assignment]
            continue
        parts = stripped.split()
        if len(parts) != 3:
            raise _cube_error(f"cannot read the row {stripped[:40]!r}", line=number)
        samples.append(tuple(_cube_float(item, line=number) for item in parts))  # type: ignore[arg-type]
    if size < 2:
        raise _cube_error("the file needs a LUT_1D_SIZE of 2 or more", size=size, rows=len(samples))
    if len(samples) != size:
        raise _cube_error(
            f"expected {size} rows but found {len(samples)}",
            size=size,
            rows=len(samples),
        )
    if domain_min != (0.0, 0.0, 0.0) or domain_max != (1.0, 1.0, 1.0):
        raise _cube_error(
            "only the default DOMAIN 0..1 is supported",
            domain_min=list(domain_min),
            domain_max=list(domain_max),
        )
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


def _cube_error(message: str, **details) -> Exception:
    from .contracts import EditorError

    return EditorError("INVALID_LUT", message, 422, **details)


def _cube_int(text: str, what: str, *, line: int) -> int:
    try:
        return int(text)
    except ValueError as error:
        raise _cube_error(f"{what} must be a whole number", line=line) from error


def _cube_float(text: str, *, line: int) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise _cube_error(f"cannot read the number {text[:20]!r}", line=line) from error
    if value != value or value in (float("inf"), float("-inf")):
        raise _cube_error("LUT numbers must be finite", line=line)
    return value


def parse_cube(text: str, *, title_default: str = "LUT") -> dict:
    """Read any Autodesk `.cube` file and say which flavour it is.

    One entry point for both kinds, so neither the interface nor an Agent has to guess from the file
    name: the file's own header decides, and the result carries `kind` (`lut` or `lut3d`). A 1D file
    yields `title/size/channels`; a 3D one `title/size/cells` plus `resampled_from` when its grid
    larger than the contract's inline ceiling.
    """
    if "LUT_3D_SIZE" in text.upper():
        return {"kind": "lut3d", **parse_3d_cube(text, title_default=title_default)}
    return {"kind": "lut", **parse_1d_cube(text, title_default=title_default)}


def parse_3d_cube(text: str, *, title_default: str = "LUT") -> dict:
    """Parse a `LUT_3D_SIZE` cube: `size**3` rows of RGB, red varying fastest per the format.

    Only the default DOMAIN 0..1 is accepted; matrices/interp keywords are refused by name, never
    half-applied — a file that needs them is not the transform this node can hold. Samples clamp
    onto 0..1 like the 1D path. A grid over `LUT3D_SIZE_LIMIT` is resampled trilinearly instead
    of refused, because the table is interpolated either way; `resampled_from` carries the original
    edge count so nothing about that is silent.
    """
    title = title_default
    size = size_line = 0
    samples: list[tuple[float, float, float]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        upper = stripped.upper()
        if upper.startswith("TITLE"):
            words = stripped.split(None, 1)
            if len(words) > 1:
                title = words[1].strip().strip('"')[:64]
            continue
        if upper.startswith("LUT_3D_SIZE"):
            if size:
                raise _cube_error("the file declares LUT_3D_SIZE twice", line=number)
            size, size_line = _cube_int(upper.split()[1], "LUT_3D_SIZE", line=number), number
            if size < 2:
                raise _cube_error("LUT_3D_SIZE must be 2 or more", line=number)
            continue
        if upper.startswith("LUT_1D_SIZE"):
            raise _cube_error("this is a 1D LUT; the 1D reader takes it", line=number)
        if upper.startswith(("DOMAIN_MIN", "DOMAIN_MAX")):
            values = [_cube_float(item, line=number) for item in stripped.split()[1:]]
            if len(values) != 3:
                raise _cube_error("DOMAIN needs three numbers", line=number)
            wanted = (0.0, 0.0, 0.0) if upper.startswith("DOMAIN_MIN") else (1.0, 1.0, 1.0)
            if tuple(values) != wanted:
                raise _cube_error("only the default DOMAIN 0..1 is supported", line=number)
            continue
        if upper.split()[0] in {"INPUT_MATRIX", "OUTPUT_MATRIX", "LUT_TYPE", "VERTEX_INTERP"}:
            raise _cube_error(f"{stripped.split()[0]} is not supported by this node", line=number)
        parts = stripped.split()
        if len(parts) != 3:
            raise _cube_error(f"cannot read the row {stripped[:40]!r}", line=number)
        if not size:
            raise _cube_error("the file needs a LUT_3D_SIZE before its rows", line=number)
        samples.append(tuple(_cube_float(item, line=number) for item in parts))  # type: ignore[arg-type]
    if not size:
        raise _cube_error("the file has no LUT_3D_SIZE header", rows=len(samples))
    if len(samples) != size**3:
        raise _cube_error(
            f"expected {size**3} rows for a {size} cube but found {len(samples)}",
            size=size,
            rows=len(samples),
            line=size_line,
        )
    cells = [_clamp(value) for row in samples for value in row]
    from .contracts import LUT3D_SIZE_LIMIT

    resampled_from = None
    if size > LUT3D_SIZE_LIMIT:
        cells, resampled_from = _resample_cube(cells, size, LUT3D_SIZE_LIMIT), size
        size = LUT3D_SIZE_LIMIT
    return {"title": title, "size": size, "cells": cells, "resampled_from": resampled_from}


def _resample_cube(cells: list[float], size: int, target: int) -> list[float]:
    """Trilinear resample onto a `target` grid — the same chords FFmpeg interpolates with."""

    def read(index_r: int, index_g: int, index_b: int) -> tuple[float, float, float]:
        base = 3 * (index_r + size * (index_g + size * index_b))
        return cells[base], cells[base + 1], cells[base + 2]

    def sample(r: float, g: float, b: float) -> tuple[float, float, float]:
        lows, weights = [], []
        for value in (r, g, b):
            grid = value * (size - 1)
            low = min(int(grid), size - 2)
            lows.append(low)
            weights.append(grid - low)
        high = [min(low + 1, size - 1) for low in lows]
        fr, fg, fb = weights
        out = []
        for channel in range(3):
            corners = [
                read(lows[0], lows[1], lows[2])[channel],
                read(high[0], lows[1], lows[2])[channel],
                read(lows[0], high[1], lows[2])[channel],
                read(high[0], high[1], lows[2])[channel],
                read(lows[0], lows[1], high[2])[channel],
                read(high[0], lows[1], high[2])[channel],
                read(lows[0], high[1], high[2])[channel],
                read(high[0], high[1], high[2])[channel],
            ]
            lo_b = (
                corners[0] * (1 - fr) + corners[1] * fr,
                corners[2] * (1 - fr) + corners[3] * fr,
            )
            hi_b = (
                corners[4] * (1 - fr) + corners[5] * fr,
                corners[6] * (1 - fr) + corners[7] * fr,
            )
            mid = lo_b[0] * (1 - fg) + lo_b[1] * fg
            top = hi_b[0] * (1 - fg) + hi_b[1] * fg
            out.append(_clamp(mid + (top - mid) * fb))
        return out[0], out[1], out[2]

    step = 1.0 / (target - 1)
    return [
        value
        for blue in range(target)
        for green in range(target)
        for red in range(target)
        for value in sample(red * step, green * step, blue * step)
    ]


def cube_text(title: str, size: int, cells: list[float]) -> str:
    """The node back into `.cube` text, in the file order FFmpeg's `lut3d` reads (red fastest)."""
    rows = [
        f"{cells[index]:.6f} {cells[index + 1]:.6f} {cells[index + 2]:.6f}"
        for index in range(0, len(cells), 3)
    ]
    return (
        f'TITLE "{title}"\n'
        f"LUT_3D_SIZE {size}\n"
        "DOMAIN_MIN 0.0 0.0 0.0\n"
        "DOMAIN_MAX 1.0 1.0 1.0\n" + "\n".join(rows) + "\n"
    )
