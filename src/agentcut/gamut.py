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
"""

from __future__ import annotations

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
    "p3-dci": (
        ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
        (0.3127, 0.3290),
        "gamma22",
    ),
    "display-p3": (
        ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
        (0.3127, 0.3290),
        "srgb",
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
        "id": "p3dci_to_rec709",
        "label": "DCI-P3 → Rec.709（影院母带到电视）",
        "source": "p3-dci",
        "target": "rec709",
    },
    {
        "id": "rec709_to_p3dci",
        "label": "Rec.709 → DCI-P3（电视到影院）",
        "source": "rec709",
        "target": "p3-dci",
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
