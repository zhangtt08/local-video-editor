"""基色转换表：数是对的吗？挂上「线性进—矩阵—线性出」这一对之后，画面真的换档、灰真的不动吗？

这一步交的是一**份表**（`capabilities.gamut_matrices`），不是一颗按钮：九个数要写进链子里的
`matrix` 节点，并且必须前后各挂一个 `transfer` 把画面抬进线性光再落回来——`matrix` 那九个数
是直接乘在存储值上的，单独挂它做基色转换就是错的（`clip.color_manage` 从 1.130 起就在写这样一对）。
界面这一侧还没有那颗按钮；没有按钮就不说按钮的谎。

量的两层：

1. 表的性质（不引任何记忆里的发表值）：每行和恰为 1；每一档正逆往返是恒等；**每一列**与
   「源档那号原色的色度经 XYZ 换算到目标档」成比例——颜色是三维向量的等价类，必须先归一化再比，
   否则对的矩阵也会读成错的（这一条本轮真的踩过一次）。比之前先取绝对值最大的一维做基准，
   拿一个接近 0 的系数去除会把误差放大成假红。
2. 真走一遍导出：两段各一秒的素材，一段橙红 `0xB45032`（两边色域都在内才看得出差别；
   纯 2020 红在 709 里越界、钳位后落回同一条射线，那种「没变」是对的，不能当判据），
   一段中灰 `0x808080`。四份交付：不挂 / 挂 2020→709 / 再挂 709→2020 走一趟来回 /
   同一形状的链但把两个矩阵换成差 1e-6 才等于单位阵的系数（对照组）。
   前三份说的都是必须说的事：中灰不动（行和为 1）、橙红动了（表真的接进了链子）。
   第四份是**归因**：来回一趟并不恒等，因为这条链的中间一站是 8 位线性光——1.52 当年就是
   被这件事拦住的。对照组量出「这条链自己漂多少」，真链与对照组之差才是矩阵那份，
   两个数都印出来。不拿恒等去要一条会量化的链，也不把量化的账算到矩阵头上。
"""

import subprocess
import tempfile
import time
from pathlib import Path
from typing import get_args

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import ColorSpace, capabilities
from agentcut.gamut import PRIMARIES, chromaticity_rgb, primaries_matrix
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-source-quality"


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    ).stdout


def rgb_at(path: Path, at: float) -> tuple[int, int, int]:
    """按时间读一帧。

    上一版这里写死了 `-ss 1.0`，于是两段素材读的其实是同一段——仪表的错被当成了产品的现象。
    """
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
    )
    return (raw[0], raw[1], raw[2])


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(x - y) for x, y in zip(a, b))


def check_table() -> None:
    tables = capabilities()["gamut_matrices"]
    assert [row["id"] for row in tables][:2] == ["rec2020_to_rec709", "rec709_to_rec2020"]
    assert len({row["id"] for row in tables}) == len(tables), "档位 id 撞了"
    assert all(len(row["coefficients"]) == 9 for row in tables)
    spaces = set(get_args(ColorSpace))
    for row in tables:
        flat = row["coefficients"]
        assert row["source_transfer"] in spaces, row
        assert row["target_transfer"] in spaces, row
        matrix = primaries_matrix(row["source"], row["target"])
        for index in range(3):
            assert abs(sum(flat[index * 3 : index * 3 + 3]) - 1.0) < 2e-6, (row["id"], index)
        for r in range(3):
            for c in range(3):
                assert abs(flat[r * 3 + c] - matrix[r][c]) < 1e-6, (row["id"], r, c)
        # 第 c 列必须落在**源档第 c 号原色**在目标档里的那条射线上。这一条抓的是矩阵自己的列序：
        # 只把红、绿两列对调，行和照样是 1（灰不动）、正逆照样互为逆阵（往返恒等），
        # 只有「红原色去哪儿」这一件事会露馅——而它在成片里读起来只是「颜色有点偏」。
        for column in range(3):
            got = [matrix[r][column] for r in range(3)]
            want = chromaticity_rgb(row["target"], PRIMARIES[row["source"]][0][column])
            # 颜色是三维向量的等价类：比方向之前先归一化，而且用绝对值最大的那一维做基准，
            # 不然拿一个接近 0 的系数去除，误差被放大成假红（本轮真的先踩过一次）。
            pivot = max(range(3), key=lambda index: abs(got[index]))
            scale = want[pivot] / got[pivot]
            for index in range(3):
                assert abs(scale * got[index] - want[index]) < 1e-6, (
                    row["id"],
                    column,
                    got,
                    want,
                )
    # 一颗外部锚。三条自洽性质有一个共同盲区：它们都是拿实现自己的基色数据反过来核自己，
    # `PRIMARIES` 里把一个 xy 少抄一位，矩阵和那条射线会用同一份错数据算出来，
    # 行和仍 1、正逆仍恒等、列仍「落在射线上」——全表自洽，只是每一档都偏。这种笔误只有
    # 外来的数能抓。锚取自本仓库自己的测量记录：1.52 那节记下「与公布值一致」的 709→P3
    # 九个数字 [0.92092 0.19879 0; 0.03717 1.08255 0; 0.01913 0.08106 1.01952]，
    # 行和 1.11971——那是整颗矩阵乘了同一个 1.12（方向不动，白点被抬到 1.12 再钳位），
    # 所以把那九个数除以行和，就是行和为 1 的那一份归一化。实测九个系数逐个差在 7e-6 内。
    # 被这颗锚钉住的是 rec709 与 P3 两档的 xy；rec2020、rec601 没有外部数可钉，
    # 只有自洽性质护着——这一句照实印出来，下一版拿 FFmpeg 自己的 colorspace 换算补那一半。
    recorded = [0.92092, 0.19879, 0.0, 0.03717, 1.08255, 0.0, 0.01913, 0.08106, 1.01952]
    gain = sum(recorded[:3])
    assert abs(gain - 1.11971) < 1e-4, gain
    matrix = primaries_matrix("rec709", "display-p3")
    for index, value in enumerate(recorded):
        got = matrix[index // 3][index % 3]
        assert abs(got - value / gain) < 1e-5, (index, got, value / gain)
    for row in tables:
        back = primaries_matrix(row["target"], row["source"])
        forward = primaries_matrix(row["source"], row["target"])
        for r in range(3):
            for c in range(3):
                product = sum(forward[r][k] * back[k][c] for k in range(3))
                assert abs(product - (1.0 if r == c else 0.0)) < 1e-12, (row["id"], r, c, product)
    print(
        f"   表：{len(tables)} 档，每行和 1、正逆往返恒等、三列分别落在源档三原色的射线上"
        "（与独立的 XYZ 换算成比例，同一白点故不需色适应），另钉一颗外部锚"
        "（709→Display P3，取自 1.52 的测量记录除以它的行和 1.11971；rec2020、rec601 无锚）"
    )


def main() -> None:
    check_table()
    with tempfile.TemporaryDirectory(prefix="agentcut-gm-") as scratch:
        folder = Path(scratch)
        media = MediaService(folder / "gm.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        exports = folder / "exports"
        runtime = JobRuntime(folder / "gm-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "gamutcheck" + "e" * 54
        app = create_app(folder / "gm-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            for name, colour in (("orange", "0xB45032"), ("grey", "0x808080")):
                run(
                    [
                        FFMPEG,
                        "-v",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={colour}:s={SRC_W}x{SRC_H}:r=30:d=1",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv444p",
                        "-r",
                        "30",
                        str(folder / (name + ".mp4")),
                    ]
                )
            probes = {}
            for name in ("orange", "grey"):
                probes[name] = client.post(
                    "/v1/media/import", json={"path": str(folder / (name + ".mp4"))}
                ).json()
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "gm-new",
                    "name": "基色表",
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            path = f"/v1/projects/{created['id']}"
            commands = [{"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}}]
            for index, name in enumerate(("orange", "grey")):
                commands.append(
                    {
                        "op": "asset.import",
                        "asset_id": "a" + str(index),
                        "label": name,
                        "probe_id": probes[name]["id"],
                        "verified": probes[name]["verified"],
                    }
                )
                commands.append(
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c" + str(index),
                            "asset_id": "a" + str(index),
                            "track_id": "v",
                            "position_ticks": index * T,
                            "duration_ticks": T,
                        },
                    }
                )
            seed = client.post(
                path + "/edits",
                json={"request_id": "gm-seed", "expected_revision": 0, "commands": commands},
            )
            assert seed.status_code == 200, seed.text
            state = {"revision": seed.json()["project"]["revision"]}
            tables = {row["id"]: row for row in capabilities()["gamut_matrices"]}

            def trio(preset_id: str, coefficients: list | None = None) -> list:
                row = tables[preset_id]
                return [
                    {
                        "kind": "transfer",
                        "input_space": row["source_transfer"],
                        "output_space": "linear",
                    },
                    {
                        "kind": "matrix",
                        "coefficients": coefficients or row["coefficients"],
                    },
                    {
                        "kind": "transfer",
                        "input_space": "linear",
                        "output_space": row["target_transfer"],
                    },
                ]

            # 对照组必须是**颜色上不动、形状上同一条链**：矩阵换成「差 1e-6 才等于单位阵」。
            # 为什么不用真单位阵——因为试过，而且这次把理由量出来了：单位阵会被 `_matrix_of`
            # 判成「这节点什么都不做」而删掉，两侧的单通道曲线各自成一张表；但 8 位存储值上乘
            # 单位阵不产生任何舍入，所以两条读回的数一模一样（都是 (177,78,44)，本轮实测）。
            # 留 1e-6 是为了让对照组和真链**同形状**（矩阵节点确实在场），不是怕它改量化。
            near_identity = [1.0 + 1.0e-6 if index in (0, 4, 8) else 0.0 for index in range(9)]

            def set_grade(grade: list) -> None:
                for clip_id in ("c0", "c1"):
                    answer = client.post(
                        path + "/edits",
                        json={
                            "request_id": "gm-e"
                            + str(state["revision"])
                            + clip_id
                            + str(len(grade)),
                            "expected_revision": state["revision"],
                            "commands": [
                                {
                                    "op": "clip.color",
                                    "clip_id": clip_id,
                                    "color": {"exposure": 0.0, "grade": grade},
                                }
                            ],
                        },
                    )
                    assert answer.status_code == 200, answer.text
                    state["revision"] = answer.json()["project"]["revision"]

            def deliver(tag: str):
                job = client.post(
                    path + "/renders",
                    json={
                        "request_id": "gm-j" + tag,
                        "expected_revision": state["revision"],
                        "preset_id": PRESET,
                        "filename": tag + ".mp4",
                    },
                )
                assert job.status_code == 200, job.text
                done = wait(client, job.json()["job"]["id"])
                assert done["status"] == "succeeded", done
                out = Path(done["output_path"])
                return rgb_at(out, 0.4), rgb_at(out, 1.4)

            set_grade([])
            plain_orange, plain_grey = deliver("gm-plain")
            assert plain_orange[0] > plain_orange[2] + 40, plain_orange
            set_grade(trio("rec2020_to_rec709"))
            wide_orange, wide_grey = deliver("gm-wide")
            set_grade(trio("rec2020_to_rec709") + trio("rec709_to_rec2020"))
            back_orange, back_grey = deliver("gm-back")
            set_grade(
                trio("rec2020_to_rec709", near_identity) + trio("rec709_to_rec2020", near_identity)
            )
            ctl_orange, ctl_grey = deliver("gm-ctl")
            assert distance(wide_grey, plain_grey) <= 3, (wide_grey, plain_grey)
            assert distance(wide_orange, plain_orange) >= 6, (wide_orange, plain_orange)
            # 界的来历，不是宽容：同形状的对照链在暗部蓝（存储值 50，线性后只剩约 7 个码字）
            # 自己漂 6 级——那是 8 位线性光这一站的量化，1.52 记的就是它。矩阵那份是两条链之差，
            # 实测 4 级，要求它不超过这条链自己的量化成本；中灰在中段、码字充裕，来回一趟
            # 实测 0～1 级，界给到 6。
            assert distance(back_orange, ctl_orange) <= 6, (back_orange, ctl_orange)
            assert distance(back_grey, plain_grey) <= 6, (back_grey, plain_grey)
            print(
                f"   导出：中灰 {plain_grey}→{wide_grey}（不动），橙红 {plain_orange}→{wide_orange}"
                f"（换档）\n         来回一趟 {back_orange}／灰 {back_grey}；同形状对照链"
                f" {ctl_orange}／灰 {ctl_grey}\n         链子自己的量化漂"
                f" {distance(ctl_orange, plain_orange)} 级，矩阵那份漂"
                f" {distance(back_orange, ctl_orange)} 级"
            )


if __name__ == "__main__":
    main()
