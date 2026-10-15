"""编译好的那张图自己得说得通：每条层链读的 pad 必须真被声明过，而它 trim 的长度不得超过那一路输入
自己声明的 `-t`。

这两条形状就是 1.166 那次遮蔽的签名（层链从 `0,1,2,3,4` 变成 `0,2,2,3,4`）：FFmpeg 对这种矛盾毫不
介意——它交回一张**什么都没有**的画面，任务退 0，`GET /v1/frame` 回 200。所以拒绝必须发生在编译时，
而不是等人去盯成片。

这里量三件事：健康的真实工程编译得出来、每个声明过的输入都被图上读到（并钉住那一路输入自己报的
秒数）、把 1.166 那一幕**手搓进同一份 plan**（某一路输入没人读）时拒绝点名它的 pad；最后一条是
故意量「不判」的那一面——链子 trim 得比声明的 `-t` 长，在四点点位与变速那一路是合法的，所以它只在
这里被量下来，不当成拒绝（这一条第一次进套件就误伤了它们，是套件把它挡回去的）。
"""

from __future__ import annotations

import copy
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import EditorError, Project
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan, declared_input_windows, validate_plan_inputs

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "planinput-check-" + "q" * 48
F = T // 30
SRC = (ROOT / "src/agentcut/render.py").read_text(encoding="utf-8")


def make_media(folder: Path) -> list[Path]:
    out = []
    for name, colour in (("red", "red"), ("blue", "blue")):
        path = folder / f"{name}.mp4"
        done = subprocess.run(
            [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=c={colour}:s=320x180:r=30:d=2",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p", str(path)],
            capture_output=True, check=False)
        assert done.returncode == 0, done.stderr[-200:].decode(errors="replace")
        out.append(path)
    return out


def trim_of(graph: str, pad: int) -> list[float]:
    return [float(value) for index, value in re.findall(
        r"\[(\d+):v\][^\n]*?trim=duration=([0-9.]+)", graph) if int(index) == pad]


def main() -> None:
    # ① 单位级：`-t` 归谁，按 `-i` 切块才算得准，倒着数几个 token 是猜
    windows = declared_input_windows([
        "-f", "lavfi", "-t", "2.000000", "-i", "color=black:s=2x2",
        "-ss", "0", "-t", "1.000000", "-i", "red.mp4",
        "-loop", "1", "-i", "plate.png"])
    assert windows == [2.0, 1.0, None], windows
    print("   切块：每路输入拿到的就是它自己那一格的 -t，没有 -t 的那路是 None")

    work = Path(tempfile.mkdtemp(prefix="planinput-"))
    media_dir = work / "media"
    media_dir.mkdir(parents=True)
    paths = make_media(media_dir)
    media = MediaService(work / "db.sqlite3", [media_dir], work / "cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    with TestClient(create_app(store.path, TOKEN, media),
                    base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        records = []
        for path in paths:
            ans = client.post("/v1/media/import", json={"path": str(path)})
            assert ans.status_code == 200, ans.text
            records.append(ans.json())
        made = client.post("/v1/projects", json={
            "request_id": "pi-new", "name": "层链与输入配对",
            "settings": {"width": 320, "height": 180,
                         "frame_rate": {"numerator": 30, "denominator": 1}}}).json()["project"]
        pid = made["id"]

        def edit(request_id: str, commands: list[dict]) -> Project:
            ans = client.post(f"/v1/projects/{pid}/edits", json={
                "request_id": request_id, "expected_revision": revision[0], "commands": commands})
            assert ans.status_code == 200, (request_id, ans.text[:500])
            body = ans.json()["project"]
            revision[0] = body["revision"]
            return Project.model_validate(body)

        revision = [made["revision"]]
        project = edit("pi-seed", [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
            {"op": "asset.import", "asset_id": "a0", "label": "红",
             "probe_id": records[0]["id"], "verified": records[0]["verified"]},
            {"op": "asset.import", "asset_id": "a1", "label": "蓝",
             "probe_id": records[1]["id"], "verified": records[1]["verified"]},
            {"op": "clip.add", "clip": {"id": "c", "asset_id": "a0", "track_id": "v",
                                        "position_ticks": 0, "duration_ticks": 2 * T}},
            {"op": "clip.add", "clip": {"id": "c2", "asset_id": "a1", "track_id": "v",
                                        "position_ticks": 2 * T, "duration_ticks": T}},
        ])
        turned = edit("pi-mask", [
            {"op": "clip.mask", "clip_id": "c", "mask": {
                "shape": "rectangle", "center_x": 0.5, "center_y": 0.5, "width": 0.5,
                "height": 0.2, "rotation": 30.0}},
            {"op": "keyframe.set", "clip_id": "c",
             "keyframe": {"property": "mask_rotation", "at_ticks": 0, "value": 10.0}},
            {"op": "keyframe.set", "clip_id": "c",
             "keyframe": {"property": "mask_width", "at_ticks": 0, "value": 0.4}},
            {"op": "keyframe.set", "clip_id": "c",
             "keyframe": {"property": "mask_width", "at_ticks": 2 * T, "value": 0.8}},
        ])
        morphed = edit("pi-path", [
            {"op": "clip.mask", "clip_id": "c2", "mask": {
                "shape": "path", "center_x": 0.5, "center_y": 0.5, "width": 0.6, "height": 0.6,
                "vertices": [{"x": 0.3, "y": 0.3}, {"x": 0.7, "y": 0.35}, {"x": 0.5, "y": 0.8}]}},
        ])

    shapes = (("两段并排", project), ("转过的盒带宽高针", turned), ("轮廓遮罩", morphed))
    for label, sample in shapes:
        plan = compile_render_plan(sample, "h264-source-quality")
        graph = "\n".join(plan.filters)
        declared = declared_input_windows(plan.input_args)
        assert len(declared) == plan.input_args.count("-i"), (label, declared)
        read = {int(pad) for pad in re.findall(r"\[(\d+):[va]\]", graph)}
        read |= {int(pad) for pad in re.findall(r"(?:^|[ ,;\[])(\d+):[av]\b", graph)}
        assert all(pad in read for pad in range(len(declared))), (label, declared, sorted(read))
        for pad, value in re.findall(r"\[(\d+):v\][^\n]*?trim=duration=([0-9.]+)", graph):
            want = declared[int(pad)]
            assert want is None or float(value) - want <= 1e-6, (label, pad, value, want)
        print(f"   健康：{label} 编译得出，{len(declared)} 路输入全被引用，"
              f"每条链 trim 都在它那一路声明的秒数之内 {declared}")

    # ② 钉一个真实的数：第二条片段长 1 秒，它那一路输入就必须 declare 1.0 秒——不是再算一遍
    plan = compile_render_plan(project, "h264-source-quality")
    assert 1.0 in declared_input_windows(plan.input_args), declared_input_windows(plan.input_args)

    # ③ 手搓 1.166 那一幕：把某一路输入从图上抹掉，编译层得点名它
    broken = copy.deepcopy(plan)
    pad_read = {int(pad) for pad in re.findall(r"\[(\d+):[va]\]", "\n".join(broken.filters))}
    victim = max(pad_read - {0})
    broken.filters = [line.replace(f"[{victim}:", "[99:") for line in broken.filters]
    try:
        validate_plan_inputs(broken)
        raise AssertionError("孤儿 pad 竟然过了")
    except EditorError as error:
        assert error.code == "PLAN_INPUT_UNREFERENCED", error.code
        assert error.details["pad"] == victim, error.details
        print(f"   拒绝：输入 {victim} 没人读 -> {error.code}")

    # ④ 另一条形状**故意不判**：链子按 8 秒 trim 而它那一路只 declare 1 秒。四点点位与变速那一路
    #    会在拉伸后的时间轴上合法地 trim 得比源窗长——这条拒绝在套件第一次跑就误伤了它们，所以这里
    #    只把「不判」量下来，而不是把它当成规矩交出去。
    over = copy.deepcopy(plan)
    pads = [int(pad) for pad, _ in re.findall(
        r"\[(\d+):v\][^\n]*?trim=duration=([0-9.]+)", "\n".join(over.filters))]
    target = next(pad for pad in pads if declared_input_windows(over.input_args)[pad] == 1.0)
    hit = next(i for i, line in enumerate(over.filters)
               if re.search(rf"\[{target}:v\].*trim=duration=", line))
    over.filters[hit] = re.sub(r"trim=duration=[0-9.]+", "trim=duration=8.000000",
                               over.filters[hit], count=1)
    validate_plan_inputs(over)
    print(f"   不判：输入 {target} declare 1 秒而链子按 8 秒 trim——这份 plan 照样编译得过去")

    # ⑤ 没有 -t 的那一路（一张静态图板）不归这条判断管：给它一个天大的 trim 也不该红
    plain = copy.deepcopy(plan)
    none_pads = [pad for pad, value in enumerate(declared_input_windows(plain.input_args))
                 if value is None]
    if none_pads:
        pad = none_pads[0]
        hit = next((i for i, line in enumerate(plain.filters)
                    if re.search(rf"\[{pad}:v\].*trim=duration=", line)), None)
        if hit is not None:
            plain.filters[hit] = re.sub(r"trim=duration=[0-9.]+", "trim=duration=99.0",
                                        plain.filters[hit], count=1)
        validate_plan_inputs(plain)
        print(f"   不误伤：输入 {pad} 没 declare -t，这条判断不判它")
    else:
        print("   不误伤：这份 plan 里每一路都 declare 了 -t，无静态板可量")

    # ⑥ 编译器真的调用它——不是只有一函数摆着没人用
    two_plan = compile_render_plan(project, "h264-source-quality")
    heads = [int(pad) for pad in re.findall(r"^\[(\d+):v\]", "\n".join(two_plan.filters), re.M)]
    assert heads and len(heads) == len(set(heads)), heads
    print(f"   健康：层链头各读各的 pad {heads}，没有哪一路被读两次")

    # 手搓：把一条**媒体**层链整个再挂一遍——图上一个孤儿都不留，但同一路被两条链读
    twice = copy.deepcopy(two_plan)
    pattern = re.compile(r"^\[(\d+):v\]")

    def head_pad(line: str) -> int | None:
        matched = pattern.match(line)
        return int(matched.group(1)) if matched else None

    source_chain = next(line for line in twice.filters
                        if (head_pad(line) or 0) > 0 and line == line.strip())
    twice.filters.append(source_chain)
    try:
        validate_plan_inputs(twice)
        raise AssertionError("两条链读同一路竟然过了")
    except EditorError as error:
        assert error.code == "PLAN_INPUT_DOUBLE_READ", error.code
        assert error.details["chain_count"] == 2, error.details
        print(f"   拒绝：输入 {error.details['pad']} 被两条层链读 -> {error.code}")

    # 生成的那一路（黑底画布）允许被合成多次：这条判断只管真实素材的输入。这里不能再猜「0 号就是
    # 画布」——同一个门禁第一次跑就量到 0 号其实是 red.mp4，那种猜测会让这条误伤检查自己变成假的。
    sources = [two_plan.input_args[position + 1] for position, token in enumerate(
        two_plan.input_args) if token == "-i"]
    generated_pads = [index for index, value in enumerate(sources)
                      if value.startswith(("color=", "nullsrc", "anullsrc", "sine="))]
    if generated_pads:
        canvas = copy.deepcopy(two_plan)
        pad = generated_pads[0]
        head = next((line for line in canvas.filters if head_pad(line) == pad), None)
        if head is None:
            print(f"   不误伤：输入 {pad} 是生成的那一路，在这份 plan 里不当层链头，"
                  "没有可重读的形状可量")
        else:
            canvas.filters.append(head)
            validate_plan_inputs(canvas)
            print(f"   不误伤：生成的那一路（输入 {pad}）再被读一次不算矛盾")
    else:
        print("   不误伤：这份 plan 里没有生成的那一路可量（画布不占输入），跳过")

    assert "validate_plan_inputs(plan)" in SRC, "编译收尾没调用那份结构检查"
    assert SRC.index("validate_plan_inputs(plan)") > SRC.index("def compile_render_plan("), \
        "调用点在编译函数之外"
    print("   接线：compile_render_plan 收尾就调 validate_plan_inputs(plan)")
    print("PASS: 没人读的 pad 在编译时点名；越过声明的 trim 只量不判")


if __name__ == "__main__":
    main()
