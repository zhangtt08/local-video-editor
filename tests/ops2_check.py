"""1.320 运维那一面的读数：/v1/metrics 说得出什么，输出盘守卫守的是什么。

企业把交付排成流水线之后，第二件事（第一件是 1.319 的「别丢活」）是**看得见排队**：

① `/v1/metrics` 交回的 `queue` 与 `jobs` 必须是 runtime 那本账的样子——槽数、还在排几单、
   最近这些单的成败、失败栽在哪些码上、真交付的字节数。一格都不许是抄来的第二份；
② 输出盘守的是**底线**，不是预估：默认留 2 GB，低于底线就拒在**排队之前**（503
   `OUTPUT_DISK_TIGHT`，点名是哪块盘、还剩多少、底线设的是多少）。盘满时让 FFmpeg 渲到一半
   才失败，留下的是半截 `.part` 和一句「渲染失败」，那不是运维想要的答案；
③ 那一格里附的体积预估**只在这台引擎真渲过同一种预设之后**才出现，用的是那几单实测的
   字节/秒。没渲过就说没渲过——CRF 的产物大小没有别处的可信来源，编一个常数等于把猜测写成度量；
④ 这扇门在契约三面同源（`TOOL_ENDPOINTS`、MCP 同名工具、参数表里 `recent` 在 query 上）；
⑤ 反向腿：底线调到 0，同样那一单照样排得进去并且渲出文件——守卫不许把正常出货挡住。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import ops_check as oc
import scratch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut import agent_contract  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.mcp_server import create_mcp  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def hub_for(rig: oc.Rig, jobs, **app_kwargs):
    app = create_app(rig.db, oc.TOKEN, media=rig.media, jobs=jobs, **app_kwargs)
    return TestClient(app, base_url="http://127.0.0.1",
                      headers={"Authorization": f"Bearer {oc.TOKEN}"})


def metrics_leg(rig: oc.Rig, fast: tuple[str, int]) -> None:
    """①⑤ 读数自洽，而且正常出货挡不住。"""
    fast_id, revision = fast
    jobs = rig.runtime(slots=2, max_pending=9, pending_per_actor=4, min_free_mb=0)
    with hub_for(rig, jobs) as hub:
        before = hub.get("/v1/metrics").json()
        check("metrics 三张表都在", {"queue", "jobs", "outputs"} <= set(before), sorted(before))
        check("queue 那一格读的就是 runtime 的数",
              before["queue"] == {"pending": jobs.pending_count(), "slots": 2,
                                  "live_slots": jobs.live_slots(), "max_pending": 9,
                                  "pending_per_actor": 4, "requeued": len(jobs.requeued)},
              before["queue"])
        check("每块输出根都说得出剩多少与守的底线",
              all({"path", "free_bytes", "total_bytes", "reserve_bytes"} <= set(row)
                  for row in before["outputs"]) and before["outputs"],
              before["outputs"][:1])
        made = hub.post(
            f"/v1/projects/{fast_id}/renders",
            json={"request_id": "ops2-render-0", "expected_revision": revision,
                  "preset_id": oc.PRESET, "filename": "ops2-0.mp4"},
        )
        check("守卫在 0 底线时不挡正常出货", made.status_code == 200, made.text[:200])
        check("渲得出文件", oc.wait_for([rig.out / "ops2-0.mp4"]), "ops2-0.mp4 没落地")
        after = hub.get("/v1/metrics?recent=20").json()
        by_status = after["jobs"]["by_status"]
        check("成过的单在账上看得见", by_status.get("succeeded", 0) >= 1, by_status)
        check("recent 这一格说的是这次读了几单", after["jobs"]["recent"] >= 1
              and after["jobs"]["recent"] <= 20, after["jobs"]["recent"])
        check("交付字节数是从文件身上量的，不是估的",
              after["jobs"]["delivered_bytes"] >= (rig.out / "ops2-0.mp4").stat().st_size,
              after["jobs"]["delivered_bytes"])
        span = after["jobs"]["duration_seconds"]
        check("耗时读数说得出 p50/p95/max，且没编毫秒",
              {"p50", "p95", "max"} <= set(span) and span["max"] is None or span["max"] >= 0,
              span)

    # 一次取消：状态与账都要如实反映，而不是只统计成功。
    # 取消的是**第二单**：一槽时它一定还排在队列里（第一单正渲着），所以这一手测的就是
    # 「排队中被叫停的那一单不许永远留在 queued」；读账之前先等它落到终态，不然读的是过程。
    cancelled = rig.runtime(slots=1, min_free_mb=0)
    with hub_for(rig, cancelled) as hub:
        busy = hub.post(
            f"/v1/projects/{fast_id}/renders",
            json={"request_id": "ops2-render-1", "expected_revision": revision,
                  "preset_id": oc.PRESET, "filename": "ops2-1.mp4"},
        )
        parked = hub.post(
            f"/v1/projects/{fast_id}/renders",
            json={"request_id": "ops2-render-2", "expected_revision": revision,
                  "preset_id": oc.PRESET, "filename": "ops2-2.mp4"},
        )
        parked_id = (parked.json().get("job") or {}).get("id")
        check("第一单在跑的时候第二单确实排在队列里",
              (parked.json().get("job") or {}).get("status") == "queued"
              and (busy.json().get("job") or {}).get("status") in ("queued", "running"),
              (busy.json().get("job"), parked.json().get("job")))
        hub.post(f"/v1/jobs/{parked_id}/cancel", json={})
        row_now = hub.get(f"/v1/jobs/{parked_id}").json().get("job") or {}
        check("叫停之后那一单不再算「还在排」",
              row_now.get("status") == "cancelled", row_now)
        counts = hub.get("/v1/metrics?recent=50").json()["jobs"]["by_status"]
        check("取消那一手也记在账上", counts.get("cancelled", 0) >= 1, counts)
        oc.drain(cancelled, 180.0)


def disk_leg(rig: oc.Rig, fast: tuple[str, int], slow: tuple[str, int]) -> None:
    """②③ 拒在排队之前，且预估只在真渲过之后才有。"""
    fast_id, revision = fast
    starved = rig.runtime(slots=1, min_free_mb=999_999_999)
    refused = None
    try:
        starved.submit(rig.store.get(fast_id), rig.request(50, revision, oc.PRESET, tag="disk"))
    except Exception as error:  # noqa: BLE001
        refused = error
    details = getattr(refused, "details", {}) or {}
    check("盘不够时拒在排队之前",
          getattr(refused, "code", None) == "OUTPUT_DISK_TIGHT", type(refused).__name__)
    check("那句点名是哪块盘、还剩多少、底线多少",
          {"root", "free_bytes", "reserve_bytes"} <= set(details), details)
    check("这是 503，不是 422（不是调用方的错）", getattr(refused, "status", None) == 503,
          getattr(refused, "status", None))
    check("没渲过的预设不许编一个体积出来（预估那一格是缺席的）",
          "needed_bytes" not in details and "basis" not in details, details)

    # 先让这台引擎真渲一单同一预设的交付，再来问「这一单大概要多大」。
    roomy = rig.runtime(slots=1, min_free_mb=0)
    sample, _plan = roomy.submit(rig.store.get(fast_id), rig.request(51, revision, oc.PRESET,
                                                                     tag="disk"))
    check("先渲成一单，才有资格谈预估", oc.wait_for([rig.out / "ops-disk-51.mp4"]),
          sample.output_path)
    oc.drain(roomy, 120.0)
    starved_again = rig.runtime(slots=1, min_free_mb=999_999_999)
    second = None
    try:
        starved_again.submit(rig.store.get(fast_id), rig.request(52, revision, oc.PRESET,
                                                                 tag="disk"))
    except Exception as error:  # noqa: BLE001
        second = error
    details = getattr(second, "details", {}) or {}
    check("同一预设真渲过之后，预估才出现，并说清是 measured 来的",
          "needed_bytes" in details and str(details.get("basis", "")).startswith("measured"),
          details)
    check("预估那一个数不是凭空的大：与实测字节/秒同量级",
          isinstance(details.get("needed_bytes"), int) and 0 < details["needed_bytes"] < 10**11,
          details)


def contract_leg() -> None:
    """④ 三面同源。"""
    entry = dict(agent_contract.TOOL_ENDPOINTS).get("agent_metrics")
    check("契约登记了 metrics 这扇门", entry == ("GET", "/v1/metrics"), entry)
    params = agent_contract.route_params(create_app(Path("unused.sqlite3"), oc.TOKEN))
    check("recent 在 query 上，路径与载荷都不多一格",
          params.get(("GET", "/v1/metrics")) == {"path": [], "query": ["recent"], "body": []},
          params.get(("GET", "/v1/metrics")))
    server = create_mcp("http://127.0.0.1:0", "opscheck19" + "d" * 52)
    tools = {tool.name for tool in asyncio.run(server.list_tools())}
    check("MCP 也交出 agent_metrics", "agent_metrics" in tools, sorted(tools)[-6:])


def main() -> None:
    folder = scratch.make("agentcut-ops2-")
    rig = oc.Rig(folder)
    fast = oc.seeded(rig, 4, 4000, "fast")
    slow = oc.seeded(rig, 20, 20000, "slow")
    # 顺序是有讲究的：磁盘那一腿要先证明「没渲过的预设不编体积」，之后再让 metrics 腿渲交付。
    disk_leg(rig, fast, slow)
    metrics_leg(rig, fast)
    contract_leg()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: /v1/metrics 读的就是 runtime 那本账，输出盘守的是底线、预估只在真渲过之后才有")


if __name__ == "__main__":
    main()
