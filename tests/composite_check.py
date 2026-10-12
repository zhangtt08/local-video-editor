"""第二路画面输入（`composite` 节点）：一条链第一次有**两幅画**，只能按像素验。

链上其余节点都是「一幅进、一幅出」的每通道函数；这一条边把「链调完的结果」与「进来的那幅
原图」相合，所以它在滤镜图里必须真的劈出第二路（`split` + 两段 `blend`）。所有「表对表」的
老办法在这里都回答不了问题——只有把交付文件里的像素读回来，与两个自己量出来的端点比，
才能说清「权重与方式都落到了 FFmpeg」。

断的全是量出来的数（这台机器的包内 FFmpeg 跑出来的，不是从公式表抄的）：

1. 两个自己量的端点：不挂任何节点、曝光 0 的那一份 = 原图在交付里的值 O；只挂曝光 0.5 的
   那一份 = 调完的 G。中灰源 130，量到的是 O≈132、G≈184。
2. `mix=0` 必须逐值等于 O（任何 mode 都是），`mix=1` 必须等于 `mode(G, O)`，`mix=0.5`
   必须是这两者的线性插值——这条不需要知道 FFmpeg 的 opacity 约定就能证伪「只有一幅画进了混合」。
3. `mode=normal` 且 `mix=1` 必须等于 G：FFmpeg 的 normal 取第一路，这正是「这一级什么都不改」。
4. `mode` 真的到了 FFmpeg：screen 与 multiply 在 `mix=1` 上给出不同的数，且各自等于按 O/G
   现算的 W3C 合成值。
5. **位置不影响结果**：这一级放在链首与链尾，读回的像素相同（它是图的一条边，不是串联的一步）。
6. 停用（`enabled=false`）与根本不挂这一级，像素相同；干跑的图里一个 `split=` 都没有。
7. 一条链第二个 `composite` 点名拒 `COMPOSITE_LIMIT`；走到分层合成的工程点名拒
   `COMPOSITE_NEEDS_CUT`——两次拒绝都不涨 revision、不排队任务、不落文件。
8. 八种混合方式逐条过一遍导出（名字是原样写进 `blend=all_mode=` 的）。这把尺的绝对值只有
   ±6 的抖（yuv420p 往返），所以这里按每个方式定义上的大小关系判，逐条写明容差。
8. 那句拒绝要**点名真的原因**：单条画面轨上改一次不透明度，不能让句子说成「你的工程是多条画面轨
   合成的」（走到分层的原因有十条，这一条只是其中一条）；`details.reasons` 逐条交回，
   透明母版那一路点名的原因是「透明通道」，两条原因同时按下就交回两条。
"""

import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project
from agentcut.grade import composite_stages, grade_tables, preview_grade
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-1080p"


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def source(folder: Path) -> Path:
    """两秒的中灰（128）：纯白会被曝光裁顶、纯黑什么都乘不出来，128 两头都还动得了。"""
    target = folder / "gray-2s.mp4"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x808080:s={SRC_W}x{SRC_H}:r=30:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-r",
            "30",
            str(target),
        ]
    )
    return target


def greys(path: Path) -> list[int]:
    """这份文件每一帧的灰度，去重排序——像素是唯一能回答「两幅画都进了混合」的证据。

    尺子自己也要量：1x1 缩放的单通道在 yuv420p 往返上有 ±6 级的抖动（同一幅中灰交回
    R=184 G=178 B=185），所以这里**不比绝对值到 4 级以内**，比的是每个方式定义上的大小关系
    与「FFmpeg 认不认这个名字」。要卡绝对值的那几条由 screen／multiply／normal 用 ±3 钉住。
    """
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    ).stdout
    return sorted({raw[index] for index in range(0, len(raw) - 2, 3)})


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-cx-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "cx-db.sqlite3", [folder], folder / "cx-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "cx-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "cxcheck" + "e" * 56
        app = create_app(folder / "cx-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            clip = source(folder)
            probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "cx-new",
                    "name": "第二路画面",
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            path = f"/v1/projects/{created['id']}"
            seeded = client.post(
                path + "/edits",
                json={
                    "request_id": "cx-seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a",
                            "label": "a",
                            "probe_id": probe["id"],
                            "verified": probe["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": 2 * T,
                            },
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text
            state = {"revision": seeded.json()["project"]["revision"]}

            def composite(mode: str, mix: float, enabled: bool = True) -> dict:
                return {"kind": "composite", "mode": mode, "mix": mix, "enabled": enabled}

            def curve() -> dict:
                return {
                    "kind": "curve",
                    "channel": "rgb",
                    "enabled": True,
                    "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
                }

            def export(tag: str, exposure: float, grade: list) -> list[int]:
                """改一次链、导一次，把交付文件里的灰度读回来。"""
                answer = client.post(
                    path + "/edits",
                    json={
                        "request_id": f"{tag}-edit",
                        "expected_revision": state["revision"],
                        "commands": [
                            {
                                "op": "clip.color",
                                "clip_id": "c",
                                "color": {"exposure": exposure, "grade": grade},
                            }
                        ],
                    },
                )
                assert answer.status_code == 200, answer.text
                state["revision"] = answer.json()["project"]["revision"]
                job = client.post(
                    path + "/renders",
                    json={
                        "request_id": f"{tag}-render",
                        "expected_revision": state["revision"],
                        "preset_id": PRESET,
                        "filename": f"{tag}.mp4",
                    },
                )
                assert job.status_code == 200, job.text
                done = wait(client, job.json()["job"]["id"])
                assert done["status"] == "succeeded", done
                values = greys(Path(done["output_path"]))
                assert len(values) == 1, (tag, values)
                return values

            original = export("cx-plain", 0.0, [])[0]
            graded = export("cx-graded", 0.5, [])[0]
            assert graded - original > 20, (original, graded)

            at_zero = export("cx-screen-0", 0.5, [composite("screen", 0.0)])
            at_one = export("cx-screen-1", 0.5, [composite("screen", 1.0)])
            at_half = export("cx-screen-half", 0.5, [composite("screen", 0.5)])
            assert at_zero[0] == original, (at_zero, original)
            expected_screen = 255 - (255 - graded) * (255 - original) / 255
            assert abs(at_one[0] - expected_screen) <= 3, (at_one, expected_screen)
            middle = at_zero[0] + 0.5 * (at_one[0] - at_zero[0])
            assert abs(at_half[0] - middle) <= 3, (at_half, middle)

            passthrough = export("cx-normal-1", 0.5, [composite("normal", 1.0)])
            assert abs(passthrough[0] - graded) <= 2, (passthrough, graded)
            multiplied = export("cx-multiply-1", 0.5, [composite("multiply", 1.0)])
            expected_multiply = graded * original / 255
            assert abs(multiplied[0] - expected_multiply) <= 3, (multiplied, expected_multiply)
            assert multiplied != at_one, (multiplied, at_one)

            # 八种方式全都要过一遍导出：契约的 `BlendMode` 表是 8 条，界面八个中文名字来自它，
            # 而这一级把名字原样写进 `blend=all_mode=`。名字 FFmpeg 不认就是「界面允许、
            # 导出会拒」，认但算成另一幅画就是「界面说一套、文件做一套」。绝对值这一档量不动
            # （单通道在 yuv420p 往返上有 ±6 的抖，见 `greys` 的说明），所以按每个方式定义上的
            # 大小关系判；normal／screen／multiply 三条另有上面那两组 ±2／±3 的硬账。
            read = {"normal": passthrough[0], "multiply": multiplied[0], "screen": at_one[0]}
            for mode in ("overlay", "darken", "lighten", "difference", "exclusion"):
                read[mode] = export(f"cx-{mode}", 0.5, [composite(mode, 1.0)])[0]
            low, high = min(original, graded), max(original, graded)
            # 每档按自己的定义判，容差是那把尺的抖（±6）而不是想象的零：
            # 上面那三行若有人把 `all_mode` 写死，`screen`／`multiply`／`normal` 立刻红在这里。
            assert read["difference"] < low - 40, read
            assert read["multiply"] < low - 20, read
            assert read["darken"] <= low + 6, read
            assert abs(read["exclusion"] - (low + high - 2 * low * high / 255)) <= 8, read
            assert abs(read["normal"] - high) <= 3, read
            assert abs(read["lighten"] - high) <= 3, read
            assert abs(read["overlay"] - high) <= 8, read
            assert read["screen"] > high + 20, read
            # 「方式被忽略」这一整类由这一条兜住：八个名字必须交出至少五种不同的数。
            assert len(set(read.values())) >= 5, read

            # 位置不影响结果：这一级在链首与链尾，读回来的像素必须相同。
            at_head = export("cx-head", 0.5, [composite("screen", 1.0), curve()])
            at_tail = export("cx-tail", 0.5, [curve(), composite("screen", 1.0)])
            assert at_head == at_tail == at_one, (at_head, at_tail, at_one)
            off = export("cx-disabled", 0.5, [composite("screen", 1.0, enabled=False)])
            assert off == [graded], (off, graded)

            # 图里真的劈了这一刀；不挂这一级时一个 split 都没有。（`GET /v1/projects/{id}`
            # 交回的是**没有包一层**的工程。）
            export("cx-on-again", 0.5, [curve(), composite("screen", 1.0)])
            project = Project.model_validate(client.get(path).json())
            graph = ";".join(compile_render_plan(project, PRESET).filters)
            assert "split=3" in graph, graph[:300]
            assert "blend=all_mode=screen" in graph, graph[:300]
            assert "blend=all_mode=normal:all_opacity=1" in graph, graph[:300]
            chain = project.clips["c"].color
            bare = project.model_copy(
                update={
                    "clips": {
                        "c": project.clips["c"].model_copy(
                            update={"color": chain.model_copy(update={"grade": []})}
                        )
                    }
                }
            )
            plain_graph = ";".join(compile_render_plan(bare, PRESET).filters)
            assert "split=" not in plain_graph and "blend=" not in plain_graph, plain_graph[:300]
            assert composite_stages(chain) == [{"mode": "screen", "mix": 1.0}]
            tables = grade_tables(chain)
            kinds = [stage["type"] for stage in tables["stages"]]
            assert kinds == ["composite"], kinds
            assert tables["stages"][0]["preview"] is False, tables
            # 预览那条路**整个丢掉**这一级：浏览器画不出第二条画面输入，
            # `preview_grade` 宁可交回 None，也不交回一个没有数字的原语。
            assert preview_grade(chain) is None, preview_grade(chain)

            # 一条链第二个 composite：点名拒，而且拒的时候什么都不做。
            revision_before = state["revision"]
            refused = client.post(
                path + "/edits",
                json={
                    "request_id": "cx-two",
                    "expected_revision": revision_before,
                    "commands": [
                        {
                            "op": "clip.color",
                            "clip_id": "c",
                            "color": {
                                "exposure": 0.5,
                                "grade": [
                                    composite("screen", 1.0),
                                    composite("multiply", 1.0),
                                ],
                            },
                        }
                    ],
                },
            )
            assert refused.status_code == 422, refused.text
            assert refused.json()["error"]["code"] == "COMPOSITE_LIMIT", refused.text
            head_after = client.get(path).json()["revision"]
            assert head_after == revision_before, refused.text
            assert "cx-two" not in sorted(item.name for item in exports.iterdir())

            # 并联的某一支里挂这条边：契约收 `GradeNode`，所以类型拦不住它，必须在这里点名拒。
            branch_revision = state["revision"]
            in_branch = client.post(
                path + "/edits",
                json={
                    "request_id": "cx-branch",
                    "expected_revision": branch_revision,
                    "commands": [
                        {
                            "op": "clip.color",
                            "clip_id": "c",
                            "color": {
                                "exposure": 0.5,
                                "grade": [
                                    {
                                        "kind": "parallel",
                                        "enabled": True,
                                        "mix": 1.0,
                                        "blend": "normal",
                                        "branches": [curve(), composite("screen", 1.0)],
                                    }
                                ],
                            },
                        }
                    ],
                },
            )
            assert in_branch.status_code == 422, in_branch.text
            # 一支里放不进这条边：挡住它的不是某个 validator，而是契约的类型表——
            # `GradeParallel.branches` 收的是 `GradeBranch`，那张表里没有 composite，加上
            # `extra="forbid"` 就是一次 `INVALID_REQUEST`。这条断言钉的是「类型表就是这一处口径」，
            # 若哪天有人把 composite 加进 `GradeBranch`，这里会先变成另一种代号而红。
            assert in_branch.json()["error"]["code"] == "INVALID_REQUEST", in_branch.text
            assert client.get(path).json()["revision"] == branch_revision, in_branch.text

            # 多条画面轨合成的工程：点名拒，出路写在句子里。
            layered = client.post(
                "/v1/projects",
                json={
                    "request_id": "cx-layered-new",
                    "name": "两条轨",
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            lpath = f"/v1/projects/{layered['id']}"
            lseed = client.post(
                lpath + "/edits",
                json={
                    "request_id": "cx-lseed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "v1"}},
                        {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "v2"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a",
                            "label": "a",
                            "probe_id": probe["id"],
                            "verified": probe["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c1",
                                "asset_id": "a",
                                "track_id": "v1",
                                "position_ticks": 0,
                                "duration_ticks": 2 * T,
                            },
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c2",
                                "asset_id": "a",
                                "track_id": "v2",
                                "position_ticks": 0,
                                "duration_ticks": T,
                                "color": {"grade": [composite("screen", 0.5)]},
                            },
                        },
                    ],
                },
            )
            assert lseed.status_code == 200, lseed.text
            lrevision = lseed.json()["project"]["revision"]
            ljob = client.post(
                lpath + "/renders",
                json={
                    "request_id": "cx-lrender",
                    "expected_revision": lrevision,
                    "preset_id": PRESET,
                    "filename": "分层拒绝.mp4",
                },
            )
            assert ljob.status_code == 422, ljob.text
            body = ljob.json()["error"]
            assert body["code"] == "COMPOSITE_NEEDS_CUT", body
            assert "另一条" in body["message"], body["message"]
            assert client.get(lpath).json()["revision"] == lrevision, body
            assert client.get(lpath + "/jobs").json()["jobs"] == [], body
            assert "分层拒绝" not in sorted(item.name for item in exports.iterdir())
            assert "多条画面轨" in body["message"], body["message"]

            # 拒绝那句必须点名**真的**那条原因。走到分层的原因有十条，「多条画面轨」只是其中一条：
            # 单条画面轨上改一次不透明度、或者只要一份透明母版，都会被同一句「你的工程是合成」
            # 解释成别的东西——那是假诊断，而假诊断把人支去改一处根本不需要改的地方。
            solo = client.post(
                "/v1/projects",
                json={
                    "request_id": "cx-solo-new",
                    "name": "单轨但有改动",
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            spath = f"/v1/projects/{solo['id']}"
            sseed = client.post(
                spath + "/edits",
                json={
                    "request_id": "cx-sseed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "v1"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a",
                            "label": "a",
                            "probe_id": probe["id"],
                            "verified": probe["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c",
                                "asset_id": "a",
                                "track_id": "v1",
                                "position_ticks": 0,
                                "duration_ticks": 2 * T,
                                "effects": {"opacity": 0.5},
                                "color": {"grade": [composite("screen", 0.5)]},
                            },
                        },
                    ],
                },
            )
            assert sseed.status_code == 200, sseed.text
            srevision = sseed.json()["project"]["revision"]

            def refuse(tag: str, **extra: object) -> dict:
                answer = client.post(
                    spath + "/renders",
                    json={
                        "request_id": f"cx-{tag}",
                        "expected_revision": srevision,
                        "preset_id": extra.pop("preset_id", PRESET),
                        "filename": f"{tag}.{'mov' if 'transparent' in extra else 'mp4'}",
                        **extra,
                    },
                )
                assert answer.status_code == 422, answer.text
                return answer.json()["error"]

            blamed = refuse("cx-solo")
            assert blamed["code"] == "COMPOSITE_NEEDS_CUT", blamed
            assert blamed["details"]["reasons"] == ["片段 c 改了「不透明度」"], blamed
            assert "不透明度" in blamed["message"], blamed["message"]
            assert "多条画面轨" not in blamed["message"], blamed["message"]
            assert "没有画面轨" not in blamed["message"], blamed["message"]

            # 透明母版那一档：只有带 alpha 平面的预设能走到编译（否则先被 TRANSPARENT_NEEDS_ALPHA
            # 拦在门外，问的就是另一件事）。
            matte = refuse("cx-matte", transparent=True, preset_id="prores-4444-alpha")
            assert matte["code"] == "COMPOSITE_NEEDS_CUT", matte
            assert any("透明通道" in item for item in matte["details"]["reasons"]), matte
            # 同一次拒绝里两条原因都要在：透明通道是这次交付带来的，不透明度是那条链带来的。
            assert len(matte["details"]["reasons"]) == 2, matte["details"]
            assert client.get(spath).json()["revision"] == srevision, matte
            assert client.get(spath + "/jobs").json()["jobs"] == [], matte
            for name in ("cx-solo", "cx-matte"):
                assert name not in " ".join(item.name for item in exports.iterdir()), name

            print(
                f"   原图在交付里是 {original}、调完是 {graded}；"
                f"mix=0 读回 {at_zero[0]}（=原图）、mix=1 读回 {at_one[0]}"
                f"（screen 公式 {expected_screen:.0f}）、mix=0.5 读回 {at_half[0]}"
                f"（两端中点 {middle:.0f}）；"
                f"normal@mix=1 = {passthrough[0]}（=调完的）、"
                f"multiply@mix=1 = {multiplied[0]}（公式 {expected_multiply:.0f}）；"
                "链首与链尾同像素、停用等于没挂"
            )


if __name__ == "__main__":
    main()
