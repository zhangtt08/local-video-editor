"""基色（primaries）转换矩阵：一张由引擎算出来的表，界面与 Agent 都从这一处读。

`transfer` 那个节点只管色调曲线（一条 EOTF 进、一条 OETF 出），它**不动基色**——所以把 Rec.2020
的素材当 Rec.709 用，gamma 可以对上，色域对不上：同一组存储值落在色域三角形里的另一个位置。

这一步交的是一**份表**，不是一颗按钮：要把它用在链子里，正确写法是把九个数写进 `matrix` 节点，
并在它前后各挂一个 `transfer` 把画面抬进线性光再落回目标档（`clip.color_manage` 从 1.130 起就在
写这样一对）。`matrix` 那九个数是直接乘在**存储值**上的，单独挂它做基色转换就是错的——这一点在
`GradeFields` 的通道混合提示里已经写着，这里只是把「怎么才对」的那份数据交出去。

矩阵按常规解法：由 xy 与白点解出每原色的缩放 S，A = [[x],[y],[1-x-y]]·diag(S) 把线性 RGB 映到
XYZ；两档之间 M = inv(A_target) @ A_source。行=输出通道，列=输入通道。

三条性质不是靠相信，而是由 `tests/gamut_check.py` 量：① 每行和恰为 1（中性灰不动）；② 正逆档
往返是恒等；③ `M · (1,0,0)` 与「同一个色度经 XYZ 换算到目标档」**成比例**——颜色是三维向量的
等价类，不归一化就比（先 sum 再比），对的矩阵也会读成错的。

白点：本表全是 D65，所以不需要色适应。哪天加进 D60/D50 的档，`primaries_matrix` 会直接拒——
「只做了半套色适应」在成片里读起来只是颜色有点偏，没人会当 bug 报，所以宁可拒。
也因为这个，**影院 DCI-P3 不在这张表里**：它的白点是影院基准（约 `0.314,0.351`）、传递特性是
γ2.6。表里那一档 `p3-d65-g22` 是 P3 原色配 **D65 白 + γ2.2**（业界常写的「DCI-P3 D65」那一档），
与 `display-p3` 只差曲线那一项——名字与 label 都按这个写，不许念「影院母带」。
"""

from __future__ import annotations

from typing import Callable

# 名字 → (三原色 xy, 白点 xy, 那一档实际用的传递函数名)。传递函数名与 `contracts.ColorSpace`
# 同一套词：界面上「基色」与「曲线」是两件事，但说话时一起说，所以随表交出去（本模块不用它算矩阵）。
PRIMARIES: dict[str, tuple[tuple[tuple[float, float], ...], tuple[float, float], str]] = {
    "rec709": (
        ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
        (0.3127, 0.3290),
        "rec709",
    ),
    "rec601": (
        ((0.630, 0.340), (0.310, 0.595), (0.155, 0.077)),
        (0.3127, 0.3290),
        "rec709",
    ),
    "rec2020": (
        ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
        (0.3127, 0.3290),
        "rec709",
    ),
    "p3-d65-g22": (
        ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
        (0.3127, 0.3290),
        "gamma22",
    ),
    "display-p3": (
        ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
        (0.3127, 0.3290),
        "srgb",
    ),
    # 交付那一端用的 P3 档：原色与白点与上面两档同表，差的是**曲线名**——这一档配的
    # 就是容器声明的 BT.709（`gamut.delivery_cube` 两侧都按 bt709 折，标签也写 bt709），
    # 所以它不能借用 `p3-d65-g22` 那个名字：那个名字已经把 γ2.2 写在里面了。
    "p3-d65": (
        ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
        (0.3127, 0.3290),
        "rec709",
    ),
}

# 界面上给的那几档：id 是稳定说法，label 给人看；两端的传递函数一起交出去，
# 因为「挂这一档矩阵」必须先问「素材的曲线是哪一条」。
GAMUT_PRESETS: tuple[dict, ...] = (
    {
        "id": "rec2020_to_rec709",
        "label": "Rec.2020 → Rec.709（收到广播色域）",
        "source": "rec2020",
        "target": "rec709",
    },
    {
        "id": "rec709_to_rec2020",
        "label": "Rec.709 → Rec.2020（扩到 UHD 色域）",
        "source": "rec709",
        "target": "rec2020",
    },
    {
        "id": "p3d65g22_to_rec709",
        "label": "P3 原色（D65 白、γ2.2）→ Rec.709（广色屏收到电视）",
        "source": "p3-d65-g22",
        "target": "rec709",
    },
    {
        "id": "rec709_to_p3d65g22",
        "label": "Rec.709 → P3 原色（D65 白、γ2.2）",
        "source": "rec709",
        "target": "p3-d65-g22",
    },
    {
        "id": "displayp3_to_rec709",
        "label": "Display P3 → Rec.709（广色屏素材收到电视）",
        "source": "display-p3",
        "target": "rec709",
    },
    {
        "id": "rec601_to_rec709",
        "label": "SMPTE-C(Rec.601) → Rec.709（标带上 HD）",
        "source": "rec601",
        "target": "rec709",
    },
)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """3×3 高斯消元。自己写是因为这台机器上没有 numpy，不该为一张表把依赖拖进来。"""
    m = [list(row) + [b[index]] for index, row in enumerate(a)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(m[row][column]))
        if abs(m[pivot][column]) < 1e-12:
            raise ValueError(f"基色矩阵在第 {column} 列奇异")
        m[column], m[pivot] = m[pivot], m[column]
        divide = m[column][column]
        m[column] = [value / divide for value in m[column]]
        for row in range(3):
            if row == column:
                continue
            factor = m[row][column]
            m[row] = [value - factor * other for value, other in zip(m[row], m[column])]
    return [m[row][3] for row in range(3)]


def _rgb_to_xyz(name: str) -> list[list[float]]:
    xy, white, _curve = PRIMARIES[name]
    xw, yw = white
    weight = [xw / yw, 1.0, (1.0 - xw - yw) / yw]
    rows = [
        [xy[0][0], xy[1][0], xy[2][0]],
        [xy[0][1], xy[1][1], xy[2][1]],
        [1 - xy[0][0] - xy[0][1], 1 - xy[1][0] - xy[1][1], 1 - xy[2][0] - xy[2][1]],
    ]
    scale = _solve(rows, weight)
    return [[rows[row][col] * scale[col] for col in range(3)] for row in range(3)]


def _inverse(a: list[list[float]]) -> list[list[float]]:
    """解 `A·x = eᵢ` 交出的是逆矩阵的**第 i 列**，所以要按列拼回去。

    按行拼会拿到转置：九个数字看上去都还「像矩阵」，行和也还是 1，
    只有往返一测才露馅（误差 1 量级）。
    """
    columns = [_solve(a, unit) for unit in ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])]
    return [[column[row] for column in columns] for row in range(3)]


def _multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3)] for row in range(3)]


def primaries_matrix(source: str, target: str) -> list[list[float]]:
    """线性光里把 `source` 的三通道换成 `target` 的九个系数（行=输出，列=输入）。"""
    if source not in PRIMARIES or target not in PRIMARIES:
        raise KeyError(f"不认识的基色档：{source} / {target}")
    if PRIMARIES[source][1] != PRIMARIES[target][1]:
        raise ValueError(f"{source} 与 {target} 白点不同，需要先做色适应（本表没有那一半）")
    return _multiply(_inverse(_rgb_to_xyz(target)), _rgb_to_xyz(source))


# 工程级基色可以选的那几档：`PRIMARIES` 里「曲线就是交付那一档」的名字。词表只有这一个主人，
# 契约与界面都从这里读——再抄一份 Literal 就是给同一句话两个答案，而落在成片里的是引擎这一个。
WORKING_PRIMARIES: tuple[str, ...] = tuple(
    name for name, entry in PRIMARIES.items() if entry[2] == "rec709"
)


def working_collapse(source: str, display: str = "rec709") -> list[float] | None:
    """把「按 `source` 那档基色解释的图」落到 `display` 上要乘的九个系数；同一档就没有这一级。

    工程基色与看它的那一端说的不是同一档时才有它：预览那一趟折到显示端（浏览器是 sRGB），交付那一趟
    折到容器声明的那档。九个系数仍由 `primaries_matrix` 算，这里只配两端并说「相等就不折」。
    """
    if source == display:
        return None
    return [round(value, 6) for row in primaries_matrix(source, display) for value in row]


def chromaticity_rgb(space: str, xy: tuple[float, float]) -> list[float]:
    """某个色度坐标在该档线性 RGB 里的表示（用于性质判据；与矩阵同一条路，不引外部数）。"""
    xw, yw = PRIMARIES[space][1]
    weight = [xy[0] / xy[1], 1.0, (1.0 - xy[0] - xy[1]) / xy[1]]
    return [
        sum(value * weight[k] for k, value in enumerate(row))
        for row in _inverse(_rgb_to_xyz(space))
    ]


def gamut_presets() -> list[dict]:
    """能力表交出去的那份：id、给人看的名字、两端传递函数，加上算好的九个系数。"""
    said = []
    for preset in GAMUT_PRESETS:
        matrix = primaries_matrix(preset["source"], preset["target"])
        said.append(
            {
                "id": preset["id"],
                "label": preset["label"],
                "source": preset["source"],
                "target": preset["target"],
                "source_transfer": PRIMARIES[preset["source"]][2],
                "target_transfer": PRIMARIES[preset["target"]][2],
                "coefficients": [round(value, 6) for row in matrix for value in row],
            }
        )
    return said


# 交付母版那一端的「曲线」只认容器声明的那一档：写 bt709 就得按 ITU-R BT.709 的
# α=1.099、β=0.099、线性段斜率 4.5、光侧拐点 0.018 来折。链子里那个 `rec709` 是纯 γ2.4
# （`grade.GAMMA_BY_SPACE`，那是对人眼的显示端建模），两件事不是一回事，所以这里单独一对。
# 这四个数是 ITU-R BT.709 的公开定义本身：α=1.099、β=0.099、编码侧指数 0.45、线性段斜率 4.5
# （拐点在光侧 0.018、信号侧 0.081）。别拿 zscale 的 TRC 当权威去对表——那一站连着 re-range 一起做，
# 量的不是同一条式子（1.153 试过，两边差一成）。钉住这条曲线的是 `tests/colour_tag_check.py`：
# 交出去的 YUV 要等于按它折的那一组，且按标记解回来要落回源色。
BT709_ALPHA = 1.099
BT709_BETA = 0.099
BT709_TURN = 0.018
BT709_SLOPE = 4.5
BT709_SIGNAL_TURN = BT709_TURN * BT709_SLOPE  # 0.081：信号侧的直线段上限
BT709_GAMMA = 0.45  # 编码侧的指数
BT709_GAMMA_INVERSE = 1 / 0.45  # 解码侧的指数（别与上面那行对调）


def bt709_eotf(signal: float) -> float:
    """声明成 bt709 的那格信号换回线性光。"""
    if signal <= BT709_SIGNAL_TURN:
        return signal / BT709_SLOPE
    return ((signal + BT709_BETA) / BT709_ALPHA) ** BT709_GAMMA_INVERSE


def bt709_oetf(light: float) -> float:
    """`bt709_eotf` 的逆：线性光落回那一档信号。

    两个指数一边一个，别对调——1.153 就对调过一次：那对函数仍然互逆，于是纯色往返与恒等控制组
    全都绿，只有碰到色域边界（换基色后某一通道本该是极小值）才把信号算成负数、被夹成 0，
    解回来差到 85 阶。互逆的一对错曲线是自洽检查抓不到的，所以 `tests/colour_tag_check.py` 拿
    随包 FFmpeg 的 709 TRC 对表。
    """
    if light < BT709_TURN:
        return BT709_SLOPE * light
    return BT709_ALPHA * light**BT709_GAMMA - BT709_BETA


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


GAMMA_24 = 2.4  # 纯幂那一条：BT.1886 的显示端建模，也是链子里 `rec709` 那一格实际的数


def gamma24_eotf(signal: float) -> float:
    """声明成「纯幂 2.4」的那格信号换回线性光。"""
    return _clamp(signal) ** GAMMA_24


def gamma24_oetf(light: float) -> float:
    """`gamma24_eotf` 的逆。两个指数一边一个，别对调——对调的那次记在 `bt709_oetf` 的说明里。"""
    return _clamp(light) ** (1 / GAMMA_24)


# 折叠那一步（抬进线性光 → 乘九个数 → 落回信号）按哪档曲线，可选的就这两档，名字只在这里写一次。
# 分叉是量出来的：同一个名字，链子那端（`grade.GAMMA_BY_SPACE`）按纯幂 2.4 解，容器那一格本来的
# 意思按分段 0.45 解，8 位上最坏差 27.2 阶（`tests/primariestags_check.py` 的 `curve_suite`）；
# 而随包那支 FFmpeg 的 zscale 把 `bt709` 实现成纯幂 2.4——逐格差 0.011 阶，与分段差 18.5 阶
# （`agentcut-验收脚本/zscale_curve_1161.py`）。哪一条才对，说的是「那幅像素实际是谁编的」，
# 引擎不替某一档素材猜，所以这一格交给人和 Agent 声明。默认仍取分段那一条：1.153／1.156／1.159
# 那几批交付实测全是按它量的，改默认等于把已经交出去的成片重算一遍。
TRANSFER_CURVES: dict[str, dict] = {
    "bt709": {
        "label": "BT.709 分段曲线（容器那一格本来的意思）",
        "eotf": bt709_eotf,
        "oetf": bt709_oetf,
    },
    "gamma24": {
        "label": "纯幂 2.4（链子里 rec709 用的那一条）",
        "eotf": gamma24_eotf,
        "oetf": gamma24_oetf,
    },
}
DEFAULT_FOLD_TRANSFER = "bt709"
FOLD_TRANSFERS: tuple[str, ...] = tuple(TRANSFER_CURVES)


def transfer_pair(name: str) -> tuple[Callable[[float], float], Callable[[float], float]]:
    """那一档曲线的正反两个方向。认不得的名字点名拒绝，并把名单一起交回去。"""
    row = TRANSFER_CURVES.get(name)
    if row is None:
        raise ValueError(
            "折叠那一步只认 "
            + "、".join(FOLD_TRANSFERS)
            + f"（名单在 gamut，别处不另写一份），来的是 {name}"
        )
    return row["eotf"], row["oetf"]


def fold_transfer_rows() -> list[dict]:
    """给人和 Agent 的那张表：id 加那句「这一档是谁」，界面不许自己再抄一份句子。"""
    return [{"id": name, "label": str(TRANSFER_CURVES[name]["label"])} for name in FOLD_TRANSFERS]


# 浏览器那两条每通道表与 `grade.grade_tables` 那张同为 256 格——同一把尺，两处不该分家。
PREVIEW_TABLE_SIZE = 256


def transfer_tables(
    name: str = DEFAULT_FOLD_TRANSFER, size: int | None = None
) -> tuple[list[float], list[float]]:
    """把声明的那档曲线切成两张每通道表：抬进线性光的那一张与落回信号的那一张。

    换基色那九个数是乘在**线性光**上的（`delivery_cube` 就是这个形状：eotf → 矩阵 → oetf）。浏览器
    画不出立方体，但画得出「每通道表 → 通道混合 → 每通道表」这一串，所以折到监视器那一趟交三段：
    而不是直接把九个数乘在存储值上——后者本轮量到最坏 71 阶偏差（(105, 254, 210) 的蓝被
    推成 0），而 256 格这两张表的插值地板只有 1 阶。
    """
    eotf, oetf = transfer_pair(name)
    size = size if size is not None else preview_cells(name)
    decode = [round(eotf(index / (size - 1)), 9) for index in range(size)]
    encode = [round(oetf(index / (size - 1)), 9) for index in range(size)]
    return decode, encode


# 折叠这一档怎么算，写在同一张表里：立方体还是链条、预览那两张表给几格。三个数都是量回来的
# （`agentcut-验收脚本/fold_routes_1162.py` 与 `preview_density_1162.py`，20,012 个颜色，期望一律
# 取「板上那同一份整数按该档解析折一次」）：
#   · 立方体 33³ + tetrahedral：分段 3 阶、γ2.4 15 阶；65³ 只降到 2／9 阶而文本 7.2 MB；
#   · 链条（zscale 抬线性 → colorchannelmixer 那九个数 → zscale 落回，16 位中间量）：γ2.4 4 阶；
#     分段那一条**走不了**——随包 FFmpeg 的 zscale 把容器那一格实现成纯幂 2.4（1.160 量到差 0.011
#     阶），它念不出分段，所以那一档只有立方体可走；
#   · 预览那两张表的格数：分段 256 格地板 1 阶（1.159 就是照这个定的），γ2.4 同样 256 格是 8 阶、
#     1024 格 5 阶、4096 格 3 阶——取 1024，因为再往上每多四倍只换一阶，而清单要带着这些数走线。
# `route` 与 `trc` 只说导出那一路；`chain` 必须配一个 zscale 念得出的 TRC 名，立方体那一路给 None。
FOLD_ROUTES: dict[str, dict] = {
    "bt709": {"route": "cube", "trc": None, "preview_cells": 256},
    "gamma24": {"route": "chain", "trc": "bt709", "preview_cells": 1024},
}


def fold_route(name: str) -> str:
    """导出那一路走立方体还是走链条。认不得的名字照名拒绝。"""
    row = FOLD_ROUTES.get(name)
    if row is None:
        raise ValueError(
            "折叠那一路只认 "
            + "、".join(FOLD_TRANSFERS)
            + f"（表在 gamut，别处不另写），来的是 {name}"
        )
    return str(row["route"])


def fold_trc(name: str) -> str:
    """链条那一路要念给 zscale 的 TRC 名；立方体那一路没有这个名字。"""
    row = FOLD_ROUTES[name]
    trc = row["trc"]
    if trc is None:
        raise ValueError(f"{name} 这一档走不了链条：随包 FFmpeg 念不出这条曲线")
    return str(trc)


def preview_cells(name: str) -> int:
    """预览那两张每通道表给几格。默认那条沿用 1.159 定的 256 格，一字不改。"""
    return int(FOLD_ROUTES.get(name, {"preview_cells": PREVIEW_TABLE_SIZE})["preview_cells"])


def primaries_mix_expression(matrix: list[list[float]]) -> str:
    """把九个系数写成 FFmpeg 的 `colorchannelmixer` 选项串（选项名＝输出通道＋输入通道）。"""
    return ":".join(
        f"{'rgb'[row]}{'rgb'[col]}={matrix[row][col]:.9f}" for row in range(3) for col in range(3)
    )


# 33^3 ≈ 3.6 万格、文本 947 KB（65^3 要 7.2 MB，129^3 上百 MB，每张交付目录都装不下）。
# 这一档不是拍的：格子中点与两端平均的最大差（插值的地板）在 33^3 上是 0.17 阶，65^3 上是
# 0.07 阶——差别在交付上量不出来（同一份渐变在 65/33/17/9 格上都量到 7 阶，那 7 阶是有损编码
# 器在奈奎斯特图案上的账）。地板由 `tests/colour_tag_check.py` 的 cube 档判在 0.5 阶以内。
DELIVERY_CUBE_SIZE = 33


def delivery_cube(
    source: str,
    target: str,
    size: int = DELIVERY_CUBE_SIZE,
    curve: Callable[[float], float] = bt709_eotf,
    inverse: Callable[[float], float] = bt709_oetf,
) -> str:
    """把「换基色」那一步写成 FFmpeg 认得的 `.cube`：每一格都是标准算式本身。

    为什么不直接写 `colorchannelmixer`：那一站乘的是**存储值**，而基色转换必须在线性光里做；
    1.152 实测「zscale 进线性 → colorchannelmixer → 回 709」这一对在 16 位上仍与标准算式差
    3–7 阶，而按这张表切的立方体交出的折叠与独立预测逐位相同。矩阵出自本模块的
    `primaries_matrix`（`tests/gamut_check.py` 已经用色度坐标那条独立路量过它），曲线出自上面
    那一对，与容器声明的那一档同一条。`.cube` 的既定次序是红变化最快、蓝最慢，与
    `grade.parse_3d_cube` 的读法同一句。
    """
    matrix = primaries_matrix(source, target)
    lines = [
        f'TITLE "AgentCut {source} -> {target} primaries"',
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    top = size - 1
    for blue in range(size):
        for green in range(size):
            for red in range(size):
                encoded = (red / top, green / top, blue / top)
                light = [
                    sum(matrix[row][k] * curve(value) for k, value in enumerate(encoded))
                    for row in range(3)
                ]
                lines.append(" ".join(f"{_clamp(inverse(value)):.6f}" for value in light))
    return "\n".join(lines) + "\n"
