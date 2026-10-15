"""1.161 折叠那一步走哪档曲线：名单、默认不动、图里那张立方体、落点的阶数。

四件事各钉一处：

1. **名单只有一个主人。** `capabilities.fold_transfers` 交的就是
   `gamut.TRANSFER_CURVES` 的 id 与那句「这一档是谁」；契约只认这一份，`srgb` 这种
   本轮没对过表的名字点名拒收（版本不涨、字也不落库）。默认 `bt709` 就是 1.153
   以来一直在用的那一条：把这一格删回「没写过」，预览清单与那张立方体逐字节回到
   原样——旧工程的画面不许被一个新字段改掉。
2. **两档不是同一条曲线。** 纯幂 2.4 与分段 0.45 在 256 格那张抬光的表上最坏差
   18.475 阶，33³ 的 35,937 格里 35,524 格被折成不同的数。哪天这两句不成立，这条红。
3. **图里那一趟跟着这一格走。** 同一份工程（工程基色 p3-d65、交付标记 bt2020）只改
   `fold_transfer`：导出的立方体逐字等于 `gamut.delivery_cube(工程, 容器, 那档正反两个
   方向)`，两档互不相同；预览那两级表等于 `gamut.transfer_tables(那一档)`，滤镜 id 跟着变。
4. **落点量的是配对。** 夹具由门禁自己按公布常数造（不读产品那条曲线）：同一幅颜色按某一档
   存成 P3-D65 的一帧，再交给随包 FFmpeg 的 `lut3d=…:interp=tetrahedral` 折回 709，与「拿板上
   那同一份整数、按同一档曲线解析折一次」的期望比——**声明对了差 3 阶（分段）／15 阶（γ2.4，
   那张 33³ 的格子在这条更陡的曲线上插值更吃亏），声明错了差 10 阶／55 阶**。两个方向都跑，
   所以钉的是配对，不是某一条曲线更好；而配对剩下的那一截是立方体那一级的插值地板，不是这一格。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import (
    SCHEMA_VERSION,
    ClipColor,
    Project,
    capabilities,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.gamut import (
    DEFAULT_FOLD_TRANSFER,
    FOLD_TRANSFERS,
    TRANSFER_CURVES,
    delivery_cube,
    fold_route,
    fold_trc,
    preview_cells,
    primaries_matrix,
    primaries_mix_expression,
    transfer_pair,
    transfer_tables,
)
from agentcut.grade import GAMMA_BY_SPACE, preview_grade
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan, fold_stage

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-source-quality"
CURVE = {
    "kind": "curve",
    "channel": "rgb",
    "points": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.28}, {"x": 1.0, "y": 1.0}],
}
CUBE_CELLS = 35937  # 33³，`gamut.DELIVERY_CUBE_SIZE` 那一档
PLATE_W = 8

# 这两把尺是这里自己写的，用的是公布常数：α=1.099、β=0.099、编码侧指数 0.45、
# 线性段斜率 4.5，以及纯幂 2.4。不 import `gamut.bt709_*`／`gamma24_*`——那两条曲线
# 正是本轮要测的东西，用它们造夹具又用它们算基准，等于让地面跟着尺子一起动。
PIECE_ALPHA, PIECE_BETA = 1.099, 0.099
PIECE_GAMMA, PIECE_SLOPE = 0.45, 4.5
PIECE_LIGHT_TURN, PIECE_SIGNAL_TURN = 0.018, 0.018 * 4.5
POWER = 2.4


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def piece_eotf(signal: float) -> float:
    return (
        signal / PIECE_SLOPE
        if signal <= PIECE_SIGNAL_TURN
        else ((signal + PIECE_BETA) / PIECE_ALPHA) ** (1 / PIECE_GAMMA)
    )


def piece_oetf(light: float) -> float:
    return (
        PIECE_SLOPE * light
        if light < PIECE_LIGHT_TURN
        else PIECE_ALPHA * light**PIECE_GAMMA - PIECE_BETA
    )


def power_eotf(signal: float) -> float:
    return clamp01(signal) ** POWER


def power_oetf(light: float) -> float:
    return clamp01(light) ** (1 / POWER)


ANCHORS = {"bt709": (piece_eotf, piece_oetf), "gamma24": (power_eotf, power_oetf)}

# 八格：亮、暗、饱和、中性都要有——折叠的错在最暗与最饱和那一头最藏不住（1.153 那个
# 85 阶就是从「碰到色域边界被夹成 0」那里露出来的）。
PLATE_CELLS = [
    (105, 254, 210),
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (12, 34, 56),
    (128, 128, 128),
    (6, 6, 6),
    (250, 250, 250),
]


def run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, check=False, cwd=str(cwd) if cwd else None)


def vocabulary_suite() -> list[dict]:
    rows = capabilities()["fold_transfers"]
    assert [row["id"] for row in rows] == list(FOLD_TRANSFERS), (
        f"能力表交的曲线名单与 gamut 那张表不一致：{rows} vs {list(FOLD_TRANSFERS)}"
    )
    assert [row["label"] for row in rows] == [
        str(TRANSFER_CURVES[name]["label"]) for name in FOLD_TRANSFERS
    ], f"能力表把那句「这一档是谁」写歪了：{rows}"
    assert DEFAULT_FOLD_TRANSFER == "bt709", f"默认档被挪走了：{DEFAULT_FOLD_TRANSFER}"
    assert rows[0]["id"] == DEFAULT_FOLD_TRANSFER, rows
    assert SCHEMA_VERSION == 21, f"schema 不再是 21：{SCHEMA_VERSION}"
    assert capabilities()["project_schema_version"] == 21
    # 链子那一侧的 `rec709` 是纯幂 2.4——那正是名单里必须有 `gamma24` 的理由。
    assert GAMMA_BY_SPACE["rec709"] == POWER, GAMMA_BY_SPACE["rec709"]
    assert "srgb" not in FOLD_TRANSFERS, (
        "sRGB 这一档本轮没重量（1.160 量到随包 FFmpeg 的 `iec61966-2-1` 自己就与 IEC 那条"
        "分段差 12.1 阶），名单里不许出现一条没对过表的曲线"
    )
    for name in FOLD_TRANSFERS:
        eotf, oetf = transfer_pair(name)
        assert abs(oetf(eotf(0.5)) - 0.5) < 1e-9, f"{name} 那两个方向不互逆"
        assert abs(eotf(oetf(0.5)) - 0.5) < 1e-9, f"{name} 那两个方向不互逆"
    refused = None
    try:
        transfer_pair("iec61966-2-1")
    except ValueError as caught:
        refused = str(caught)
    assert refused and "bt709" in refused and "gamma24" in refused, refused
    return rows


def fork_suite() -> tuple[float, int]:
    """两档差多少：同一把 256 步的尺上最坏的阶数，与那张立方体里被改动的格数。

    两条表各有各的格数（γ2.4 那条 1.162 起换密表），所以这里比的是**两条曲线**，不是两张表——
    表长不一样时拿 zip 比表，量的就成了「两把尺的刻度不一样」这件事。
    """
    worst = max(
        abs(ANCHORS["bt709"][0](index / 255.0) - ANCHORS["gamma24"][0](index / 255.0)) * 255
        for index in range(256)
    )
    for name in FOLD_TRANSFERS:
        decode, encode = transfer_tables(name)
        top = len(decode) - 1
        assert len(decode) == len(encode) == preview_cells(name), (
            f"{name} 的预览表不是那张表给的格数：{len(decode)} vs {preview_cells(name)}"
        )
        for index in range(len(decode)):
            cell = index / top
            eotf, oetf = ANCHORS[name]
            assert abs(decode[index] - eotf(cell)) < 5e-10, (
                f"{name} 抬光表第 {index} 格不是那条公布曲线切的（{decode[index]}）"
            )
            assert abs(encode[index] - oetf(cell)) < 5e-10, (
                f"{name} 落回那张表第 {index} 格不是那条公布曲线切的（{encode[index]}）"
            )
    assert worst > 15.0, (
        f"两档曲线只差 {worst:.3f} 阶了？那这条分叉可能已被统一，1.153/1.156/1.159 那几批"
        "的账与这条门禁要一起重量"
    )
    cube_piece = delivery_cube("p3-d65", "rec709", curve=piece_eotf, inverse=piece_oetf)
    cube_power = delivery_cube("p3-d65", "rec709", curve=power_eotf, inverse=power_oetf)
    cells_piece = cube_piece.splitlines()[4:]
    cells_power = cube_power.splitlines()[4:]
    assert len(cells_piece) == len(cells_power) == CUBE_CELLS, (
        f"两张立方体的格数不再是 33³：{len(cells_piece)} / {len(cells_power)}"
    )
    moved = sum(1 for a, b in zip(cells_piece, cells_power, strict=True) if a != b)
    assert moved > CUBE_CELLS // 2, (
        f"两张立方体只有 {moved} 格不同（共 {CUBE_CELLS}）：这一格改的到底是什么"
    )
    return worst, moved


class _StubPlan:
    """`fold_stage` 只要一个能收 `text_files` 的对象，这里不建整张计划。"""

    def __init__(self) -> None:
        self.text_files: dict[str, str] = {}


def product_fold(
    curve: str, pixels: bytes, folder: Path, source: str, target: str, route=None
) -> bytes | None:
    """把**产品那一条编译法**（`route=None` 时由 `gamut.FOLD_ROUTES` 决定）喂给随包 FFmpeg。

    `route` 只给对照那一次用：同一个 `fold_stage` 编另一条路，两条路各跑一遍——比的是同一段图
    在同一块板上的两种走法，而不是两种写法各自的手感。走不通（`fold_trc` 给 None，即随包
    FFmpeg 念不出那条曲线）就交回 None：那是一条测出来的事实，不是崩溃。
    """
    plan = _StubPlan()
    try:
        stage = fold_stage(plan, source, target, curve, "gbrp", route)
    except ValueError:
        return None
    for name, body in plan.text_files.items():
        (folder / name).write_text(body, encoding="utf-8")
    plate = folder / f"prec-{curve}-{source}-{target}-{route or 'own'}.rgb"
    plate.write_bytes(pixels)
    out = folder / f"export-{curve}-{source}-{target}-{route or 'own'}.rgb"
    made = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{PLATE_W}x{len(PLATE_CELLS)}",
            "-i",
            plate.name,
            "-vf",
            f"format=gbrp,{stage}format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            out.name,
        ],
        cwd=folder,
    )
    assert made.returncode == 0, made.stderr[-400:].decode(errors="replace")
    data = out.read_bytes()
    assert len(data) == len(PLATE_CELLS) * PLATE_W * 3, len(data)
    return data


def preview_fold(plate: bytes, name: str, matrix) -> bytes:
    """浏览器那一端做的事：读交出去的那两张表（线性插值）、乘那九个数、再取整。"""
    decode, encode = transfer_tables(name)
    top = len(decode) - 1

    def read(table: list[float], value: float) -> float:
        position = clamp01(value) * top
        low = min(int(position), top - 1)
        rest = position - low
        return table[low] * (1 - rest) + table[low + 1] * rest

    out = bytearray()
    for index in range(0, len(plate), 3):
        linear = [read(decode, plate[index + channel] / 255.0) for channel in range(3)]
        middle = [
            clamp01(sum(matrix[row][column] * linear[column] for column in range(3)))
            for row in range(3)
        ]
        out.extend(round(read(encode, value) * 255) for value in middle)
    return bytes(out)


def precision_suite(folder: Path) -> dict:
    """两端的地板、两端互差、按另一档声明的代价，以及**两条编译法在同一块板上的对照**。

    对照要跑两块板：`p3-d65→rec2020` 是放宽（九个系数几乎全正，格间插值没地方放大），
    `rec2020→p3-d65` 是收窄（一行里 −0.02·R 与 1.03·G 相消，那才是立方体的考场）。
    只在放宽那块上比，两条路都是 1 阶，路由表就等于没被证明过。
    """
    wide = primaries_matrix("p3-d65", "rec2020")
    deep = primaries_matrix("rec2020", "p3-d65")
    other = lambda name: "cube" if fold_route(name) == "chain" else "chain"  # noqa: E731
    worst = lambda a, b: max(abs(x - y) for x, y in zip(a, b, strict=True))  # noqa: E731
    reported: dict[str, tuple] = {}
    for name in FOLD_TRANSFERS:
        plate = fold_pixels(name)
        expected = analytic_fold(plate, ANCHORS[name], wide)
        exported = product_fold(name, plate, folder, "p3-d65", "rec2020")
        declared_wrong = product_fold(
            [item for item in FOLD_TRANSFERS if item != name][0], plate, folder, "p3-d65", "rec2020"
        )
        preview = preview_fold(plate, name, wide)
        narrow_plate = fold_pixels(name, "rec2020")
        narrow_expected = analytic_fold(narrow_plate, ANCHORS[name], deep)
        shipped_deep = product_fold(name, narrow_plate, folder, "rec2020", "p3-d65")
        against_deep = product_fold(name, narrow_plate, folder, "rec2020", "p3-d65", other(name))
        reported[name] = (
            worst(preview, expected),
            worst(exported, expected),
            worst(preview, exported),
            worst(declared_wrong, expected),
            None if against_deep is None else worst(against_deep, narrow_expected),
            worst(shipped_deep, narrow_expected),
        )
    return reported


def default_suite() -> None:
    """默认那一档必须与「新字段不存在」逐字节相同——旧工程的画面不许被新字段改掉。"""
    assert transfer_tables() == transfer_tables("bt709"), "默认那条曲线不再是名单第一行那一条"
    assert len(transfer_tables()[0]) == 256 == preview_cells("bt709"), (
        "默认那一条的预览表不再是 1.159 定的 256 格——旧工程的清单字节被动了"
    )
    assert preview_cells("gamma24") > 256, (
        "γ2.4 又用回 256 格了？本轮在这条曲线上量到的地板是 8 阶，别把量过的退回去"
    )
    eotf, oetf = transfer_pair(DEFAULT_FOLD_TRANSFER)
    assert delivery_cube("p3-d65", "rec709") == delivery_cube(
        "p3-d65", "rec709", curve=eotf, inverse=oetf
    ), "默认那张立方体不再是分段那条曲线切的一张"
    plain = ClipColor(exposure=0.0, contrast=1.0, saturation=1.0, grade=[CURVE])
    assert preview_grade(plain, "p3-d65") == preview_grade(
        plain, "p3-d65", DEFAULT_FOLD_TRANSFER
    ), "显式写默认档改了预览清单——那默认值就不是「老样子」"
    drawn = preview_grade(plain, "p3-d65", "gamma24")
    assert drawn is not None and [stage["type"] for stage in drawn["stages"]][-3:] == [
        "lut",
        "matrix",
        "lut",
    ], drawn


def fold_pixels(stored_name: str, source: str = "p3-d65") -> bytes:
    """把八格参考颜色按那一档曲线搬进 `source` 那一档存起来：每行一格，横向铺满 8 列。"""
    load, save = ANCHORS[stored_name]
    widen = primaries_matrix("rec709", source)
    frame = bytearray()
    for cell in PLATE_CELLS:
        linear = [load(value / 255.0) for value in cell]
        moved = [
            sum(widen[row][column] * linear[column] for column in range(3)) for row in range(3)
        ]
        stored = [round(clamp01(save(clamp01(value))) * 255) for value in moved]
        for _ in range(PLATE_W):
            frame.extend(bytes(stored))
    return bytes(frame)


NARROW = primaries_matrix("p3-d65", "rec709")


def analytic_fold(plate: bytes, curve, matrix=None) -> bytes:
    """把板上那些**整数**存储值按这一档曲线折一次：门禁自己算的那一份期望。

    基准读的是板上那同一个整数，不是「最初那格颜色」——后者会被量化的条件数污染：P3-D65 里
    (255,0,0) 存成 (235,62,47)，折回 709 时绿通道是 −0.042·R + 1.042·G 两个大数相消，板上
    半个量化台阶在这里被放大成十几阶，那是夹具的账，不是这一格声明的账。
    """
    load, save = curve
    out = bytearray()
    for index in range(0, len(plate), 3):
        linear = [load(plate[index + channel] / 255.0) for channel in range(3)]
        folded = [
            sum((matrix or NARROW)[row][column] * linear[column] for column in range(3))
            for row in range(3)
        ]
        out.extend(bytes(round(clamp01(save(clamp01(value))) * 255) for value in folded))
    return bytes(out)


def ff_fold(folder: Path, plate: str, fold_name: str) -> bytes:
    """把板上那一帧交给随包 FFmpeg 的 `lut3d`（tetrahedral），交回读回来的字节。"""
    cube = folder / f"fold-{fold_name}.cube"
    cube.write_text(
        delivery_cube(
            "p3-d65",
            "rec709",
            curve=ANCHORS[fold_name][0],
            inverse=ANCHORS[fold_name][1],
        ),
        encoding="utf-8",
    )
    out = folder / f"out-{plate}-{fold_name}.rgb"
    made = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{PLATE_W}x{len(PLATE_CELLS)}",
            "-i",
            plate,
            "-vf",
            f"format=gbrp,lut3d=file={cube.name}:interp=tetrahedral,format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            out.name,
        ],
        cwd=folder,
    )
    assert made.returncode == 0, made.stderr[-400:].decode(errors="replace")
    data = out.read_bytes()
    assert len(data) == len(PLATE_CELLS) * PLATE_W * 3, len(data)
    return data


def landing_suite(folder: Path) -> dict[str, tuple[int, int]]:
    """板上像素按哪档曲线存，就该按那一档声明：对上的差几阶、对不上的差几阶。"""
    reported: dict[str, tuple[int, int]] = {}
    for stored_name in FOLD_TRANSFERS:
        plate = folder / f"in-{stored_name}.rgb"
        pixels = fold_pixels(stored_name)
        plate.write_bytes(pixels)
        expected = analytic_fold(pixels, ANCHORS[stored_name])
        other = [name for name in FOLD_TRANSFERS if name != stored_name][0]
        matched = max(
            abs(a - b)
            for a, b in zip(ff_fold(folder, plate.name, stored_name), expected, strict=True)
        )
        wrong = max(
            abs(a - b) for a, b in zip(ff_fold(folder, plate.name, other), expected, strict=True)
        )
        reported[stored_name] = (matched, wrong)
    return reported


def http_suite() -> dict[str, str]:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        folder = root / "media"
        folder.mkdir()
        exports = root / "exports"
        run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0xB45032:s={SRC_W}x{SRC_H}:r=30:d=1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv444p",
                "-r",
                "30",
                str(folder / "orange.mp4"),
            ]
        )
        db = root / "fc.sqlite3"
        media = MediaService(root / "media.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        runtime = JobRuntime(db, FFMPEG, exports, [exports, folder])
        token = "f" * 48
        app = create_app(db, token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            probe = client.post(
                "/v1/media/import", json={"path": str(folder / "orange.mp4")}
            ).json()
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "fc-new",
                    "name": "折叠曲线",
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            assert created["settings"]["fold_transfer"] == DEFAULT_FOLD_TRANSFER, (
                f"新建工程的这一格不是默认档：{created['settings']}"
            )
            path = f"/v1/projects/{created['id']}"
            state = {"revision": created["revision"]}
            counter = {"n": 0}
            seed = client.post(
                path + "/edits",
                json={
                    "request_id": "fc-seed",
                    "expected_revision": state["revision"],
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a0",
                            "label": "orange",
                            "probe_id": probe["id"],
                            "verified": probe["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c0",
                                "asset_id": "a0",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": T,
                            },
                        },
                        {
                            "op": "clip.color",
                            "clip_id": "c0",
                            "color": {"exposure": 0.0, "grade": [CURVE]},
                        },
                    ],
                },
            )
            assert seed.status_code == 200, seed.text
            state["revision"] = seed.json()["project"]["revision"]

            def settings_now() -> dict:
                return dict(client.get(path).json()["settings"])

            def write(**changes) -> None:
                counter["n"] += 1
                answer = client.post(
                    path,
                    json={
                        "request_id": f"fc-set-{counter['n']}",
                        "expected_revision": state["revision"],
                        "settings": {
                            **settings_now(),
                            "working_primaries": "p3-d65",
                            **changes,
                        },
                    },
                )
                assert answer.status_code == 200, answer.text
                state["revision"] = answer.json()["project"]["revision"]

            def graph() -> tuple[str, str]:
                project = Project.model_validate(client.get(path).json())
                plan = compile_render_plan(project, PRESET, colour_tag="bt2020")
                names = sorted(key for key in plan.text_files if key.startswith("primaries-"))
                return "\n".join(plan.filters), "".join(plan.text_files[key] for key in names)

            def preview() -> tuple[str, list[list[float]]]:
                grade = client.get(path + "/preview-manifest").json()["clips"]["c0"]["grade"]
                tables = [stage["r"] for stage in grade["stages"] if stage["type"] == "lut"]
                return grade["id"], tables

            before = state["revision"]
            bad = client.post(
                path,
                json={
                    "request_id": "fc-bad",
                    "expected_revision": before,
                    "settings": {**settings_now(), "fold_transfer": "srgb"},
                },
            )
            assert bad.status_code == 422, bad.text
            assert "srgb" in bad.text, bad.text[:300]
            assert "gamma24" in bad.text, "拒绝必须把走得通的那几档念出来"
            assert client.get(path).json()["revision"] == before, "被拒的那一次涨了版本"
            assert settings_now()["fold_transfer"] == DEFAULT_FOLD_TRANSFER, (
                "被拒的那一次把认不得的名字写下去了"
            )

            seen: dict[str, tuple[str, str]] = {}
            ids: dict[str, str] = {}
            for name in FOLD_TRANSFERS:
                write(fold_transfer=name)
                filters, cubes = graph()
                eotf, oetf = ANCHORS[name]
                if fold_route(name) == "cube":
                    assert "lut3d=file=primaries-" in filters, filters[:400]
                    assert cubes == delivery_cube("p3-d65", "rec2020", curve=eotf, inverse=oetf), (
                        f"{name}：图里那张立方体不是按这一档曲线切的那一张"
                    )
                else:
                    assert "lut3d=file=primaries-" not in filters, (
                        f"{name}：这一档改走链条了，图里却还挂着一张立方体——凭空多的一层"
                    )
                    assert cubes == "", f"{name}：链条那一路不该往作业目录写立方体"
                    mix = primaries_mix_expression(primaries_matrix("p3-d65", "rec2020"))
                    trc = fold_trc(name)
                    assert f"colorchannelmixer={mix}" in filters, (
                        f"{name}：链条中间那九个数不是 gamut.primaries_matrix 算的那一份"
                    )
                    assert f"zscale=transferin={trc}:transfer=linear" in filters, filters[:400]
                    assert f"zscale=transferin=linear:transfer={trc}" in filters, filters[:400]
                pid, tables = preview()
                decode, encode = transfer_tables(name)
                assert tables[1:] == [decode, encode], (
                    f"{name}：预览链子最后那两张表不是 transfer_tables(这一档) 切的那两张"
                )
                seen[name], ids[name] = (filters, cubes), pid
            assert seen["bt709"][0] != seen["gamma24"][0], (
                "换了曲线而导出图一个字没变——那这一格是摆设"
            )
            assert ids["bt709"] != ids["gamma24"], (
                "预览那两级表换了而滤镜 id 没变——浏览器认 id，两张图会共用同一个 filter"
            )

            left = settings_now()
            left.pop("fold_transfer")
            counter["n"] += 1
            answer = client.post(
                path,
                json={
                    "request_id": f"fc-drop-{counter['n']}",
                    "expected_revision": state["revision"],
                    "settings": {**left, "working_primaries": "p3-d65"},
                },
            )
            assert answer.status_code == 200, answer.text
            state["revision"] = answer.json()["project"]["revision"]
            assert settings_now()["fold_transfer"] == DEFAULT_FOLD_TRANSFER
            _, cubes = graph()
            pid, _ = preview()
            assert cubes == seen["bt709"][1], "把这一格删回去，立方体没回到默认档那一张"
            assert pid == ids["bt709"], "把这一格删回去，预览清单没回到默认档那一份字节"
            return {name: seen[name][0] for name in FOLD_TRANSFERS}


def main() -> None:
    rows = vocabulary_suite()
    worst, moved = fork_suite()
    default_suite()
    with tempfile.TemporaryDirectory() as scratch:
        landed = landing_suite(Path(scratch))
        floors = precision_suite(Path(scratch))
    graphs = http_suite()
    print(
        "   名单："
        + "、".join(f"{row['id']}（{row['label']}）" for row in rows)
        + f"，默认 {DEFAULT_FOLD_TRANSFER}，schema {SCHEMA_VERSION}"
    )
    print(
        f"   两条曲线在抬光那张 256 格的表上最坏差 {worst:.3f} 阶，"
        f"33³ 的 {CUBE_CELLS} 格里 {moved} 格被折成不同的数"
    )
    print(
        "   落点（板上像素按某一档存，期望按同一档算）："
        + "；".join(
            f"按 {name} 存 → 声明对了差 {matched} 阶、声明错了差 {wrong} 阶"
            for name, (matched, wrong) in landed.items()
        )
    )
    for name, (matched, wrong) in landed.items():
        # 配对那一对剩的是立方体那一级的插值地板：同一张 33³ 的格子，分段那张在本夹具这八格上
        # 量到 3 阶，γ2.4 那张量到 15 阶（它的 eotf 在暗到中间那一段更陡，格与格之间线性插值
        # 更吃亏）。这不是「这一格声明错了」，所以判到 16 阶为止，而不是要求它是 0。
        assert matched <= 16, f"{name}：配对差到 {matched} 阶，已经不是插值地板：{landed}"
        assert wrong >= 10, f"{name}：配错只差 {wrong} 阶了？这条分叉要重新量，{landed}"
        assert wrong >= 2 * matched + 2, f"{name}：配对与配错的差距不再悬殊（{matched} vs {wrong}）"
    assert landed["gamma24"][1] > landed["bt709"][1], (
        f"两边走错曲线的代价不再分高矮（{landed}）——那「哪条更常是错的」这句话要重写"
    )
    print(
        "   两端的地板（期望＝同一份整数按该档解析折一次）："
        + "；".join(
            f"{name}：预览 {p} 阶／导出 {x} 阶／互差 {g} 阶／按另一档声明 {w} 阶"
            f"／收窄板上本路 {s} 阶" + ("、另一条走不通" if o is None else f"、另一条 {o} 阶")
            for name, (p, x, g, w, o, s) in floors.items()
        )
    )
    for name, (
        preview_worst,
        export_worst,
        gap,
        declared_wrong,
        other_route,
        shipped_deep,
    ) in floors.items():
        # 判的是「表示」那一级的地板：立方体 33³ 与每通道 256／1024 格都是近似。数来自
        # 本轮测量（分段：导出 3 阶、预览 1 阶；γ2.4：链条 4 阶、1024 格 5 阶），红起来的意思是
        # 「地板涨了或两端又分家」，不是我发明的容差。
        assert preview_worst <= 8, f"{name}：预览那一端 {preview_worst} 阶，{floors}"
        assert export_worst <= 8, f"{name}：导出那一端 {export_worst} 阶，这一路地板涨了：{floors}"
        assert gap <= 10, f"{name}：预览与导出互差 {gap} 阶，两端又分家了：{floors}"
        assert declared_wrong >= 10, (
            f"{name}：按另一档声明只差 {declared_wrong} 阶，要重量：{floors}"
        )
        assert declared_wrong >= 2 * export_worst + 2, (
            f"{name}：配对与配错的差距不再悬殊（{export_worst} vs {declared_wrong}）"
        )
        # 这一条是「选这一路」那句决定的凭据：同一段图、同一块板，两条编译法各跑一遍，
        # 交出去的那一条不许比另一条差。有人把 γ2.4 换回立方体、或把分段塞进链条，红的是这里。
        # 对照看的是**收窄**那块板：放宽那一头两条路都几乎没误差，比不出决定。
        if other_route is None:
            assert fold_route(name) == "cube", (
                f"{name}：另一条路对这一档走不通（随包 FFmpeg 念不出这条曲线），"
                "交出去的却不是唯一走得通的那一条"
            )
        else:
            assert shipped_deep <= other_route, (
                f"{name}：收窄那块板上交出去的那一路 {shipped_deep} 阶、另一条 {other_route} 阶——"
                "路由表选错了，这张表要重新量"
            )
    assert graphs["bt709"] != graphs["gamma24"]
    print(
        "PASS: 折叠曲线只认名单里那两档，认不得的点名拒收且不涨版本；默认那一档与「没写过」"
        "逐字节相同，旧工程画面不动；工程说了话，导出那张立方体与预览那两级表都按那一档切"
        "（两档交出的立方体与滤镜 id 都不相同）；落点钉的是配对——"
        + "、".join(
            f"{name} 对上 {matched} 阶／对不上 {wrong} 阶"
            for name, (matched, wrong) in landed.items()
        )
    )


main()
