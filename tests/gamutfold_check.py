"""界面那颗「按表换基色」：九个数字只有一个主人，那一格只在色彩管理那一对里面。

这一档**不重做** `gamut_check.py` 的测量——那张表的性质（每行和为 1、正逆往返恒等、列与色度坐标
成比例）与「线性进—矩阵—线性出」真导出之后的画面，那一档已经量过并钉住了。这里钉的是这张表
**交出去、再被界面搬回来**的那一段，四个说法各管一处：

1. `capabilities.gamut_matrices` 交的就是 `gamut.gamut_presets()` 现算的那几行：一行不少、一档不
   多、顺序照旧。界面抄一份表，就会与落在成片里的那一份不一致。
2. 每一行的九个系数都在引擎自己下发的 `matrix_limit` 之内。这是「那颗按钮不会骗人」的下半句：档位
   在名单里、点下去却被自己的契约拒掉，是最难看出来的一种坏。
3. 界面那一次写入（先 `clip.color_manage` 套上一对，再 `clip.grade` 交回整条链）落到工程里的矩阵
   就是表里那九个数，顺序不换；预览清单交给浏览器的 `stages` 里那一格 `m` 与导出图里
   `colorchannelmixer` 那九个也都是同一份。
4. 反方向也钉：把某一行的系数整体放大到越过 `matrix_limit`，引擎当场拒、版本不涨、链子留空——上面
   那些「收下了」才不是因为根本没在检查。

最后是一条字面量纪律：`desktop/src/gamutFold.ts` 里不许出现任何档位名、任何系数、任何兜底数字，
判断（哪一格能放、什么时候不能）只在那一处，界面与 `tests/desktop_gamutfold_check.ts` 都读它。
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agentcut.contracts import (
    MATRIX_LIMIT,
    Clip,
    Project,
)
from agentcut.contracts import (
    TIMEBASE as T,
)
from agentcut.gamut import gamut_presets
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT = 320, 180
HEAD = {
    "kind": "transfer",
    "input_space": "srgb",
    "output_space": "linear",
    "enabled": True,
    "purpose": "color_manage",
}
TAIL = {
    "kind": "transfer",
    "input_space": "linear",
    "output_space": "rec709",
    "enabled": True,
    "purpose": "color_manage",
}
MIXER_KEYS = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")


def matrix_node(coefficients: list[float]) -> dict:
    return {"kind": "matrix", "coefficients": list(coefficients), "enabled": True}


def new_clip(client: TestClient, name: str, probe: str, verified: dict) -> tuple[str, int]:
    """新工程 + 一条轨道 + 一段一秒钟的真实素材。

    底板与 `matrix_check.py` 同一块：两处用同一块料，就不会出现一处真导出、另一处只查了载荷形状。
    """
    created = client.post("/v1/projects", json={"request_id": f"new-{name}", "name": name})
    assert created.status_code == 200, created.text[:300]
    path = f"/v1/projects/{created.json()['project']['id']}"
    seed = client.post(
        path + "/edits",
        json={
            "request_id": "seed",
            "expected_revision": 0,
            "commands": [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                {
                    "op": "asset.import",
                    "asset_id": "a",
                    "label": "plate",
                    "probe_id": probe,
                    "verified": verified,
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c",
                        "asset_id": "a",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": T,
                    },
                },
            ],
        },
    )
    assert seed.status_code == 200, seed.text[:300]
    return path, seed.json()["project"]["revision"]


def published_is_the_engine_table(caps: dict[str, Any]) -> list[dict]:
    rows = gamut_presets()
    published = caps["gamut_matrices"]
    assert published == rows, "能力表交出去的那份不是引擎现算的那一份"
    assert [row["id"] for row in published] == [row["id"] for row in rows]
    assert len({row["id"] for row in published}) == len(published), "档位 id 不许重复"
    assert caps["features"]["grade_matrix"] is True
    assert caps["grade_limits"]["matrix_limit"] == MATRIX_LIMIT
    for row in published:
        numbers = row["coefficients"]
        assert len(numbers) == 9, f"{row['id']} 不是九个数"
        assert all(abs(value) <= MATRIX_LIMIT for value in numbers), (
            f"{row['id']} 有系数越过 ±{MATRIX_LIMIT}：那一档在名单里，点下去却会被自己的契约拒掉"
        )
        assert row["label"] and row["source"] and row["target"], f"{row['id']} 少了给人看的那几句"
        assert row["source_transfer"] and row["target_transfer"], (
            f"{row['id']} 没交代两端的曲线——挂这一档矩阵必须先问素材的曲线是哪一条"
        )
    return published


def mixer_in_graph(graph: str) -> list[float]:
    """从导出图里把 `colorchannelmixer` 那九个数读回来：只认引擎那一种写法（rr…bb 九个键都在）。"""
    match = re.search(r"colorchannelmixer=([^,\]]+)", graph)
    assert match, graph[:200]
    pairs = dict(part.split("=", 1) for part in match.group(1).split(":"))
    assert all(key in pairs for key in MIXER_KEYS), f"图里缺了键：{sorted(pairs)}"
    return [float(pairs[key]) for key in MIXER_KEYS]


def fold_rows(client: TestClient, rows: list[dict], probe: str, verified: dict) -> None:
    for row in (rows[0], rows[-1]):
        path, revision = new_clip(client, f"fold-{row['id']}", probe, verified)
        written = client.post(
            path + "/edits",
            json={
                "request_id": f"fold-{row['id']}",
                "expected_revision": revision,
                "commands": [
                    {
                        "op": "clip.color_manage",
                        "clip_id": "c",
                        "source_space": "srgb",
                        "display_space": "rec709",
                    },
                    {
                        "op": "clip.grade",
                        "clip_id": "c",
                        "grade": [HEAD, matrix_node(row["coefficients"]), TAIL],
                    },
                ],
            },
        )
        assert written.status_code == 200, written.text[:400]
        project = written.json()["project"]
        assert project["revision"] == revision + 1, (
            f"{row['id']} 那一次涨了 {project['revision'] - revision} 个版本："
            "「套上一对」加「折进一枚矩阵」是一个批次，一次点击只该涨一格"
        )
        stored = Project.model_validate(project)
        clip: Clip = stored.clips["c"]
        nodes = clip.color.grade
        assert [node.kind for node in nodes] == ["transfer", "matrix", "transfer"], (
            f"{row['id']} 落地成了 {[node.kind for node in nodes]}，不是线性进—矩阵—线性出"
        )
        assert [getattr(node, "purpose", None) for node in nodes] == [
            "color_manage",
            None,
            "color_manage",
        ], "只有那两个转换节点带章：界面不自己造第三种说法"
        assert list(nodes[1].coefficients) == row["coefficients"], (
            f"{row['id']} 写进链子的九个数字与能力表那一份不一样"
        )

        manifest = client.get(path + "/preview-manifest").json()
        stages = manifest["clips"]["c"]["grade"]["stages"]
        assert [stage["type"] for stage in stages] == ["lut", "matrix", "lut"], stages
        assert list(stages[1]["m"]) == row["coefficients"], (
            f"{row['id']} 交给浏览器的那九个数字不是表里那九个"
        )
        graph = "\n".join(compile_render_plan(stored, "h264-source-quality").filters)
        assert mixer_in_graph(graph) == row["coefficients"], (
            f"{row['id']} 导出图里那九个数与表里对不上"
        )


def overshoot_is_refused(client: TestClient, rows: list[dict], probe: str, verified: dict) -> None:
    path, revision = new_clip(client, "fold-overshoot", probe, verified)
    too_big = [value * 10.0 for value in rows[0]["coefficients"]]
    assert max(abs(value) for value in too_big) > MATRIX_LIMIT, "这份夹具越不过上限，判不了"
    refused = client.post(
        path + "/edits",
        json={
            "request_id": "overshoot",
            "expected_revision": revision,
            "commands": [
                {"op": "clip.grade", "clip_id": "c", "grade": [HEAD, matrix_node(too_big), TAIL]},
            ],
        },
    )
    assert refused.status_code == 422, refused.text[:300]
    assert "coefficients must be within" in refused.text, refused.text[:300]
    after = client.get(path).json()
    assert after["revision"] == revision, "被拒的那一笔把版本涨了"
    assert Project.model_validate(after).clips["c"].color.grade == [], "被拒的那一笔还是写了节点"


def surfaces_stay_copies_of_the_table() -> None:
    fold = (ROOT / "desktop/src/gamutFold.ts").read_text(encoding="utf-8")
    fields = (ROOT / "desktop/src/views/GradeFields.tsx").read_text(encoding="utf-8")
    for row in gamut_presets():
        assert row["id"] not in fold, f"界面抄了档位名：{row['id']}"
        assert row["id"] not in fields, f"检查器里写死了档位名：{row['id']}"
    assert not re.search(r"coefficients:\s*\[\s*-?\d", fold), (
        "gamutFold.ts 里出现了系数——那九个数字只有一个主人（gamut.primaries_matrix）"
    )
    assert not re.search(r"\?\?\s*\d", fold), (
        "gamutFold.ts 里有兜底数字：每链节点上限与九个系数都必须来自 capabilities 那一份"
    )
    assert "gamut_matrices" in fields, "检查器没去读能力表那一份，那就是在别处另编了一张表"
    for name in ("usableRows", "foldBlocker", "foldIn", "foldedRow", "foldWords"):
        assert name in fields, f"检查器没用上 gamutFold 的 {name}：判断就有了第二处"


def main() -> None:
    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        source = folder / "plate.mp4"
        done = subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"nullsrc=s={WIDTH}x{HEIGHT}:d=1:r=25,format=rgb24,"
                "geq=r='X*255/(W-1)':g='Y*255/(H-1)':b='128'",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(source),
            ],
            capture_output=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr.decode(errors="replace")[-400:]
        token = "g" * 48
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        probe = media.import_file(str(source))
        verified: dict = probe.verified.model_dump()
        store = ProjectStore(media.db_path, media)
        with TestClient(
            create_app(store.path, token, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            rows = published_is_the_engine_table(client.get("/v1/capabilities").json())
            fold_rows(client, rows, probe.id, verified)
            overshoot_is_refused(client, rows, probe.id, verified)
        surfaces_stay_copies_of_the_table()
        print(
            f"   表里 {len(rows)} 档；首档「{rows[0]['label']}」九个系数 "
            + " ".join(f"{value:.6f}" for value in rows[0]["coefficients"])
        )
        print(
            "PASS: 基色表交出去的就是引擎现算的那一份、每一档都在界面允许的范围内；"
            "写进链子的九个数字与预览清单、导出图里那九个一字不差，越上限那一份被当场拒且不涨版本；"
            "而 gamutFold.ts 里没有一个档位名、一个系数、一个兜底数字"
        )


if __name__ == "__main__":
    main()
