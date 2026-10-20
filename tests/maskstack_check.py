"""1.221：一条片段再叠一块矩形/椭圆的遮罩——真像素、两端的图、拒绝与旧行兼容。

这一档量的不是「字段存进去了」，而是**那块多出来的洞真的把画面切掉了**：
白底板 + 主遮罩留中间一条 + 再叠一块留右边一条，两块的交集才露出来。
关键是那一个点：`x=0.30` 在主遮罩里、在再叠那块外——没有这块时它是白的，
有了之后必须是黑的。少了这个对照，任何「遮罩没生效」的回归都会绿着过去。
"""
from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import (  # noqa: E402
    MASK_STACK_LIMIT,
    Clip,
    CreateProject,
    EditBatch,
    Project,
    ShapeMask,
)
from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402

TOKEN = "maskstack-check-" + "s" * 48
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
BOX = {"shape": "rectangle", "feather": 0.0}
PRIMARY = {"shape": "rectangle", "feather": 0.0, "center_x": 0.5, "center_y": 0.5,
           "width": 0.6, "height": 0.6}
EXTRA = {"shape": "rectangle", "feather": 0.0, "center_x": 0.75, "center_y": 0.5,
         "width": 0.5, "height": 0.5}
NARROW = {"shape": "rectangle", "feather": 0.0, "center_x": 0.65, "center_y": 0.5,
          "width": 0.1, "height": 0.5}


def clip_body(**over) -> dict:
    base = {"id": "z", "asset_id": "a", "track_id": "v",
            "position_ticks": 0, "duration_ticks": T}
    base.update(over)
    return base


def bright(pixel) -> bool:
    return sum(pixel) > 300


def dark(pixel) -> bool:
    return sum(pixel) < 90


def contract_leg() -> None:
    """上限、类型、旧行：这三件事在契约那一层，不碰素材就能钉住。"""
    assert MASK_STACK_LIMIT == 4, MASK_STACK_LIMIT
    one = Clip.model_validate(clip_body(
        id="c", asset_id="a",
        extra_masks=[dict(BOX, center_x=0.3), dict(BOX, center_x=0.7)]))
    assert len(one.extra_masks) == 2, one.extra_masks
    assert all(isinstance(item, ShapeMask) for item in one.extra_masks), one.extra_masks
    assert one.mask is None, "再叠的那几块不许顺手造出一个主遮罩"
    assert [item.center_x for item in one.extra_masks] == [0.3, 0.7], one.extra_masks
    try:
        Clip.model_validate(clip_body(
            id="c", asset_id="a",
            extra_masks=[dict(BOX) for _ in range(MASK_STACK_LIMIT + 1)]))
        raise AssertionError("超出上限的 extra_masks 被收了")
    except ValidationError:
        pass
    document = Project.model_validate({
        "id": "p", "name": "n",
        "tracks": [{"id": "v", "kind": "video", "name": "v"}],
        "clips": {"c": clip_body(id="c", asset_id="a", mask=dict(BOX))},
    }).model_dump(mode="json")
    assert "extra_masks" in document["clips"]["c"], document["clips"]["c"].keys()
    del document["clips"]["c"]["extra_masks"]
    legacy = Project.model_validate(document)
    assert legacy.clips["c"].extra_masks == [], legacy.clips["c"].extra_masks


def receipt_leg(store) -> None:
    """提了空列表的旧载荷必须与压根没提的同一份指纹；真多了一块就必须变。"""

    def fingerprint(body: dict):
        batch = EditBatch.model_validate({
            "request_id": "fp-a", "expected_revision": 1,
            "commands": [{"op": "clip.add", "clip": dict(body)}],
        })
        return store._fingerprint("edit", batch)

    empty = fingerprint(clip_body(extra_masks=[]))
    assert empty == fingerprint(clip_body()), "空列表与没提这个字段是同一份指纹，旧回执才不裂"
    assert fingerprint(clip_body(extra_masks=[dict(BOX)])) != empty, "多了一块却算同一份指纹"


def main() -> None:
    contract_leg()
    ffmpeg = str(FFMPEG)
    with tempfile.TemporaryDirectory(prefix="agentcut-maskstack-") as temp:
        folder = Path(temp)
        media_dir = folder / "media"
        media_dir.mkdir()
        plate = media_dir / "white.mp4"
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=white:s=320x180:r=30:d=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(plate)],
            check=True, creationflags=0x08000000,
        )
        media = MediaService(folder / "db.sqlite3", [media_dir], folder / "cache",
                             ffmpeg, str(FFPROBE))
        store = ProjectStore(media.db_path, media)
        made = store.create(CreateProject(request_id="stack-new", name="stack"))
        project_id = made.project.id
        probe_media = media.import_file(str(plate))
        client = TestClient(
            create_app(store.path, TOKEN, media),
            base_url="http://127.0.0.1:8791",
            headers={"Authorization": "Bearer " + TOKEN},
        )

        def edit(revision, commands, request_id):
            body = {"request_id": request_id, "expected_revision": revision,
                    "commands": commands}
            response = client.post(f"/v1/projects/{project_id}/edits", json=body)
            assert response.status_code == 200, response.text[:300]
            return response.json()["project"]["revision"]

        def head():
            return client.get(f"/v1/projects/{project_id}").json()

        def probe(revision):
            """引擎那一帧的原始像素，按归一化坐标取样（与导出读的是同一条 alpha）。"""
            url = f"/v1/projects/{project_id}/frame?revision={revision}&at_ticks={T}"
            answer = client.get(url)
            assert answer.status_code == 200, answer.text[:200]
            width, height = struct.unpack(">II", answer.content[16:24])
            raw = subprocess.run(
                [ffmpeg, "-v", "error", "-i", "pipe:0", "-f", "rawvideo",
                 "-pix_fmt", "rgb24", "pipe:1"],
                input=answer.content, capture_output=True, check=True,
                creationflags=0x08000000,
            ).stdout

            def at(x: float, y: float):
                offset = (int(y * height) * width + int(x * width)) * 3
                return tuple(raw[offset : offset + 3])

            return at

        def manifest(revision):
            answer = client.get(
                f"/v1/projects/{project_id}/preview-manifest?revision={revision}")
            assert answer.status_code == 200, answer.text[:200]
            return answer.json()["clips"]["w"]

        def refusal(request_id, command, code, needle=""):
            before = head()["revision"]
            answer = client.post(f"/v1/projects/{project_id}/edits", json={
                "request_id": request_id, "expected_revision": before,
                "commands": [command]})
            assert answer.status_code == 422, (needle or code, answer.text[:220])
            problem = answer.json()["error"]
            assert problem["code"] == code, (needle or code, problem)
            if needle:
                assert needle in problem["message"], (needle, problem["message"])
            assert head()["revision"] == before, "被拒那一手写了状态"

        with client:
            revision = edit(made.project.revision, [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                {"op": "asset.import", "asset_id": "w", "label": "白",
                 "probe_id": probe_media.id,
                 "verified": probe_media.verified.model_dump()},
                {"op": "clip.add", "clip": {"id": "w", "asset_id": "w", "track_id": "v",
                                            "position_ticks": 0, "duration_ticks": 2 * T}},
                {"op": "clip.mask", "clip_id": "w", "mask": dict(PRIMARY)},
            ], "stack-seed")

            # ① 对照：只有主遮罩时 x=0.30 是白的（这一条不成立，后面那块黑的就没有意义）
            at = probe(revision)
            assert bright(at(0.30, 0.5)), ("对照那一帧：主遮罩里 x=0.30 应该是白的", at(0.30, 0.5))
            assert bright(at(0.65, 0.5)) and dark(at(0.05, 0.5)), (at(0.65, 0.5), at(0.05, 0.5))

            # ② 再叠一块：两块都留的那一格才露出来
            revision = edit(revision, [
                {"op": "clip.mask_stack", "clip_id": "w", "masks": [dict(EXTRA)]},
            ], "stack-one")
            at = probe(revision)
            assert bright(at(0.65, 0.5)), ("两块都留的那一格必须是白的", at(0.65, 0.5))
            assert dark(at(0.30, 0.5)), ("主遮罩里、再叠那块外——必须是黑的", at(0.30, 0.5))
            assert dark(at(0.90, 0.5)) and dark(at(0.05, 0.5)), (at(0.90, 0.5), at(0.05, 0.5))

            # ③ 预览清单交回的就是这几块的图，浏览器叠的是同一批
            entry = manifest(revision)
            images = entry.get("extra_mask_images") or []
            assert len(images) == 1 and images[0].startswith("url("), list(entry)
            assert entry["mask_image"] and entry["mask_image"] != images[0], "两块同一张图？"

            # ④ 两块一起叠：三块的交集
            revision = edit(revision, [
                {"op": "clip.mask_stack", "clip_id": "w",
                 "masks": [dict(EXTRA), dict(NARROW)]},
            ], "stack-two")
            at = probe(revision)
            assert bright(at(0.65, 0.5)), ("三块都留的那一格（0.65）必须是白的", at(0.65, 0.5))
            assert dark(at(0.90, 0.5)), ("第三块外（0.90）必须是黑的", at(0.90, 0.5))
            assert len(manifest(revision)["extra_mask_images"]) == 2, list(manifest(revision))

            # ⑤ 清空就是清空：一块不剩等于回到只有主遮罩
            revision = edit(revision, [
                {"op": "clip.mask_stack", "clip_id": "w", "masks": []},
            ], "stack-empty")
            at = probe(revision)
            assert bright(at(0.30, 0.5)), ("删干净之后 x=0.30 要回到白", at(0.30, 0.5))
            assert head()["clips"]["w"]["extra_masks"] == [], head()["clips"]["w"]

            # ⑥ 拒绝各有名字，而且都不写状态
            path_mask = {"shape": "path", "vertices": [
                {"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.5, "y": 0.8}]}
            refusal("stack-reject-path",
                    {"op": "clip.mask_stack", "clip_id": "w", "masks": [path_mask]},
                    "INVALID_MASK", "复制一层")
            refusal("stack-reject-many", {"op": "clip.mask_stack", "clip_id": "w",
                                          "masks": [dict(BOX)] * (MASK_STACK_LIMIT + 1)},
                    "INVALID_REQUEST")

            # ⑦ 幂等：同一个 request_id 与同一份载荷重发，不涨版本、也不多出第二块来
            before = head()["revision"]
            body = {"request_id": "stack-idem", "expected_revision": before,
                    "commands": [{"op": "clip.mask_stack", "clip_id": "w",
                                  "masks": [dict(EXTRA), dict(EXTRA)]}]}
            first = client.post(f"/v1/projects/{project_id}/edits", json=body)
            assert first.status_code == 200, first.text[:220]
            after = first.json()["project"]["revision"]
            again = client.post(f"/v1/projects/{project_id}/edits", json=body)
            assert again.status_code == 200, again.text[:220]
            assert again.json()["project"]["revision"] == after, "重发那一次涨了版本"
            stored = again.json()["project"]["clips"]["w"]["extra_masks"]
            assert len(stored) == 2, stored

            receipt_leg(store)

    print("PASS: 再叠的遮罩真的把画面切掉了（对照 x=0.30 由白转黑）、预览清单交回同样的图、"
          "清空回到只有主遮罩、自由形状与超限都点名拒绝且不写状态、旧行读回就是没有")


if __name__ == "__main__":
    main()
