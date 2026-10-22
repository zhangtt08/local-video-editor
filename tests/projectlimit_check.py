"""1.265：`PROJECT_LIMIT` 不再是一句英文耸肩——哪一格、允许几个、这次要存几个都在数里。

起因是量「五十万段」：AGENTS 从 1.166 起每一轮都写「五十万段仍未量」，而真相是**契约上有一道
两万段的门**（`capabilities.limits.max_clips`），撞上去交回的是
`422 PROJECT_LIMIT` +「project exceeds the supported contract limits」+ **空的 details**。
一句没人听得懂的拒绝，等于这道门不存在：人不知道删到什么程度才进得去，Agent 更拿不到数去规划。

这一档钉四件事：
  ① 轨道那一格（128）撞门时，句子点名 `tracks`、允许 128、这次要存 129，`details` 非空；
  ② 那两个数**来自契约自己**：与 `capabilities.limits.max_tracks` 是同一个数（不许抄第二份）；
  ③ 片段那一格真建到两万零一段，同样点名 `clips` 与 20000——贵的是这一次，值的是真数；
  ④ 被拒的那一步不落库：revision 一格不涨，回执里也不留半个字。
界面那句中文不再指「把长段落拆成几条片段」（那一下只会让片段更多）由壳检
`desktop_error_naming_check.ts` 反向钉着。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import MAX_COMMANDS_PER_BATCH, TIMEBASE, capabilities  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402

TOKEN = "projectlimit-check-" + "q" * 41
HEAD = {"Authorization": f"Bearer {TOKEN}"}
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def edit(client: TestClient, pid: str, rev: int, commands: list[dict], rid: str):
    body = {"request_id": rid, "expected_revision": rev, "commands": commands}
    return client.post(f"/v1/projects/{pid}/edits?receipt=slim", json=body, headers=HEAD)


def project(client: TestClient, tag: str) -> tuple[str, int]:
    """每个门各自建一条工程——`request_id` 是幂等的，同名重发交回的是**第一次那一条**。

    这一条本轮真撞上过一次：两扇门共用 `plimit-new` 时，第二扇拿到的是第一扇的 id
    （那份工程已经涨到 revision 2），接着就是 REVISION_CONFLICT。引擎说的是对的，
    说谎的是夹具。
    """
    made = client.post("/v1/projects", json={"request_id": f"plimit-new-{tag}", "name": f"门{tag}"},
                       headers=HEAD).json()["project"]
    return made["id"], made["revision"]


def refused(edit_response, path: str, allowed: int, actual: int, label: str) -> None:
    """一把门的三件数：句子点名、details 非空且带那两个数、这一笔不落库。"""
    assert edit_response.status_code == 422, (label, edit_response.status_code,
                                              edit_response.text[:300])
    error = edit_response.json()["error"]
    assert error["code"] == "PROJECT_LIMIT", (label, error)
    details = error["details"]
    assert details, f"{label}：details 是空的——这一句等于没说"
    assert details.get("contract_path") == path, f"{label}：点名的是 {details}，要 {path}"
    assert details.get("max_length") == allowed, f"{label}：允许那个数不是 {allowed}：{details}"
    assert details.get("actual_length") == actual, f"{label}：这次要存的不止 {actual}：{details}"
    assert path in error["message"], f"{label}：句子没点名那一格：{error['message']}"
    assert str(allowed) in error["message"] and str(actual) in error["message"], (
        f"{label}：句子没把两个数说出来：{error['message']}")
    print(f"PASS {label}: {error['message']}")


def track_door(client: TestClient) -> None:
    """门 ①② ：轨道那一格——便宜、可复现，而且与能力表必须是同一个数。"""
    pid, rev = project(client, "tracks")
    limits = capabilities()["limits"]
    allowed = int(limits["max_tracks"])
    setup = [{"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}}]
    assert edit(client, pid, rev, setup, "plimit-setup").status_code == 200
    rev += 1
    many = [{"op": "track.add", "track": {"id": f"t{i}", "kind": "audio", "name": f"声{i}"}}
            for i in range(allowed - 1)]
    for start in range(0, len(many), MAX_COMMANDS_PER_BATCH):
        chunk = many[start:start + MAX_COMMANDS_PER_BATCH]
        answer = edit(client, pid, rev, chunk, f"plimit-tracks-{start}")
        assert answer.status_code == 200, answer.text[:300]
        rev = answer.json()["revision"]
    have = len(client.get(f"/v1/projects/{pid}", headers=HEAD).json()["tracks"])
    assert have == allowed, f"先把那一格装满：量到 {have}，要 {allowed}"
    before = rev
    over = edit(client, pid, rev,
                [{"op": "track.add", "track": {"id": "t999", "kind": "audio", "name": "多一条"}}],
                "plimit-track-over")
    refused(over, "tracks", allowed, allowed + 1, "轨道那一格")
    after = client.get(f"/v1/projects/{pid}", headers=HEAD).json()
    assert len(after["tracks"]) == allowed, "被拒的那一条轨道落进库里了"
    assert after["revision"] == before, f"被拒那一笔把版本涨了：{before} → {after['revision']}"


def clip_door(client: TestClient, budget: int) -> None:
    """门 ③：片段那一格——真建到两万零一段，句子得说出 20000 这个数。"""
    pid, rev = project(client, "clips")
    setup = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "asset.register", "asset": {"id": "m", "kind": "image", "label": "板",
                                          "reference": "untrusted"}},
    ]
    answer = edit(client, pid, rev, setup, "plimit-clips-setup")
    assert answer.status_code == 200, answer.text[:300]
    rev = answer.json()["revision"]
    allowed = int(capabilities()["limits"]["max_clips"])
    assert allowed == budget, f"这一档按量到的那道门写：{budget}，现在读的是 {allowed}"
    index = 0
    while index < allowed:
        size = min(MAX_COMMANDS_PER_BATCH, allowed - index)
        commands = [{
            "op": "clip.add",
            "clip": {"id": f"c{index + k}", "asset_id": "m", "track_id": "v",
                     "position_ticks": (index + k) * TIMEBASE, "duration_ticks": TIMEBASE,
                     "source_in_ticks": 0}
        } for k in range(size)]
        answer = edit(client, pid, rev, commands, f"plimit-clips-{index}")
        assert answer.status_code == 200, answer.text[:400]
        rev = answer.json()["revision"]
        index += size
    row = client.get("/v1/projects", headers=HEAD).json()["projects"]
    summary = next(item for item in row if item["id"] == pid)
    assert int(summary["clips"]) == allowed, f"列表摘要那格的片段数不是 {allowed}：{summary}"
    over = edit(client, pid, rev,
                [{"op": "clip.add", "clip": {"id": "c-over", "asset_id": "m", "track_id": "v",
                                            "position_ticks": allowed * TIMEBASE,
                                            "duration_ticks": TIMEBASE, "source_in_ticks": 0}}],
                "plimit-clip-over")
    refused(over, "clips", allowed, allowed + 1, "片段那一格")
    after = client.get(f"/v1/projects/{pid}", headers=HEAD).json()
    assert len(after["clips"]) == allowed and after["revision"] == rev, "被拒那一段落库了"


def json_safe_details() -> None:
    """那一格不只得说出数——交出去的每一个数都得**序列化成得了**。

    这一条是套件抓出来的真缺陷（不是猜的）：第一版把 pydantic 的 `ctx` 整个抄进 `details`，
    而**字段校验器抛出来的那一类**错误在 `ctx` 里带的是异常**对象**本身，于是
    `bezier_check` 撞上的是一次 JSON 序列化崩溃——拒绝自己变成了 500，而不是点名哪一道门。
    这里造一份那样的错误（不靠找某条 HTTP 门，形状是确定的），量两件事：`details` 非空、
    而且 `json.dumps` 得过。
    """
    from pydantic import BaseModel, ValidationError, field_validator

    from agentcut.timeline import _contract_limit_refusal

    class Narrow(BaseModel):
        bezier_x: float

        @field_validator("bezier_x")
        @classmethod
        def _reject(cls, value: float) -> float:
            raise ValueError("bezier x must be within 0..1")

    try:
        Narrow.model_validate({"bezier_x": 3.0})
    except ValidationError as error:
        refusal = _contract_limit_refusal(error)
    else:
        raise AssertionError("夹具没能造出一份带异常对象的校验错误")
    assert refusal.details.get("contract_path") == "bezier_x", refusal.details
    assert refusal.details.get("reason") == "value_error", refusal.details
    assert refusal.details, "details 又空了——那句拒绝等于没说"
    try:
        json.dumps(refusal.details)
    except TypeError as error:
        keys = ", ".join(sorted(refusal.details))
        raise AssertionError(
            f"拒绝自己序列化不出去——HTTP 那一边就是一次崩溃而不是一道门：{error}；keys={keys}"
        ) from None
    print(f"PASS 校验器那一类门: {refusal.message}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agentcut-plimit-") as raw:
        folder = Path(raw)
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG,
                             str(FFPROBE))
        store = ProjectStore(media.db_path, media)
        # TestClient 只在当上下文管理器用的那一次跑 lifespan，而 `state.projects` 就在那儿建
        with TestClient(create_app(store.path, TOKEN, media),
                        base_url="http://127.0.0.1:8791", headers=HEAD) as client:
            track_door(client)
            clip_door(client, 20_000)
            json_safe_details()
    print("PASS: PROJECT_LIMIT 把哪一格、允许几个、这次要存几个都说出来了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
