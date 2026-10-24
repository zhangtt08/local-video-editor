"""色度键抠像：键必须真的在交付文件里抠出洞，而且预览读的是引擎那一份数。

一件事值不值得说「已实现」，判据是成片：一段绿幕压在一片蓝底上，挂了键之后成片里那一块
应该是**蓝**，不是绿，也不是黑。这一档因此逐点读交付文件的像素（EXR 序列，没有色度二次
采样，所以读回来就是导出的那一格），并且先读一遍夹具自己——夹具说红的地方读回来必须是
红的，否则下面那张表全是假的。

第二件事是「只有一处主人」：导出串里那两个数（`low`/`width`）与预览清单里交出去的那两个
数必须是同一次换算的结果，界面不许自己再算 `similarity - blend`。

第三件事是不许有第二种说法：没挂键的片段，编译出来的串里一个键的字节都不许出现。

1.277 把同一只手管到的第二件事也量在成片上：溢色抑制压的是键色里最亮那一条通道，压完那几
块板子的读数由这里**手算**给出（`SPILL_EXPECTED`），不从 `chroma_row` 反推自己；同时要求压完
比没压时更不绿——只比「两端一致」的话，两端一起什么都不做也能过关。
"""

import struct
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.compositing import chroma_row
from agentcut.contracts import (
    CHROMA_BLEND_DEFAULT,
    CHROMA_COLOR_DEFAULT,
    CHROMA_SIMILARITY_DEFAULT,
    CHROMA_SPILL_DEFAULT,
    SCHEMA_VERSION,
    ChromaKey,
    EditBatch,
    Project,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import chroma_stage, compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
PRESET = "exr-sequence"
SIZE = 64
SECONDS = 1.0
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
RED = (255, 0, 0)

# 三条靠近键色的带，距离分别是 15 / 23 / 31：默认档（相似度 0.12=30.6、柔和 0.05=12.75）
# 下应当是「全透 / 混在斜坡上 / 全不透」。
NEAR = [(0, 240, 0), (0, 232, 0), (0, 224, 0)]
NO_REFUSAL = "\u8fd9\u4e00\u79cd\u62d2\u6cd5\u6839\u672c\u6ca1\u6709\u53d1\u751f"
NO_RAMP = "\u8f6f\u8fb9\u584c\u4e0d\u6210\u659c\u5761"
BOXES = [
    (16, 16, 12, 12, RED),
    (32, 4, 4, 4, NEAR[0]),
    (40, 4, 4, 4, NEAR[1]),
    (48, 4, 4, 4, NEAR[2]),
]
PROBES = {
    "green field": (2, 2, GREEN, 0.0),
    "red subject": (20, 20, RED, 1.0),
    "key minus 15": (33, 5, NEAR[0], 0.0),
    "key minus 23": (41, 5, NEAR[1], None),
    "key minus 31": (49, 5, NEAR[2], 1.0),
}

# 1.277：溢色抑制在成片里的读数。这些数是一路**手算**出来的（不叫 `chroma_row` 反推自己）：
# 压的是绿那一通道，封顶 min(g, max(r,b))——这三块板子里 r 与 b 都是 0，所以封顶就是 0，
# 压一半就是把 g 折成一半；权重沿用上面那三档（全透 / 0.40392 / 全不透），底片是纯蓝。
#   key minus 23：0.40392 × 116 = 46.9，0.59608 × 255 = 152.0
#   key minus 31：224 × 0.5 = 112
SPILL = 0.5
SPILL_EXPECTED = {
    "green field": (0, 0, 255),
    "red subject": (255, 0, 0),
    "key minus 15": (0, 0, 255),
    "key minus 23": (0, 47, 152),
    "key minus 31": (0, 112, 0),
}


def run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(a) for a in args], capture_output=True, check=True, timeout=600
    )


def hex_of(rgb: tuple[int, int, int]) -> str:
    return f"0x{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def write_plate(target: Path, default: tuple[int, int, int], boxes=()) -> None:
    """一张实色 PNG；`boxes` 是 (x, y, w, h, rgb)。全部走 rgb24，不留 YUV 往返的余地。"""
    chain = f"color=c={hex_of(default)}:s={SIZE}x{SIZE}:r=25:d={SECONDS},format=rgb24"
    for x, y, w, h, rgb in boxes:
        chain += f",drawbox=x={x}:y={y}:w={w}:h={h}:c={hex_of(rgb)}:t=fill"
    run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", chain, "-frames:v", "1", target])


def read_png(path: Path) -> list[tuple[int, int, int]]:
    raw = run(
        [FFMPEG, "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    ).stdout
    return [struct.unpack_from("3B", raw, step * 3) for step in range(SIZE * SIZE)]


def at(pixels: list[tuple[int, int, int]], x: int, y: int) -> tuple[int, int, int]:
    return pixels[y * SIZE + x]


def check_fixture(folder: Path) -> None:
    """夹具先自证：说它是红的地方必须读回来是红的。"""
    plate = folder / "plate.png"
    write_plate(plate, GREEN, BOXES)
    pixels = read_png(plate)
    assert at(pixels, 2, 2) == GREEN, at(pixels, 2, 2)
    assert at(pixels, 20, 20) == RED, at(pixels, 20, 20)
    for (x, y, _, _, rgb), probe in zip(BOXES[1:], NEAR):
        assert at(pixels, x + 2, y + 2) == rgb, (probe, at(pixels, x + 2, y + 2))
    base = folder / "base.png"
    write_plate(base, BLUE)
    assert read_png(base)[0] == BLUE


def distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def weight_for(rgb: tuple[int, int, int], row: dict) -> float:
    d = distance(rgb, tuple(row["color"]))
    if not row["soft"]:
        return 1.0 if d >= row["high"] else 0.0
    if d <= row["low"]:
        return 0.0
    if d >= row["high"]:
        return 1.0
    return (d - row["low"]) / row["width"]


def client_for(folder: Path):
    media = MediaService(
        folder / "chroma-db.sqlite3", [folder], folder / "chroma-cache", FFMPEG, FFPROBE
    )
    runtime = JobRuntime(
        folder / "chroma-api.sqlite3",
        FFMPEG,
        folder / "deliverables",
        [folder / "deliverables"],
    )
    runtime.ensure_worker()
    token = "chromachek" + "e" * 52
    app = create_app(folder / "chroma-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


def seed_commands(green: dict, blue: dict, chroma: dict | None):
    """两条画面轨：底下一片蓝，上面一张绿幕板（`chroma` 给了就挂上键）。"""
    verified_green = green["verified"]
    verified_blue = blue["verified"]
    commands = [
        {"op": "track.add", "track": {"id": "under", "kind": "video", "name": "under"}},
        {"op": "track.add", "track": {"id": "over", "kind": "video", "name": "over"}},
        {
            "op": "asset.import",
            "asset_id": "blue",
            "label": "blue",
            "probe_id": verified_blue["probe_id"],
            "verified": verified_blue,
        },
        {
            "op": "asset.import",
            "asset_id": "green",
            "label": "green",
            "probe_id": verified_green["probe_id"],
            "verified": verified_green,
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "b",
                "asset_id": "blue",
                "track_id": "under",
                "position_ticks": 0,
                "duration_ticks": int(SECONDS * T),
            },
        },
    ]
    clip: dict = {
        "id": "g",
        "asset_id": "green",
        "track_id": "over",
        "position_ticks": 0,
        "duration_ticks": int(SECONDS * T),
    }
    if chroma is not None:
        clip["chroma"] = chroma
    commands.append({"op": "clip.add", "clip": clip})
    return commands


def export(client: TestClient, path: str, revision: int, name: str) -> list[tuple[int, int, int]]:
    request_id = "render-" + name.replace(".", "-")
    if not name.endswith(".exr"):
        name = f"{name}.exr"
    queued = client.post(
        path + "/renders",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "preset_id": PRESET,
            "filename": name,
        },
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()["job"]
    status = {}
    for _ in range(600):
        status = client.get("/v1/jobs/" + job["id"]).json()["job"]
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.2)
    assert status["status"] == "succeeded", status
    pattern = Path(status["output_path"])
    first = pattern.parent / pattern.name.replace("%06d", "000001")
    assert first.exists(), first
    raw = run(
        [FFMPEG, "-v", "error", "-i", first, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    ).stdout
    return [struct.unpack_from("3B", raw, step * 3) for step in range(SIZE * SIZE)]


def contract_suite() -> None:
    key = ChromaKey()
    row = chroma_row(key)
    assert key.color == CHROMA_COLOR_DEFAULT == "#00FF00", key.color
    assert key.similarity == CHROMA_SIMILARITY_DEFAULT, key.similarity
    assert key.blend == CHROMA_BLEND_DEFAULT, key.blend
    assert row["color"] == [0, 255, 0] and row["soft"] is True, row
    # 0.12 与 0.05 说的都是「满量程 255 上的那一段距离」：低门槛 17.85、高门槛 30.6。
    assert abs(row["low"] - 17.85) < 1e-6, "低门槛不是 0.12 与 0.05 折出来的"
    assert abs(row["high"] - 30.6) < 1e-6, "高门槛不是 0.12 折出来的"
    assert abs(row["width"] - 12.75) < 1e-6, row

    stage = chroma_stage(type("C", (), {"chroma": key})())
    assert stage.startswith("format=rgba,geq="), stage
    assert "pow(r(X,Y)-0,2)" in stage and "pow(g(X,Y)-255,2)" in stage, stage
    assert "-17.85)/12.75" in stage, NO_RAMP
    assert chroma_stage(type("C", (), {"chroma": None})()) == ""

    hard = chroma_row(ChromaKey(blend=0.0))
    assert hard["soft"] is False and hard["low"] == hard["high"], hard
    hard_stage = chroma_stage(type("C", (), {"chroma": ChromaKey(blend=0.0)})())
    assert "gte(sqrt(" in hard_stage and "clip(" not in hard_stage, hard_stage

    flipped = chroma_stage(type("C", (), {"chroma": ChromaKey(inverted=True)})())
    assert "(1-(clip(" in flipped, flipped

    for bad in ("green", "#00FF0", "#GGGGGG", "0x00FF00"):
        try:
            ChromaKey(color=bad)
        except Exception:
            continue
        raise AssertionError(f"键色的形状没守住：{bad}")
    for knob in ("similarity", "blend", "spill"):
        for bad in (-0.01, 1.01):
            try:
                ChromaKey(**{knob: bad})
            except Exception:
                continue
            raise AssertionError(f"{knob}={bad} 竟然收下了")
    assert SCHEMA_VERSION == 32, SCHEMA_VERSION


def spill_suite() -> None:
    """1.277：溢色抑制那一步——通道、份数、与「0 就是 1.276 那一格」。"""
    assert ChromaKey().spill == CHROMA_SPILL_DEFAULT == 0.0, ChromaKey().spill
    plain = chroma_stage(type("C", (), {"chroma": ChromaKey()})())
    at_zero = chroma_stage(type("C", (), {"chroma": ChromaKey(spill=0.0)})())
    assert plain == at_zero, "写了 0 的串与没写这一格的串不一样——升级动了老工程的编译串"
    assert "min(" not in plain, "没拧抑制的那一格也长了压颜色的式子"

    green = chroma_row(ChromaKey(spill=SPILL))
    assert green["spill"] == SPILL and green["spill_at"] == 1, green
    half = chroma_stage(type("C", (), {"chroma": ChromaKey(spill=SPILL)})())
    assert "g='g(X,Y)+(min(g(X,Y),max(r(X,Y),b(X,Y)))-g(X,Y))*0.5'" in half, half
    assert "r='r(X,Y)'" in half and "b='b(X,Y)'" in half, "压绿却动了另两条平面"
    assert half.count("geq=") == 1, "多压一次就多半趟滤镜"

    # 通道由键色里最亮那一条定；并列时按 R→G→B 取靠前那一条。
    cases = (("#FF0000", 0), ("#00FF00", 1), ("#0000FF", 2), ("#808080", 0), ("#004040", 1))
    for colour, want in cases:
        row = chroma_row(ChromaKey(color=colour, spill=0.5))
        assert row["spill_at"] == want, (colour, row["spill_at"], want)
        plane = ("r", "g", "b")[want]
        stage = chroma_stage(type("C", (), {"chroma": ChromaKey(color=colour, spill=0.5)})())
        assert f"{plane}='{plane}(X,Y)+(" in stage, (colour, stage)
    # 反选压的仍是同一条通道：那是「留着的那一圈也带着幕布色」的同一件事。
    flipped = chroma_stage(type("C", (), {"chroma": ChromaKey(spill=SPILL, inverted=True)})())
    assert "min(g(X,Y),max(r(X,Y),b(X,Y)))" in flipped and "(1-(clip(" in flipped, flipped


def graph_and_manifest(folder: Path) -> Project:
    """键的那两个数在两条腿上必须是同一份；没挂键的片段一个字节都不许多。"""
    app, token = client_for(folder)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        green = folder / "green.png"
        blue = folder / "blue.png"
        write_plate(green, GREEN, BOXES)
        write_plate(blue, BLUE)
        probed_green = client.post("/v1/media/import", json={"path": str(green)}).json()
        probed_blue = client.post("/v1/media/import", json={"path": str(blue)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "chroma",
                "settings": {
                    "width": SIZE,
                    "height": SIZE,
                    "frame_rate": {"numerator": 25, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        key = ChromaKey()
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": seed_commands(probed_green, probed_blue, key.model_dump()),
            },
        )
        assert seeded.status_code == 200, seeded.text
        body = seeded.json()["project"]
        project = Project.model_validate(body)
        assert project.clips["g"].chroma == key, project.clips["g"].chroma

        caps = client.get("/v1/capabilities").json()
        assert "clip.chroma" in caps["commands"], caps["commands"]
        assert caps["features"]["chroma_key"] is True, caps["features"]
        assert caps["features"]["chroma_spill"] is True, caps["features"]
        assert caps["limits"]["chroma_similarity_default"] == CHROMA_SIMILARITY_DEFAULT
        assert caps["limits"]["chroma_blend_default"] == CHROMA_BLEND_DEFAULT
        assert caps["limits"]["chroma_color_default"] == CHROMA_COLOR_DEFAULT
        assert caps["limits"]["chroma_spill_default"] == CHROMA_SPILL_DEFAULT

        plan = compile_render_plan(project, PRESET)
        graph = " ".join(plan.filters)
        row = chroma_row(key)
        assert f"-{row['low']:.6g})/{row['width']:.6g}" in graph, "编译串里那对数不是清单里那一份"

        manifest = client.get(path + "/preview-manifest").json()
        handed = manifest["clips"]["g"]["chroma"]
        assert handed == row, "预览清单没交出那一份键的数"
        assert manifest["clips"]["b"]["chroma"] is None, manifest["clips"]["b"]

        plain = client.post(
            path + "/edits",
            json={
                "request_id": "unkey",
                "expected_revision": project.revision,
                "commands": [{"op": "clip.chroma", "clip_id": "g", "chroma": None}],
            },
        ).json()
        bare = Project.model_validate(plain["project"])
        assert bare.clips["g"].chroma is None
        bare_graph = " ".join(compile_render_plan(bare, PRESET).filters)
        assert "pow(r(X,Y)" not in bare_graph, "没挂键的片段也长了键的字节"
        assert client.get(path + "/preview-manifest").json()["clips"]["g"]["chroma"] is None
        return project


def single_track_suite(folder: Path) -> None:
    """一条画面轨：挂了键才不许走 `cut` 那条链——这一判只有在这里才可能红。

    两条轨的工程本来就走叠层（`len(layers) > 1`），在那份工程上断言「mode 是 layered」永远不会红；
    所以这里量的是只有一条轨的那一份：没挂键时它确实是 `cut`，挂上键就必须换成 `layered`，
    而换过去的那条腿里才有人真的把 alpha 乘上去。
    """
    app, token = client_for(folder)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        green = folder / "single-green.png"
        write_plate(green, GREEN, BOXES)
        probed = client.post("/v1/media/import", json={"path": str(green)}).json()
        verified = probed["verified"]
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "single-new",
                "name": "chroma-single-track",
                "settings": {
                    "width": SIZE,
                    "height": SIZE,
                    "frame_rate": {"numerator": 25, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "single-seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "only", "kind": "video", "name": "only"}},
                    {
                        "op": "asset.import",
                        "asset_id": "green",
                        "label": "green",
                        "probe_id": verified["probe_id"],
                        "verified": verified,
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "g",
                            "asset_id": "green",
                            "track_id": "only",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        plain = Project.model_validate(seeded.json()["project"])
        plain_plan = compile_render_plan(plain, PRESET)
        plain_graph = " ".join(plain_plan.filters)
        assert plain_plan.mode == "cut", plain_plan.mode
        assert "pow(r(X,Y)" not in plain_graph, "单轨没挂键也长了键的字节"

        key = ChromaKey()
        wrote = client.post(
            path + "/edits",
            json={
                "request_id": "single-key",
                "expected_revision": plain.revision,
                "commands": [{"op": "clip.chroma", "clip_id": "g", "chroma": key.model_dump()}],
            },
        )
        assert wrote.status_code == 200, wrote.text
        keyed = Project.model_validate(wrote.json()["project"])
        keyed_plan = compile_render_plan(keyed, PRESET)
        row = chroma_row(key)
        assert keyed_plan.mode == "layered", "挂了键的单轨仍走 cut：那条链根本没有 alpha 这一趟"
        assert f"-{row['low']:.6g})/{row['width']:.6g}" in " ".join(keyed_plan.filters), (
            "编译串里那对数不是清单里那一份"
        )
        print(f"   单轨：没挂键走 {plain_plan.mode}，挂上键走 {keyed_plan.mode}")


def refusal_suite(folder: Path) -> None:
    """三种拒法：声音轨、文字层、越界——都点名，且都不许涨版本、不许写库。"""
    app, token = client_for(folder)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        green = folder / "green.png"
        write_plate(green, GREEN, BOXES)
        probed = client.post("/v1/media/import", json={"path": str(green)}).json()
        verified = probed["verified"]
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "chroma-refuse",
                "settings": {
                    "width": SIZE,
                    "height": SIZE,
                    "frame_rate": {"numerator": 25, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "v2"}},
                    {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
                    {
                        "op": "asset.import",
                        "asset_id": "green",
                        "label": "green",
                        "probe_id": verified["probe_id"],
                        "verified": verified,
                    },
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "snd",
                            "kind": "audio",
                            "label": "s",
                            "reference": "r",
                            "duration_ticks": T,
                        },
                    },
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "txt",
                            "kind": "text",
                            "label": "t",
                            "reference": "r",
                            "duration_ticks": T,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "pic",
                            "asset_id": "green",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "snd",
                            "asset_id": "snd",
                            "track_id": "a",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "cap",
                            "asset_id": "txt",
                            "track_id": "v2",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                            "text": {"body": "字"},
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        key = ChromaKey().model_dump()
        for clip_id in ("snd", "cap"):
            refused = client.post(
                path + "/edits",
                json={
                    "request_id": f"key-{clip_id}",
                    "expected_revision": revision,
                    "commands": [{"op": "clip.chroma", "clip_id": clip_id, "chroma": key}],
                },
            )
            assert refused.status_code == 422, (
                clip_id, NO_REFUSAL, refused.text[:200]
            )
            error = refused.json()["error"]
            assert error["code"] == "INVALID_CHROMA", "这一种拒法没有名字"
            assert error["details"]["clip_id"] == clip_id, error
            assert client.get(path).json()["revision"] == revision, "拒绝还涨了版本"
            print(f"   {clip_id} 被点名拒：{error['message']}")

        wrote = client.post(
            path + "/edits",
            json={
                "request_id": "key-pic",
                "expected_revision": revision,
                "commands": [{"op": "clip.chroma", "clip_id": "pic", "chroma": key}],
            },
        )
        assert wrote.status_code == 200, wrote.text
        after = wrote.json()["project"]
        assert after["clips"]["pic"]["chroma"] == key, after["clips"]["pic"]
        assert after["revision"] == revision + 1
        undone = client.post(
            path + "/restore",
            json={
                "request_id": "undo-key",
                "expected_revision": after["revision"],
                "target_revision": revision,
            },
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["project"]["clips"]["pic"]["chroma"] is None


def receipt_suite(folder: Path) -> None:
    """同一份载荷必须命中自己那笔回执；换了键色就是另一笔。

    `blur_check` 那两个 pre-1.64 摘要钉的是「新加一格不许把老回执劈成两半」；这一档钉的是
    另一半——**真的换了数**时不许还命中同一笔。两条一起才算说清了这一格进了指纹没有。
    1.277 又加一半：`spill` 在默认值时不许进指纹（老载荷重放命中自己），拧动了必须进。
    """
    app, token = client_for(folder)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        green = folder / "receipt-green.png"
        blue = folder / "receipt-blue.png"
        write_plate(green, GREEN, BOXES)
        write_plate(blue, BLUE)
        probed_green = client.post("/v1/media/import", json={"path": str(green)}).json()
        probed_blue = client.post("/v1/media/import", json={"path": str(blue)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "receipt-new",
                "name": "chroma-receipt",
                "settings": {
                    "width": SIZE,
                    "height": SIZE,
                    "frame_rate": {"numerator": 25, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "receipt-seed",
                "expected_revision": 0,
                "commands": seed_commands(probed_green, probed_blue, None),
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        key = ChromaKey().model_dump()
        payload = {
            "request_id": "receipt-key-once",
            "expected_revision": revision,
            "commands": [{"op": "clip.chroma", "clip_id": "g", "chroma": key}],
        }
        first = client.post(path + "/edits", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["replayed"] is False, first.json()
        landed = first.json()["project"]["revision"]
        again = client.post(path + "/edits", json=payload)
        assert again.status_code == 200, again.text
        assert again.json()["replayed"] is True, "同一份载荷没有命中自己那笔回执"
        assert again.json()["project"]["revision"] == landed, "重放还涨了一个版本"

        # 重放先看版本号再看回执，所以这里把 expected_revision 换成当前那个，
        # 让冲突只可能来自「同一个 request_id、不同的键」。
        other = {**payload, "expected_revision": landed}
        other["commands"] = [
            {"op": "clip.chroma", "clip_id": "g", "chroma": {**key, "color": "#FF00FF"}}
        ]
        moved = client.post(path + "/edits", json=other)
        assert moved.status_code == 409, moved.text
        assert moved.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT", moved.text
        # 软边换了个数也一样：回执认的是这一份键，不是「这一段有没有键」
        softer = {**payload, "expected_revision": landed}
        softer["commands"] = [
            {"op": "clip.chroma", "clip_id": "g", "chroma": {**key, "blend": 0.2}}
        ]
        also = client.post(path + "/edits", json=softer)
        assert also.status_code == 409, also.text

        # 1.277：1.276 那一份载荷里根本没有 `spill` 这一格。默认值不进指纹，所以「带着默认抑制」
        # 与「压根没写抑制」必须是**同一笔**回执——否则升级前写下的每一笔挂键，重发都会劈成两半。
        # 这里只换 `spill` 在不在，request_id 与 expected_revision 都照原来那份发。
        legacy = {
            **payload,
            "commands": [
                {
                    "op": "clip.chroma",
                    "clip_id": "g",
                    "chroma": {k: v for k, v in key.items() if k != "spill"},
                }
            ],
        }
        assert "spill" not in legacy["commands"][0]["chroma"], legacy
        before_old = client.post(path + "/edits", json=legacy)
        assert before_old.status_code == 200, before_old.text
        assert before_old.json()["replayed"] is True, "1.276 那份没写抑制的载荷没有命中自己那笔回执"
        assert before_old.json()["project"]["revision"] == landed, "重放老载荷还涨了一个版本"

        # 反过来：真的拧了抑制就是另一笔。走 HTTP 时这一笔必然先撞上版本门（上一笔已经把版本
        # 抬走了），所以这里直接比指纹本身——只换 `spill` 这一个数，别的一概不动。
        def fingerprint(chroma: dict) -> str:
            batch = EditBatch.model_validate(
                {"request_id": "fp", "expected_revision": 1,
                 "commands": [{"op": "clip.chroma", "clip_id": "g", "chroma": chroma}]}
            )
            return ProjectStore._fingerprint("edit", batch)

        base = fingerprint(key)
        assert base == fingerprint(legacy["commands"][0]["chroma"]), "写没写默认抑制成了两笔指纹"
        # 这一串是 **1.276 那份载荷**算出来的指纹——那时 `chroma` 里压根没有 `spill` 这一格。
        # 默认值不进指纹，所以升级后带着默认值重发必须还算出同一串；不然 1.276 每一笔挂键的重发
        # 都会劈成两半。（与 `blur_check` 那两串 pre-1.64 摘要是同一类账。）
        assert base == "be77fc2f968f72fc11b2ad748c5ee0ec" "91577463e19f1c9b52bc4960db6c8db4", (
            "这一格的默认值进指纹了——1.276 写下的每一笔回执都会劈成两半"
        )
        pressed = fingerprint({**key, "spill": SPILL})
        assert base != pressed, "拧动了抑制仍然同一笔（指纹没吃这一格）"
        assert pressed != fingerprint({**key, "spill": SPILL + 0.1}), "两份抑制强度在指纹里是一个数"
        assert base != fingerprint({**key, "color": "#FF0000"}), "换键色在指纹里不算另一笔"
        print(
            "   回执认得这份键：同载荷重放命中自己，换键色或换软边都成另一笔；"
            "写没写「默认的那一档抑制」是同一笔，拧动了就是另一笔"
        )


def pixels_suite(folder: Path) -> None:
    """成片逐点：抠掉的那一块交出的是底片，不是黑、也不是绿。"""
    app, token = client_for(folder)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        green = folder / "green.png"
        blue = folder / "blue.png"
        write_plate(green, GREEN, BOXES)
        write_plate(blue, BLUE)
        probed_green = client.post("/v1/media/import", json={"path": str(green)}).json()
        probed_blue = client.post("/v1/media/import", json={"path": str(blue)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "chroma-pixels",
                "settings": {
                    "width": SIZE,
                    "height": SIZE,
                    "frame_rate": {"numerator": 25, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        key = ChromaKey()
        row = chroma_row(key)

        def edit(request_id: str, revision: int, chroma) -> int:
            answer = client.post(
                path + "/edits",
                json={
                    "request_id": request_id,
                    "expected_revision": revision,
                    "commands": [{"op": "clip.chroma", "clip_id": "g", "chroma": chroma}],
                },
            )
            assert answer.status_code == 200, answer.text
            return answer.json()["project"]["revision"]

        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": seed_commands(probed_green, probed_blue, None),
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]

        control = export(client, path, revision, "chroma-control")
        for name, (x, y, rgb, _) in PROBES.items():
            assert at(control, x, y) == rgb, (name, at(control, x, y), rgb)

        revision = edit("key-on", revision, key.model_dump())
        keyed = export(client, path, revision, "chroma-keyed")
        worst = 0.0
        for name, (x, y, rgb, want) in PROBES.items():
            weight = weight_for(rgb, row) if want is None else want
            expected = tuple(
                round(rgb[i] * weight + BLUE[i] * (1 - weight)) for i in range(3)
            )
            got = at(keyed, x, y)
            delta = max(abs(a - b) for a, b in zip(got, expected))
            worst = max(worst, delta)
            assert delta <= 3, (name, got, expected, weight)
            print(
                f"   {name:14s} rgb={rgb} weight={weight:.2f} delivered={got} expected={expected}"
            )
        assert worst <= 3, worst

        revision = edit("key-off", revision, None)
        back = export(client, path, revision, "chroma-back")
        assert at(back, 2, 2) == GREEN, at(back, 2, 2)

        revision = edit("key-invert", revision, ChromaKey(inverted=True).model_dump())
        flipped = export(client, path, revision, "chroma-invert")
        assert at(flipped, 2, 2) == GREEN, at(flipped, 2, 2)
        hole = at(flipped, 20, 20)
        assert distance(hole, BLUE) < distance(hole, RED), hole
        print(f"   inverted: 绿幕留下 {at(flipped, 2, 2)}，红块被抠走 {hole}")

        # 1.277：拧上溢色抑制再导一次。读回来的是上面那几张手算的数；同时必须比没拧的那一趟
        # 更不绿——两端一起变到「都不压」也会满足前者，所以这一条才是这一只手的证据。
        revision = edit("key-spill", revision, ChromaKey(spill=SPILL).model_dump())
        pressed = export(client, path, revision, "chroma-spill")
        for name, (x, y, _, _) in PROBES.items():
            expected = SPILL_EXPECTED[name]
            got = at(pressed, x, y)
            delta = max(abs(a - b) for a, b in zip(got, expected))
            assert delta <= 3, (name, got, expected)
            print(f"   spill {name:14s} delivered={got} hand={expected} delta={delta}")
        for name in ("key minus 23", "key minus 31"):
            x, y = PROBES[name][0], PROBES[name][1]
            before = at(keyed, x, y)[1] - at(pressed, x, y)[1]
            assert before >= 40, (name, at(keyed, x, y), at(pressed, x, y))
        assert at(pressed, 20, 20) == RED, "压绿把红块也改了（那一条通道不是它）"
        revision = edit("key-clear", revision, None)


def main() -> None:
    contract_suite()
    spill_suite()
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        check_fixture(folder)
        graph_and_manifest(folder)
        single_track_suite(folder)
    with tempfile.TemporaryDirectory() as raw:
        refusal_suite(Path(raw))
    with tempfile.TemporaryDirectory() as raw:
        receipt_suite(Path(raw))
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        pixels_suite(folder)
    print(
        "PASS: 色度键与溢色抑制是同一份数在两端跑的一只手 -- 编译串与预览清单读的都是 "
        "`chroma_row` 那一份（含压哪一条通道），交付文件里被抠走的那一块交出的是底片而不是黑，"
        "拧上抑制后绿那一通道落在手算的那几个数上且比没拧时更不绿，"
        "没挂键与没拧抑制的片段一个键的字节都不许多，三种拒法各有名字且不涨版本"
    )


if __name__ == "__main__":
    main()
