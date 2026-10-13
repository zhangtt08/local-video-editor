"""图像序列交付（OpenEXR / DPX）：交付物是一串文件，就得按帧点货。

开链（image sequence）是影视后期的通货：调色、合成、套底都在序列之间走。1.142 把 EXR 与 DPX
两条加进闭表之后，「交付」这个词在这里的含义变了——不再是一个文件，而是 N 个：

1. **一帧一个文件**，数量必须等于计划里的帧数。FFmpeg 写坏序列的方式不是非零退出，而是少写
   两帧、中间断一号、最后一帧只写了个头；只看退出码与「目录存在」全都绿。
2. **顺序由帧号承担**。把整串序列当一条流 conform 回来逐帧读 RGB，才是剪辑师真正会做的那一步：
   少了、乱了、错位了，颜色序列立刻不对。
3. **没有容器 = 没有声音，也没有起始时间码**。这两样都点名拒，而不是收下之后再什么都不做；
   拒的时候一个文件都不许落盘。
4. **alpha 是真的那一层**：空洞处读回 0，实心处 255，半透明处 ~127，而关掉「透明背景」的同一条
   时间线必须处处 255——那个对照跑才是「这一层没被烘进画面」的证据。
5. **不覆盖上一次交付**：同名再来一次，目录名往后让，先那份的字节一个都不许变。
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import capabilities, render_presets
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
SECOND = T
FRAME = T // 30
EXR = "exr-sequence"
DPX = "dpx-sequence"


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def rgb_source(folder: Path) -> Path:
    """三秒、每秒一个纯色：红 / 绿 / 蓝。序列错一帧、乱一号，颜色序列就对不上。"""
    target = folder / "rgb-3s.mp4"
    parts: list[str] = []
    for colour in ("red", "green", "blue"):
        parts += ["-f", "lavfi", "-i", f"color=c={colour}:s={SRC_W}x{SRC_H}:r=30:d=1"]
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            *parts,
            "-filter_complex",
            "concat=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            str(target),
        ]
    )
    return target


def plate_source(folder: Path) -> Path:
    """两秒的亮洋红底加一块绿方：与 alphamaster 同一块板子，alpha 的三个区好对照。"""
    target = folder / "plate-2s.mov"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0xFF00FF:s={SRC_W}x{SRC_H}:r=30:d=2.0,format=yuv444p,"
            f"drawbox=x=40:y=40:w=80:h=60:color=0x00FF00:t=fill",
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


def colour(red: int, green: int, blue: int) -> str:
    if red > 150 and green < 100 and blue < 100:
        return "红"
    if green > 90 and red < 100 and blue < 100:
        return "绿"
    if blue > 150 and red < 100 and green < 100:
        return "蓝"
    if max(red, green, blue) < 24:
        return "黑"
    return f"其它{red}:{green}:{blue}"


def conform(pattern: Path, rate: int, frames: int) -> list[str]:
    """把整串序列当一条流读回来，逐帧给一个颜色名——一次 FFmpeg 点完 N 帧。"""
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-framerate",
            rate,
            "-start_number",
            1,
            "-i",
            pattern,
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    ).stdout
    assert len(raw) == frames * 3, (len(raw), frames)
    return [colour(*raw[index : index + 3]) for index in range(0, len(raw), 3)]


def alpha_bytes(pattern: Path, rate: int, frames: int) -> list[int]:
    """逐帧的 alpha 字节：`alphaextract` 把那一层搬成灰度，再缩成 1x1 读一个数。"""
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-framerate",
            rate,
            "-start_number",
            1,
            "-i",
            pattern,
            "-vf",
            "alphaextract,scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
    ).stdout
    assert len(raw) == frames, (len(raw), frames)
    return list(raw)


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def deliver(client: TestClient, path: str, body: dict) -> dict:
    answer = client.post(path + "/renders", json=body)
    assert answer.status_code == 200, answer.text
    return wait(client, answer.json()["job"]["id"])


def frames_in(folder: Path, stem: str, container: str) -> list[Path]:
    return sorted(folder.glob(f"{stem}.*.{container}"))


def project_with(client: TestClient, clip: Path, label: str, tag: str, spans: list):
    """建一个工程：一条 v 轨，若干段 (起始帧, 结束帧, 不透明度)。`tag` 是 ASCII 的请求号前缀。"""
    probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
    created = client.post(
        "/v1/projects",
        json={
            "request_id": f"{tag}-new",
            "name": label,
            "settings": {
                "width": SRC_W,
                "height": SRC_H,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
        },
    )
    assert created.status_code == 200, created.text
    project = created.json()["project"]
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {
            "op": "asset.import",
            "asset_id": "a",
            "label": "a",
            "probe_id": probe["id"],
            "verified": probe["verified"],
        },
    ]
    for index, (start, end, opacity) in enumerate(spans):
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": f"c{index}",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": start * FRAME,
                    "duration_ticks": (end - start) * FRAME,
                    "effects": {"opacity": opacity},
                },
            }
        )
    seeded = client.post(
        f"/v1/projects/{project['id']}/edits",
        json={"request_id": f"{tag}-seed", "expected_revision": 0, "commands": commands},
    )
    assert seeded.status_code == 200, seeded.text
    return project["id"], seeded.json()["project"]["revision"]


def main() -> None:
    table = {item["id"]: item for item in render_presets()}
    for preset_id in (EXR, DPX):
        assert table[preset_id]["sequence"] is True, table[preset_id]
        # 序列自带 alpha 层：`alpha` 与 `sequence` 是两个不同的开关，这里两条都该是真。
        assert table[preset_id]["alpha"] is True, table[preset_id]
        assert table[preset_id]["audio_codec"] == "", table[preset_id]
    caps = capabilities()
    assert caps["sequence_presets"] == [EXR, DPX], caps["sequence_presets"]

    with tempfile.TemporaryDirectory(prefix="agentcut-seq-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "seq-db.sqlite3", [folder], folder / "seq-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "seq-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "seqcheck" + "e" * 56
        app = create_app(folder / "seq-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            rgb = rgb_source(folder)
            project_id, revision = project_with(client, rgb, "开链", "seq", [(0, 90, 1.0)])
            path = f"/v1/projects/{project_id}"

            # ---- 1) 干跑：计划里就没有声音这一说，也没有那条 -map
            dry = client.get(path + f"/render-plan?preset_id={EXR}&revision={revision}").json()
            joined = " ".join(dry["argv_preview"])
            assert dry["plan"]["sequence"] is True and dry["plan"]["audio"] is False, dry["plan"]
            assert "-c:v exr -pix_fmt rgba64le -an" in joined, joined[-260:]
            assert "-map [aout]" not in joined, "序列的计划还是把声音流 map 了出去"
            assert "-c:a" not in joined and "-b:a" not in joined, joined[-260:]

            # ---- 2) 落盘：90 帧、编号从 000001 起连续、conform 回来逐帧对色
            job = deliver(
                client,
                path,
                {
                    "request_id": "seq-exr-full",
                    "expected_revision": revision,
                    "preset_id": EXR,
                    "filename": "全片.exr",
                },
            )
            assert job["status"] == "succeeded", job
            pattern = Path(job["output_path"])
            assert pattern.name == "全片.%06d.exr", pattern
            delivered = pattern.parent
            assert delivered.is_dir() and not pattern.exists(), delivered
            files = frames_in(delivered, "全片", "exr")
            assert len(files) == 90, len(files)
            assert files[0].name == "全片.000001.exr", files[0].name
            assert files[-1].name == "全片.000090.exr", files[-1].name
            assert [int(f.name[3:9]) for f in files] == list(range(1, 91))
            read = conform(pattern, 30, 90)
            assert read == ["红"] * 30 + ["绿"] * 30 + ["蓝"] * 30, (
                read[:6],
                read[28:34],
                read[58:64],
                read[-3:],
            )
            assert job["output_size_bytes"] == sum(f.stat().st_size for f in files) > 0, job
            assert "共 90 帧" in job["message"] and "全片/" in job["message"], job["message"]
            assert not list(exports.glob("*.part")), "临时目录还在"

            # ---- 3) 不覆盖上一次交付：同名再来一次，目录往后让，先那份一字节都不动
            before = [(f.name, f.stat().st_size) for f in files]
            again = deliver(
                client,
                path,
                {
                    "request_id": "seq-exr-again",
                    "expected_revision": revision,
                    "preset_id": EXR,
                    "filename": "全片.exr",
                },
            )
            assert again["status"] == "succeeded", again
            second = Path(again["output_path"])
            assert second.parent.name == "全片-2", second.parent
            after = [(f.name, f.stat().st_size) for f in frames_in(delivered, "全片", "exr")]
            assert after == before, "同名第二次交付动了先那一份"
            assert len(frames_in(second.parent, "全片-2", "exr")) == 90

            # ---- 4) 标记区间 × 交付帧率：序列也吃 1.139 那把尺子
            marked = client.post(
                path,
                json={
                    "request_id": "seq-marks",
                    "expected_revision": revision,
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                        "in_ticks": SECOND,
                        "out_ticks": 2 * SECOND,
                    },
                },
            )
            assert marked.status_code == 200, marked.text
            revision = marked.json()["project"]["revision"]
            window = deliver(
                client,
                path,
                {
                    "request_id": "seq-marks-dpx",
                    "expected_revision": revision,
                    "preset_id": DPX,
                    "filename": "中段.dpx",
                    "range": "marks",
                    "output_frame_rate": {"numerator": 25, "denominator": 1},
                },
            )
            assert window["status"] == "succeeded", window
            dpx_pattern = Path(window["output_path"])
            dpx_files = frames_in(dpx_pattern.parent, "中段", "dpx")
            assert len(dpx_files) == 25, len(dpx_files)
            assert dpx_files[0].name == "中段.000001.dpx", dpx_files[0].name
            window_read = conform(dpx_pattern, 25, 25)
            assert set(window_read) == {"绿"}, window_read[:4] + window_read[-4:]
            print(
                f"   整串 {len(files)} 个文件（{files[0].name}…{files[-1].name}），conform 回来"
                f"逐帧是 30 红 / 30 绿 / 30 蓝；1..2 秒的窗口按 25 交 DPX 是 {len(dpx_files)} 帧，"
                "读回来全是绿"
            )

            # ---- 5) 点名拒：序列挂不住起始时间码，而且拒的时候不落盘
            listed_before = sorted(item.name for item in exports.iterdir())
            refused = client.post(
                path + "/renders",
                json={
                    "request_id": "seq-timecode",
                    "expected_revision": revision,
                    "preset_id": EXR,
                    "filename": "拒单.exr",
                    "timecode": "01:00:00:00",
                },
            )
            assert refused.status_code == 422, refused.text
            failure = refused.json()["error"]
            assert failure["code"] == "SEQUENCE_NEEDS_CONTAINER", failure
            assert "帧号就是位置" in failure["message"], failure["message"]
            assert sorted(item.name for item in exports.iterdir()) == listed_before, (
                "拒单之前已经把目录建出来了"
            )
            wrong_ext = client.post(
                path + "/renders",
                json={
                    "request_id": "seq-ext",
                    "expected_revision": revision,
                    "preset_id": EXR,
                    "filename": "开链.mp4",
                },
            )
            assert wrong_ext.status_code == 422, wrong_ext.text
            complaint = json.dumps(wrong_ext.json(), ensure_ascii=False)
            assert ".exr for the exr-sequence preset" in complaint, complaint

            # ---- 6) alpha 那一层是真层：空洞 0、实心 255、半透明 ~127，关掉就处处 255
            plate = plate_source(folder)
            matte_id, matte_revision = project_with(
                client, plate, "透明序列", "matte", [(15, 45, 1.0), (48, 60, 0.5)]
            )
            matte_path = f"/v1/projects/{matte_id}"
            matte = deliver(
                client,
                matte_path,
                {
                    "request_id": "seq-alpha-on",
                    "expected_revision": matte_revision,
                    "preset_id": EXR,
                    "filename": "带键.exr",
                    "transparent": True,
                },
            )
            assert matte["status"] == "succeeded", matte
            matte_pattern = Path(matte["output_path"])
            on = alpha_bytes(matte_pattern, 30, 60)
            control = deliver(
                client,
                matte_path,
                {
                    "request_id": "seq-alpha-off",
                    "expected_revision": matte_revision,
                    "preset_id": EXR,
                    "filename": "无键.exr",
                    "transparent": False,
                },
            )
            assert control["status"] == "succeeded", control
            off = alpha_bytes(Path(control["output_path"]), 30, 60)
            assert on[6] == 0, on[:12]
            assert on[30] == 255, on[24:36]
            assert 118 <= on[54] <= 137, on[48:60]
            assert set(off) == {255}, (min(off), max(off))
            print(
                f"   alpha 逐帧读回来：空洞第 7 帧 {on[6]}、实心第 31 帧 {on[30]}、"
                f"半透第 55 帧 {on[54]}；同一条时间线关掉透明是 {min(off)}..{max(off)}"
            )

            stored = {
                item["filename"]: item["transparent"]
                for item in client.get(matte_path + "/jobs").json()["jobs"]
            }
            # 存下来的 `filename` 就是那串文件的名字模板——序列交付没有「一个文件名」可写。
            assert stored == {"带键.%06d.exr": True, "无键.%06d.exr": False}, stored
    print(f"   序列预设 {caps['sequence_presets']}：一帧一个文件，按帧点数、按帧验色、按层验 alpha")


if __name__ == "__main__":
    main()
