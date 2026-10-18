"""1.200 的引擎账：删掉一张只有层在用的素材，预览与导出必须说同一句话。

复现过才做的两件事（`Documents/Qoder/2026-10-17/658a66d5/probe_layer_offline.py` 量到的）：
· 以前 `asset.remove` 只查片段自己那一路素材，删掉「只有层在用」的一张是**允许**的（HTTP 200），
  删完清单照旧把那层交出去、浏览器拿不到地址什么也不画，而导出整条 `LAYER_ASSET_UNAVAILABLE` 拒；
· 清单那一行以前没有任何「画不画得成」的话，界面只能自己猜——猜出来的判断就是第二个主人。

这一档钉四件事：
1. 那颗动作现在当场拒绝，点名是哪一段、给两条走得通的出路；不牵连的删除照旧成功；
2. 清单那一行的 `paintable`/`reason` 由 `animation.layer_rows` 一处算出：素材悬空 / 不是图像 /
   没有验过的媒体记录 → 假，三种各有自己的 reason，好的那条是真；
3. 这一行**不被整条撤掉**——界面要能说「哪一层画不成」，所以行还在、数还在，只是带着实话；
4. 导出那一条仍然是同一句话（同一个 code），也就是两端说的确实是同一件事。
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import layer_rows, preview_manifest
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Asset, Clip, ClipColor, EditorError, GradeLayer, Project, Track
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def plate(folder: Path, name: str, grey: int) -> Path:
    target = folder / name
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=0x{grey:02x}{grey:02x}{grey:02x}:s=320x180:r=30:d=1",
         "-frames:v", "1", str(target)],
        check=True, capture_output=True, timeout=300,
    )
    return target


def project_with_layer(assets: dict) -> Project:
    """一份最小而真的工程：一段底、一层指「ly」。（第三种状态靠改这张表得到，不靠 mock。）"""
    return Project(
        id="p", name="离线层", schema_version=24, tracks=[Track(id="v", kind="video", name="画面")],
        clips={"c": Clip(id="c", asset_id="bd", track_id="v", duration_ticks=T,
                         color=ClipColor(grade=[GradeLayer(asset_id="ly", mode="multiply",
                                                           mix=1.0)]))},
        assets=assets,
    )


def probe_asset(client: TestClient, path: Path) -> dict:
    answer = client.post("/v1/media/import", json={"path": str(path)})
    assert answer.status_code == 200, answer.text
    return answer.json()


def main() -> None:  # noqa: C901 - 一档门禁按节读，比拆成十个互相递状态的函数清楚
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    with tempfile.TemporaryDirectory(prefix="agentcut-lyoff-") as scratch:
        folder = Path(scratch)
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        exports = folder / "exports"
        runtime = JobRuntime(folder / "api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "lyoff" + "e" * 56
        app = create_app(folder / "api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            base = plate(folder, "base.png", 0x80)
            layer = plate(folder, "layer.png", 0xC8)
            spare = plate(folder, "spare.png", 0x40)
            bp, lp, sp = (probe_asset(client, one) for one in (base, layer, spare))

            def edit(request_id: str, commands: list, revision: int, pid: str):
                return client.post(f"/v1/projects/{pid}/edits", json={
                    "request_id": request_id, "expected_revision": revision, "commands": commands,
                })

            made = client.post("/v1/projects", json={"request_id": "n", "name": "离线层"}).json()
            pid = made["project"]["id"]
            rev = made["project"]["revision"]
            built = edit("b", [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                {"op": "asset.import", "asset_id": "bd", "label": "底",
                 "probe_id": bp["id"], "verified": bp["verified"]},
                {"op": "asset.import", "asset_id": "ly", "label": "层",
                 "probe_id": lp["id"], "verified": lp["verified"]},
                {"op": "asset.import", "asset_id": "sp", "label": "闲",
                 "probe_id": sp["id"], "verified": sp["verified"]},
                {"op": "clip.add", "clip": {"id": "c", "asset_id": "bd", "track_id": "v",
                                            "position_ticks": 0, "duration_ticks": T}},
                {"op": "clip.color", "clip_id": "c", "color": {"exposure": 0.0, "grade": [
                    {"kind": "layer", "asset_id": "ly", "mode": "multiply", "mix": 1.0,
                     "offset_x": 0.0, "offset_y": 0.0, "scale": 1.0, "enabled": True}]}},
            ], rev, pid)
            assert built.status_code == 200, built.text
            rev = built.json()["project"]["revision"]

            # 1) 那颗动作：删「只有层在用」的素材必须当场拒绝，并点名是哪一段
            refused = edit("r1", [{"op": "asset.remove", "asset_id": "ly"}], rev, pid)
            assert refused.status_code == 422, refused.text
            body = refused.json()["error"]
            assert body["code"] == "ASSET_IN_USE", body
            assert "c" in (body.get("target") or "") + str(body.get("details")), body
            detail = str(body)
            assert "第二路画面" in detail and "LAYER_ASSET_UNAVAILABLE" in detail, detail[:400]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == rev, "拒绝涨了版本"
            print(f"   拒绝那句：{body['message'][:96]}")

            # 不牵连：没被任何片段或层用的素材照旧删得掉（反向也钉，不然这条守卫会盖住正常删除）
            removed = edit("r2", [{"op": "asset.remove", "asset_id": "sp"}], rev, pid)
            assert removed.status_code == 200, removed.text
            left = removed.json()["project"]["assets"]
            assert "sp" not in left, left
            print("   不牵连那一条：没人用的素材照旧删得掉")

            # 2) 清单那一行的实话：四种状态各答各的，判断只在 `layer_rows` 一处
            good = client.get(f"/v1/projects/{pid}").json()
            rows = layer_rows(Project(**good).clips["c"], Project(**good), T // 30)
            assert len(rows) == 1 and rows[0]["paintable"] is True, rows
            assert rows[0]["reason"] is None and rows[0]["mode"] == "multiply", rows[0]

            def row_for(assets: dict) -> dict:
                project = Project(**good)
                project.assets = assets
                return layer_rows(project.clips["c"], project, T // 30)[0]

            orphan = {k: v for k, v in good["assets"].items()}
            del orphan["ly"]
            missing = row_for({k: Asset(**v) for k, v in orphan.items()})
            assert missing["paintable"] is False and missing["reason"] == "missing", missing
            unverified = row_for({
                k: (v.model_copy(update={"verified": None}) if k == "ly" else v)
                for k, v in {kk: Asset(**vv) for kk, vv in good["assets"].items()}.items()
            })
            assert unverified["paintable"] is False, unverified
            assert unverified["reason"] == "unverified", unverified
            wrong_kind = row_for({
                k: (v.model_copy(update={"kind": "video", "duration_ticks": T}) if k == "ly" else v)
                for k, v in {kk: Asset(**vv) for kk, vv in good["assets"].items()}.items()
            })
            assert wrong_kind["paintable"] is False and wrong_kind["reason"] == "kind", wrong_kind
            # 三种坏状态都不许把那一行整条撤掉：界面要能说出「哪一层」画不成
            assert missing["asset_id"] == unverified["asset_id"] == wrong_kind["asset_id"] == "ly"
            print("   三种画不成的状态：missing / unverified / kind 各有自己的 reason，行都还在")

            # 3) 清单确实把这份实话交出去（不是只有函数会算）
            manifest = preview_manifest(Project(**good), None, clip_ids=["c"])
            row = manifest["clips"]["c"]["layer"][0]
            assert row["paintable"] is True, row
            broken = Project(**good)
            # 只让「层指的那张」悬空：底片还在，不然先撞上片段素材缺失那条更前面的拒绝。
            broken.assets = {k: v for k, v in broken.assets.items() if k != "ly"}
            said = preview_manifest(broken, None, clip_ids=["c"])["clips"]["c"]["layer"][0]
            assert said["paintable"] is False and said["reason"] == "missing", said
            assert "windows" in said and said["mode"] == "multiply", said

            # 4) 导出那一条还是同一句话：悬空引用整条拒绝，而不是画一层没有根据的画
            try:
                compile_render_plan(broken, "h264-1080p", fit="stretch")
            except EditorError as exc:
                assert exc.code == "LAYER_ASSET_UNAVAILABLE", (exc.code, exc.message)
                print(f"   导出那一条：{exc.code} ——两端说的是同一件事")
            else:
                raise AssertionError("素材悬空时导出居然编译过了，那预览与导出又开始各说各话")

        print("PASS: 删掉只有层在用的素材当场拒绝且点名、三种画不成的状态各答各的、"
              "清单把实话交出去而那一行不整条撤掉、导出仍是同一条拒绝")


if __name__ == "__main__":
    main()
