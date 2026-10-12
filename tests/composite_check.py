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
7. 一条链第二个 `composite` 点名拒 `COMPOSITE_LIMIT`：拒的时候不涨 revision、不排队、不落文件。
8. 八种混合方式逐条过一遍导出（名字是原样写进 `blend=all_mode=` 的）。这把尺的绝对值只有
   ±6 的抖（yuv420p 往返），所以这里按每个方式定义上的大小关系判，逐条写明容差。
9. 1.145：**分层那条 Builder 也走同一条边**。用一个不透明度改动把工程推进 layered，交透明母版，
   五份读回灰度与 alpha——mix 拧到哪一端都不改 matte（五份 alpha 必须是同一个字节）。
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


def grey_at(path: Path, at: float) -> int:
    """某一刻的灰度：`greys()` 取的是全片最小值，淡入起点是黑，所以按时间读。"""
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-vf",
            "scale=1:1",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    ).stdout
    return raw[0]


def alpha_byte(path: Path, at: float, fx: float, fy: float) -> int:
    """交付文件里某一点的 alpha 字节：`alphaextract` 把 alpha 平面搬成灰度流再读。"""
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-vf",
            "alphaextract,scale=1:1",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
    ).stdout
    return raw[0]


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
            # 1.145：这条边接进了分层那条 Builder。用一个不透明度改动把工程推进 layered
            # （`effects.opacity != 1` 就是十条原因里的一条），交五份读回**灰度与 alpha**：
            # A 曝光 0 不挂 = 原图；B 曝光 0.5 不挂 = 调完的；C mix=0 逐值等于 A；
            # D mix=1 = screen 的结果；E mix=0.5 = 两端中点。五份的 alpha 必须**同一个字节**——
            # 相合只减弱调色，不许动 matte（透明母版量的就是这个字节，不是滤镜串）。
            layered = client.post(
                "/v1/projects",
                json={
                    "request_id": "cx-l2-new",
                    "name": "分层里的第二路",
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
                    "request_id": "cx-l2-seed",
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
                                "effects": {"opacity": 0.5},
                            },
                        },
                    ],
                },
            )
            assert lseed.status_code == 200, lseed.text
            lrevision = lseed.json()["project"]["revision"]
            lplan = compile_render_plan(
                Project.model_validate(client.get(lpath).json()),
                "prores-4444-alpha",
                transparent=True,
            )
            assert lplan.mode == "layered", lplan.mode

            def deliver_layered(tag: str, exposure: float, grade: list) -> tuple[int, int]:
                nonlocal lrevision
                answer = client.post(
                    lpath + "/edits",
                    json={
                        "request_id": f"cx-{tag}-edit",
                        "expected_revision": lrevision,
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
                lrevision = answer.json()["project"]["revision"]
                job = client.post(
                    lpath + "/renders",
                    json={
                        "request_id": f"cx-{tag}-job",
                        "expected_revision": lrevision,
                        "preset_id": "prores-4444-alpha",
                        "filename": f"{tag}.mov",
                        "transparent": True,
                    },
                )
                assert job.status_code == 200, job.text
                done = wait(client, job.json()["job"]["id"])
                assert done["status"] == "succeeded", done
                out = Path(done["output_path"])
                return greys(out)[0], alpha_byte(out, 1.0, 0.5, 0.5), out

            l_plain = deliver_layered("cx-l-plain", 0.0, [])
            l_graded = deliver_layered("cx-l-graded", 0.5, [])
            l_zero = deliver_layered("cx-l-zero", 0.5, [composite("screen", 0.0)])
            l_one = deliver_layered("cx-l-one", 0.5, [composite("screen", 1.0)])
            l_half = deliver_layered("cx-l-half", 0.5, [composite("screen", 0.5)])
            lgraph = ";".join(
                compile_render_plan(
                    Project.model_validate(client.get(lpath).json()),
                    "prores-4444-alpha",
                    transparent=True,
                ).filters
            )
            assert "alphamerge" in lgraph, "分层那一路要把 matte 盖回相合的结果"
            assert "blend=all_mode=screen" in lgraph and "all_opacity=0.5" in lgraph, lgraph[:400]
            assert l_graded[0] - l_plain[0] > 20, (l_plain, l_graded)
            assert abs(l_zero[0] - l_plain[0]) <= 3, (l_zero, l_plain)
            want_layered = 255 - (255 - l_graded[0]) * (255 - l_plain[0]) / 255
            assert abs(l_one[0] - want_layered) <= 4, (l_one, want_layered)
            mid_layered = l_plain[0] + 0.5 * (l_one[0] - l_plain[0])
            assert abs(l_half[0] - mid_layered) <= 4, (l_half, mid_layered)
            matte = {row[1] for row in (l_plain, l_graded, l_zero, l_one, l_half)}
            assert len(matte) == 1, (l_plain, l_graded, l_zero, l_one, l_half)
            assert 100 <= l_plain[1] <= 155, l_plain
            # 交叉表再乘一格：**这条边 × 不透明度淡入 × 透明母版**。
            # 淡是 alpha 随时间的那条曲线，相合是 RGB 的那条边——两者共用同一个 `geq` 乘子，
            # 所以淡的形状必须一份都不许被 `mix` 改走：在淡的中点与淡完之后各读一次 alpha，
            # mix=0 与 mix=1 两份必须**逐字节相同**，而同一帧的灰度必须不同（相合真的在执行）。
            fade_answer = client.post(
                lpath + "/edits",
                json={
                    "request_id": "cx-l-fade",
                    "expected_revision": lrevision,
                    "commands": [
                        {
                            "op": "clip.fade",
                            "clip_id": "c",
                            "property": "opacity",
                            "duration_ticks": 70_560_000,
                            "mode": "in",
                        }
                    ],
                },
            )
            assert fade_answer.status_code == 200, fade_answer.text
            lrevision = fade_answer.json()["project"]["revision"]
            faded_zero = deliver_layered("cx-l-fade-zero", 0.5, [composite("screen", 0.0)])
            faded_one = deliver_layered("cx-l-fade-one", 0.5, [composite("screen", 1.0)])
            mid_zero = alpha_at_zero = None
            for path_value, tag in ((faded_zero[2], "zero"), (faded_one[2], "one")):
                mid = alpha_byte(path_value, 0.5, 0.5, 0.5)
                late = alpha_byte(path_value, 1.5, 0.5, 0.5)
                assert 40 <= mid <= 90, (tag, mid)
                assert late >= 120, (tag, late)
                if mid_zero is None:
                    mid_zero, late_zero = mid, late
                else:
                    assert (mid, late) == (mid_zero, late_zero), (
                        tag,
                        (mid, late),
                        (mid_zero, late_zero),
                    )
            zero_grey, one_grey = grey_at(faded_zero[2], 1.5), grey_at(faded_one[2], 1.5)
            assert one_grey - zero_grey > 20, (zero_grey, one_grey)
            print(
                f"   淡入中点 alpha={mid_zero}／淡完 {late_zero}，两份逐字节相同；"
                f"同一时刻灰度 mix=0 {zero_grey} 对 mix=1 {one_grey}"
            )
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
