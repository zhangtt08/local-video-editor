"""One runnable acceptance check: actual HTTP process + official MCP stdio client."""

import asyncio
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from agentcut.contracts import APP_VERSION, TIMEBASE, EditBatch, FrameRate, SequenceSettings
from agentcut.projects import ProjectStore

TOKEN = "acceptance-test-token-" + "x" * 32


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


def edit(request_id, revision, commands, dry_run=False, sequence_id=None):
    return {
        "request_id": request_id,
        "expected_revision": revision,
        "commands": commands,
        "dry_run": dry_run,
        "sequence_id": sequence_id,
    }


def check_http(base_url, db_path, media_ready):
    with httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        assert_error(
            client.get("/v1/projects", headers={"Authorization": "Bearer wrong"}),
            401,
            "UNAUTHORIZED",
        )
        document = client.get("/v1/capabilities").json()
        # The build identity an Agent reads must be the one this file is running, or the version in
        # the title bar and in every delivery note is fiction.
        assert document["app_version"] == APP_VERSION, (document["app_version"], APP_VERSION)
        features = document["features"]
        assert features["render"] is media_ready, "capabilities 必须如实反映渲染是否可用"
        assert features["keyframes"] is True and features["transitions"] is True
        assert features["multi_clip_editing"] is True
        assert client.get("/v1/contracts").json()["EditBatch"]["$defs"]
        create = {"request_id": "create-1", "name": "Acceptance"}
        response = client.post("/v1/projects", json=create)
        assert response.status_code == 200, response.text
        project_id = response.json()["project"]["id"]
        assert client.post("/v1/projects", json=create).json()["replayed"]
        assert_error(
            client.post("/v1/projects", json={**create, "name": "Changed"}),
            409,
            "IDEMPOTENCY_CONFLICT",
        )
        path = f"/v1/projects/{project_id}"
        batch = edit(
            "edit-1",
            0,
            [
                {"op": "track.add", "track": {"id": "v1", "name": "Video", "kind": "video"}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "a1",
                        "kind": "video",
                        "label": "Demo",
                        "reference": "media://unverified-demo",
                        "duration_ticks": 4 * TIMEBASE,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c1",
                        "asset_id": "a1",
                        "track_id": "v1",
                        "position_ticks": 0,
                        "source_in_ticks": TIMEBASE,
                        "duration_ticks": 2 * TIMEBASE,
                    },
                },
            ],
        )
        preview = client.post(path + "/edits", json={**batch, "dry_run": True}).json()
        assert preview["committed"] is False and preview["project"]["revision"] == 1
        assert client.get(path).json()["revision"] == 0
        assert len(client.get(path + "/history").json()["history"]) == 1
        committed = client.post(path + "/edits", json=batch)
        assert committed.status_code == 200, committed.text
        assert committed.json()["project"] == preview["project"]
        assert client.post(path + "/edits", json=batch).json()["replayed"]
        assert_error(
            client.post(path + "/edits", json={**batch, "dry_run": True}),
            409,
            "REQUEST_ALREADY_COMMITTED",
        )
        assert_error(
            client.post(path + "/edits", json={**batch, "request_id": "stale"}),
            409,
            "REVISION_CONFLICT",
        )
        failed = edit(
            "failed",
            1,
            [
                {"op": "track.add", "track": {"id": "v2", "name": "Rollback", "kind": "video"}},
                {"op": "clip.remove", "clip_id": "missing"},
            ],
        )
        assert_error(client.post(path + "/edits", json=failed), 404, "NOT_FOUND")
        assert len(client.get(path).json()["tracks"]) == 1
        assert len(client.get(path + "/history").json()["history"]) == 2
        assert_error(
            client.post(
                path + "/edits",
                json=edit(
                    "range",
                    1,
                    [
                        {
                            "op": "clip.trim",
                            "clip_id": "c1",
                            "source_in_ticks": 3 * TIMEBASE,
                            "duration_ticks": 2 * TIMEBASE,
                        }
                    ],
                ),
            ),
            422,
            "SOURCE_OUT_OF_BOUNDS",
        )
        assert_error(
            client.post(
                path + "/edits",
                json=edit(
                    "alignment",
                    1,
                    [{"op": "clip.move", "clip_id": "c1", "track_id": "v1", "position_ticks": 1}],
                ),
            ),
            422,
            "TIME_NOT_ALIGNED",
        )
        split = edit(
            "split",
            1,
            [{"op": "clip.split", "clip_id": "c1", "at_ticks": TIMEBASE, "right_clip_id": "c2"}],
        )
        response = client.post(path + "/edits", json=split)
        assert response.status_code == 200, response.text
        assert response.json()["project"]["clips"]["c2"]["source_in_ticks"] == 2 * TIMEBASE
        swap = edit(
            "swap",
            2,
            [
                {"op": "clip.move", "clip_id": "c1", "track_id": "v1", "position_ticks": TIMEBASE},
                {"op": "clip.move", "clip_id": "c2", "track_id": "v1", "position_ticks": 0},
            ],
        )
        assert client.post(path + "/edits", json=swap).status_code == 200
        assert_error(
            client.post(
                path + "/edits",
                json=edit(
                    "overlap",
                    3,
                    [
                        {
                            "op": "clip.move",
                            "clip_id": "c2",
                            "track_id": "v1",
                            "position_ticks": TIMEBASE,
                        }
                    ],
                ),
            ),
            422,
            "CLIP_OVERLAP",
        )
        # Competing revisions: only one writer can succeed.
        writes = [
            edit(
                f"race-{i}",
                3,
                [
                    {
                        "op": "clip.trim",
                        "clip_id": "c1",
                        "source_in_ticks": i * TIMEBASE,
                        "duration_ticks": TIMEBASE,
                    }
                ],
            )
            for i in (0, 1)
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda payload: client.post(path + "/edits", json=payload), writes)
            )
        assert sorted(result.status_code for result in results) == [200, 409]
        retry = edit("parallel-retry", 4, [{"op": "clip.remove", "clip_id": "c2"}])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: client.post(path + "/edits", json=retry), range(2)))
        assert all(result.status_code == 200 for result in results)
        assert sorted(result.json()["replayed"] for result in results) == [False, True]
        # New store instance proves receipts/snapshots are not process memory.
        reopened = ProjectStore(db_path)
        assert reopened.get(project_id).revision == 5
        assert reopened.mutate(project_id, EditBatch.model_validate(retry)).replayed
        restore = {"request_id": "restore", "expected_revision": 5, "target_revision": 1}
        response = client.post(path + "/restore", json=restore)
        assert response.status_code == 200, response.text
        assert response.json()["project"]["revision"] == 6
        assert response.json()["project"]["clips"] == preview["project"]["clips"]
        assert client.get(path + "?revision=1").json()["revision"] == 1
        assert len(client.get(path + "/history").json()["history"]) == 7
        assert client.post(path + "/restore", json=restore).json()["replayed"]
        assert_error(
            client.post(
                path + "/edits",
                json=edit(
                    "float",
                    6,
                    [{"op": "clip.move", "clip_id": "c1", "track_id": "v1", "position_ticks": 1.0}],
                ),
            ),
            422,
            "INVALID_REQUEST",
        )
        assert_error(
            client.post(path + "/edits", json=edit("unknown", 6, [{"op": "render"}])),
            422,
            "INVALID_REQUEST",
        )
        assert client.get(path + "/history?limit=1&offset=1").json()["history"][0]["revision"] == 5
        assert client.get("/v1/projects?limit=0").status_code == 422
        assert client.get(path, headers={"Host": "malicious.example"}).status_code == 400
        return project_id


def check_clocks_and_images(base_url):
    for sample_rate in (44_100, 48_000, 96_000):
        settings = SequenceSettings(
            sample_rate=sample_rate, frame_rate=FrameRate(numerator=30_000, denominator=1001)
        )
        assert settings.frame_ticks * 30_000 == TIMEBASE * 1001
        assert TIMEBASE % sample_rate == 0
    try:
        SequenceSettings(frame_rate=FrameRate(numerator=29, denominator=1))
    except ValidationError:
        pass
    else:
        raise AssertionError("inexact frame clock accepted")
    with httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = client.post(
            "/v1/projects",
            json={
                "request_id": "images",
                "name": "Images/audio",
                "settings": {
                    "frame_rate": {"numerator": 30_000, "denominator": 1001},
                    "sample_rate": 96_000,
                },
            },
        )
        project_id = response.json()["project"]["id"]
        path = f"/v1/projects/{project_id}/edits"
        frame = TIMEBASE * 1001 // 30_000
        sample = TIMEBASE // 96_000
        response = client.post(
            path,
            json=edit(
                "image-split",
                0,
                [
                    {"op": "track.add", "track": {"id": "v", "name": "Video", "kind": "video"}},
                    {"op": "track.add", "track": {"id": "a", "name": "Audio", "kind": "audio"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "img",
                            "kind": "image",
                            "label": "Still",
                            "reference": "media://still",
                        },
                    },
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "audio",
                            "kind": "audio",
                            "label": "Audio",
                            "reference": "media://audio",
                            "duration_ticks": TIMEBASE,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "i1",
                            "asset_id": "img",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": frame * 4,
                        },
                    },
                    {
                        "op": "clip.split",
                        "clip_id": "i1",
                        "at_ticks": frame * 2,
                        "right_clip_id": "i2",
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "s1",
                            "asset_id": "audio",
                            "track_id": "a",
                            "position_ticks": sample,
                            "duration_ticks": sample * 10,
                        },
                    },
                ],
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["project"]["clips"]["i2"]["source_in_ticks"] == 0
        assert_error(
            client.post(
                path,
                json=edit(
                    "no-asset",
                    1,
                    [
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "unknown",
                                "asset_id": "missing",
                                "track_id": "v",
                                "position_ticks": frame * 10,
                                "duration_ticks": frame * 4,
                            },
                        },
                        {
                            "op": "clip.split",
                            "clip_id": "unknown",
                            "at_ticks": frame * 12,
                            "right_clip_id": "unknown-right",
                        },
                    ],
                ),
            ),
            422,
            "MISSING_REFERENCE",
        )


async def check_mcp(env, project_id, log, media_root, ffmpeg, ffprobe):
    params = StdioServerParameters(command=sys.executable, args=["-m", "agentcut", "mcp"], env=env)
    async with stdio_client(params, errlog=log) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            expected = {
                "editor_capabilities",
                "editor_contracts",
                "editor_info",
                "lut_parse",
                "project_create",
                "project_list",
                "project_get",
                "project_history",
                "preview_manifest",
                "animation_curve",
                "animation_sample",
                "preview_candidate",
                "clip_sample",
                "captions_export",
                "timeline_edit",
                "project_update",
                "project_restore",
                "ids_request",
                "media_import",
                "media_probe",
                "media_config",
                "render_presets_read",
                "render_plan",
                "render_start",
                "job_status",
                "job_list",
                "job_cancel",
                "project_asset_urls",
                "output_root_add",
                "output_roots_read",
                "clip_silence",
                "preview_frame",
                "media_cache_read",
                "media_cache_prune",
                "media_proxies_prune",
                "clip_loudness",
                "track_loudness",
                "track_silence",
                "captions_auto",
                "clip_track",
                "clip_stabilize",
                "marker_split",
                "clip_four_point",
                "clip_reframe",
                "track_duck",
                "render_batch",
                "master_loudness",
                "clip_auto_grade",
            }
            assert set(tools) == expected, set(tools) ^ expected
            assert "request" in tools["timeline_edit"].inputSchema["properties"]
            # The Agent-facing schema must name the 1.64 knob, not just accept any key: this is the
            # only place a client that cannot read the contract learns what `clip.patch` may write.
            assert "blur" in json.dumps(tools["timeline_edit"].inputSchema)
            assert "sharpen" in json.dumps(tools["timeline_edit"].inputSchema)
            # 1.69: the stabiliser's record is a command like any other, so the Agent's schema has
            # to say it exists — otherwise clearing a stabilisation means guessing the op name.
            assert "clip.stabilize_record" in json.dumps(tools["timeline_edit"].inputSchema)
            assert "stabilization" in json.dumps(tools["timeline_edit"].inputSchema)
            assert "clip_stabilize" in tools, "the Agent lost the stabiliser tool"
            assert "max_crop" in json.dumps(tools["clip_stabilize"].inputSchema)
            assert tools["clip_silence"].annotations.readOnlyHint is True
            # 1.79: 统一响度 and 整轨去空白 had HTTP routes and buttons long before they had a tool,
            # so an Agent could align the master and one clip's pauses but nothing else in that
            # family. They are read-only here for the same reason clip_silence is: the plan is the
            # answer, and `timeline_edit` is the one place that writes.
            for voiced in ("clip_loudness", "track_loudness", "track_silence"):
                assert tools[voiced].annotations.readOnlyHint is True, voiced
                assert "sequence_id" in json.dumps(tools[voiced].inputSchema), voiced
            # 1.80: an Agent could not see the timeline at all -- /frame was the desktop's
            # private view -- and could not read or bound the derived cache either.
            assert tools["preview_frame"].annotations.readOnlyHint is True
            assert "sequence_id" in json.dumps(tools["preview_frame"].inputSchema)
            assert "at_ticks" in json.dumps(tools["preview_frame"].inputSchema)
            assert tools["media_cache_read"].annotations.readOnlyHint is True
            assert tools["media_cache_prune"].annotations.destructiveHint is True
            assert "dry_run" in json.dumps(tools["media_cache_prune"].inputSchema)
            assert "max_bytes" in json.dumps(tools["media_proxies_prune"].inputSchema)
            assert "target_lufs" in json.dumps(tools["clip_loudness"].inputSchema)
            assert "threshold_db" in json.dumps(tools["track_silence"].inputSchema)
            assert tools["lut_parse"].annotations.readOnlyHint is True
            assert "content" in json.dumps(tools["lut_parse"].inputSchema)
            assert tools["clip_track"].annotations.readOnlyHint is False
            assert tools["marker_split"].annotations.readOnlyHint is True
            assert tools["clip_four_point"].annotations.readOnlyHint is True
            assert "source_out_ticks" in json.dumps(tools["clip_four_point"].inputSchema)
            assert tools["clip_reframe"].annotations.readOnlyHint is True
            assert "max_scale" in json.dumps(tools["clip_reframe"].inputSchema)
            assert "tolerance" in json.dumps(tools["clip_reframe"].inputSchema)
            assert tools["track_duck"].annotations.readOnlyHint is False
            # 1.83: 自动调色会落一条普通 `clip.grade`，所以它是写工具而不是只读工具；schema 要说得出
            # 那三个旋钮，Agent 才不会靠猜。色阶节点本身也必须出现在 timeline_edit 的 schema 里。
            assert tools["clip_auto_grade"].annotations.readOnlyHint is False
            for knob in ("percentile", "samples", "mode", "replace", "sequence_id"):
                assert knob in json.dumps(tools["clip_auto_grade"].inputSchema), knob
            assert '"levels"' in json.dumps(tools["timeline_edit"].inputSchema)
            # 1.84: the first cross-channel node is written through the same command, so the Agent's
            # schema has to name it too — otherwise a mixer is only reachable from the interface.
            assert '"matrix"' in json.dumps(tools["timeline_edit"].inputSchema)
            assert "coefficients" in json.dumps(tools["timeline_edit"].inputSchema)
            # 1.74: an Agent has to be able to ask for a clip inside a nested composition. The tool
            # schema is generated from the request model, so the field being there is the promise.
            for steadied in (
                "clip_silence",
                "clip_reframe",
                "track_duck",
                "clip_stabilize",
                "clip_track",
                "captions_auto",
            ):
                assert "sequence_id" in json.dumps(tools[steadied].inputSchema), steadied
            assert tools["render_batch"].annotations.readOnlyHint is False
            assert tools["master_loudness"].annotations.readOnlyHint is False
            assert tools["media_import"].annotations.openWorldHint is False
            assert tools["timeline_edit"].annotations.destructiveHint is True
            assert tools["project_restore"].annotations.destructiveHint is True
            assert tools["project_create"].annotations.destructiveHint is False
            assert tools["project_get"].outputSchema["type"] == "object"
            assert tools["animation_curve"].annotations.readOnlyHint
            assert tools["animation_sample"].annotations.readOnlyHint
            assert tools["preview_candidate"].annotations.readOnlyHint
            await check_curve_mcp(session)
            result = await session.call_tool("project_get", {"project_id": project_id})
            assert not result.isError and result.structuredContent["revision"] == 6
            created = await session.call_tool(
                "project_create", {"request": {"request_id": "mcp-create", "name": "Via MCP"}}
            )
            assert not created.isError and created.structuredContent["committed"]
            result = await session.call_tool(
                "timeline_edit",
                {
                    "project_id": project_id,
                    "request": edit("mcp-stale", 0, [{"op": "clip.remove", "clip_id": "c1"}]),
                },
            )
            assert result.isError
            assert "REVISION_CONFLICT" in result.content[0].text
            result = await session.call_tool(
                "timeline_edit",
                {
                    "project_id": project_id,
                    "request": edit("mcp-edit", 6, [{"op": "clip.remove", "clip_id": "c1"}]),
                },
            )
            assert not result.isError and result.structuredContent["project"]["revision"] == 7
            resource = await session.read_resource(f"project://{project_id}")
            assert json.loads(resource.contents[0].text)["revision"] == 7
            placement_id = created.structuredContent["project"]["id"]
            incoming = {
                "id": "inserted",
                "asset_id": "source",
                "track_id": "v",
                "position_ticks": TIMEBASE,
                "duration_ticks": TIMEBASE,
            }
            result = await call_ok(
                session,
                "timeline_edit",
                {
                    "project_id": placement_id,
                    "request": edit(
                        "mcp-place",
                        0,
                        [
                            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                            {
                                "op": "asset.register",
                                "asset": {
                                    "id": "source",
                                    "kind": "video",
                                    "label": "source",
                                    "reference": "test",
                                    "duration_ticks": 5 * TIMEBASE,
                                },
                            },
                            {
                                "op": "clip.add",
                                "clip": {
                                    **incoming,
                                    "id": "base",
                                    "position_ticks": 0,
                                    "duration_ticks": 3 * TIMEBASE,
                                },
                            },
                            {"op": "clip.insert", "clip": incoming},
                            {
                                "op": "clip.overwrite",
                                "clip": {
                                    **incoming,
                                    "id": "replacement",
                                    "duration_ticks": 2 * TIMEBASE,
                                },
                            },
                        ],
                    ),
                },
            )
            clips = result.structuredContent["project"]["clips"]
            assert "inserted" not in clips and clips["base"]["duration_ticks"] == TIMEBASE
            right = next(c for c in clips.values() if c["position_ticks"] == 3 * TIMEBASE)
            assert right["source_in_ticks"] == 2 * TIMEBASE
            transition = await call_ok(
                session,
                "timeline_edit",
                {
                    "project_id": placement_id,
                    "request": edit(
                        "mcp-transition",
                        1,
                        [
                            {
                                "op": "transition.set",
                                "clip_id": "replacement",
                                "from_clip_id": "base",
                                "duration_ticks": TIMEBASE // 2,
                                "kind": "dissolve",
                            }
                        ],
                    ),
                },
            )
            assert (
                transition.structuredContent["project"]["clips"]["replacement"]["position_ticks"]
                == TIMEBASE // 2
            )
            removed = await call_ok(
                session,
                "timeline_edit",
                {
                    "project_id": placement_id,
                    "request": edit(
                        "mcp-transition-remove",
                        2,
                        [{"op": "transition.remove", "clip_id": "replacement"}],
                    ),
                },
            )
            assert (
                removed.structuredContent["project"]["clips"]["replacement"]["position_ticks"]
                == TIMEBASE
            )
            moved = await call_ok(
                session,
                "timeline_edit",
                {
                    "project_id": placement_id,
                    "request": edit(
                        "mcp-group-move",
                        3,
                        [
                            {
                                "op": "clips.move",
                                "clip_ids": ["base", "replacement", right["id"]],
                                "delta_ticks": TIMEBASE,
                            }
                        ],
                    ),
                },
            )
            assert (
                moved.structuredContent["project"]["clips"]["replacement"]["position_ticks"]
                == 2 * TIMEBASE
            )
            group_removed = await call_ok(
                session,
                "timeline_edit",
                {
                    "project_id": placement_id,
                    "request": edit(
                        "mcp-group-remove",
                        4,
                        [
                            {
                                "op": "clips.remove",
                                "clip_ids": ["base", "replacement"],
                                "ripple": True,
                            }
                        ],
                    ),
                },
            )
            assert (
                group_removed.structuredContent["project"]["clips"][right["id"]]["position_ticks"]
                == TIMEBASE
            )
            await check_linked_mcp(session)
            if ffmpeg and ffprobe:
                await cut_through_mcp(session, media_root, ffmpeg, ffprobe)
                await analysis_through_mcp(session, media_root, ffmpeg)
                await frame_through_mcp(session, media_root, ffmpeg)


async def call_ok(session, tool, arguments):
    result = await session.call_tool(tool, arguments)
    assert not result.isError, f"{tool}: {result.content[0].text if result.content else ''}"
    return result


async def check_linked_mcp(session):
    created = await call_ok(
        session,
        "project_create",
        {"request": {"request_id": "mcp-linked-create", "name": "Linked audio/video"}},
    )
    pid = created.structuredContent["project"]["id"]
    commands = [
        {"op": "track.add", "track": {"id": k, "kind": kind, "name": k}}
        for k, kind in (("v", "video"), ("a", "audio"))
    ]
    commands += [
        {
            "op": "asset.register",
            "asset": {
                "id": k,
                "kind": kind,
                "label": k,
                "reference": "test",
                "duration_ticks": 4 * TIMEBASE,
            },
        }
        for k, kind in (("video", "video"), ("audio", "audio"))
    ]
    commands += [
        {
            "op": "clips.add",
            "clips": [
                {
                    "id": k,
                    "asset_id": asset,
                    "track_id": track,
                    "position_ticks": 0,
                    "duration_ticks": 2 * TIMEBASE,
                }
                for k, asset, track in (("picture", "video", "v"), ("voice", "audio", "a"))
            ],
        },
        {"op": "clips.group", "clip_ids": ["picture", "voice"], "group_id": "saved"},
        {"op": "clips.link", "clip_ids": ["picture", "voice"], "link_id": "av"},
        {
            "op": "clip.trim_linked",
            "clip_id": "picture",
            "source_in_ticks": TIMEBASE,
            "position_ticks": TIMEBASE,
            "duration_ticks": TIMEBASE,
        },
    ]
    result = await call_ok(
        session, "timeline_edit", {"project_id": pid, "request": edit("mcp-linked", 0, commands)}
    )
    assert result.structuredContent["project"]["clips"]["voice"]["source_in_ticks"] == TIMEBASE
    plan = await call_ok(session, "preview_manifest", {"project_id": pid})
    payload = plan.structuredContent or json.loads(plan.content[0].text)
    assert payload["links"]["av"]["synchronized"]
    blended = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "mcp-blend", 1, [{"op": "track.update", "track_id": "v", "blend_mode": "screen"}]
            ),
        },
    )
    assert blended.structuredContent["project"]["tracks"][0]["blend_mode"] == "screen"
    preview = await call_ok(session, "preview_manifest", {"project_id": pid})
    payload = preview.structuredContent or json.loads(preview.content[0].text)
    assert payload["track_blend_modes"]["v"] == "screen"


async def check_curve_mcp(session):
    created = await call_ok(
        session,
        "project_create",
        {"request": {"request_id": "curve-new", "name": "MCP value graph"}},
    )
    pid = created.structuredContent["project"]["id"]
    clip = {
        "id": "curve",
        "asset_id": "image",
        "track_id": "v",
        "position_ticks": 0,
        "duration_ticks": 2 * TIMEBASE,
        "keyframes": [
            {"property": "opacity", "at_ticks": 0, "value": 0, "interpolation": "ease"},
            {"property": "opacity", "at_ticks": 2 * TIMEBASE, "value": 1},
        ],
    }
    await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "curve-seed",
                0,
                [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "picture"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "image",
                            "kind": "image",
                            "label": "metadata",
                            "reference": "untrusted metadata",
                        },
                    },
                    {"op": "clip.add", "clip": clip},
                ],
            ),
        },
    )
    graph = await call_ok(session, "animation_curve", {"clip": clip, "property": "opacity"})
    assert "C " in graph.structuredContent["path"]
    sampled = await call_ok(session, "animation_sample", {"clip": clip, "at_ticks": TIMEBASE})
    assert sampled.structuredContent["values"]["opacity"] == 0.5
    patched = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "patch-preview",
                1,
                [
                    {"op": "clip.patch", "clip_id": "curve", "effects": {"x": 0.2}},
                    {"op": "clip.patch", "clip_id": "curve", "effects": {"y": 0.3}},
                ],
                True,
            ),
        },
    )
    candidate_clip = patched.structuredContent["project"]["clips"]["curve"]
    sampled_candidate = await call_ok(
        session, "animation_sample", {"clip": candidate_clip, "at_ticks": TIMEBASE}
    )
    assert sampled_candidate.structuredContent["values"]["x"] == 0.2
    assert sampled_candidate.structuredContent["values"]["y"] == 0.3
    masked = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "mask-proposal",
                1,
                [{"op": "clip.mask", "clip_id": "curve", "mask": {"feather": 0.25}}],
                True,
            ),
        },
    )
    preview = await call_ok(
        session, "preview_candidate", {"project": masked.structuredContent["project"]}
    )
    assert "data:image/svg+xml" in preview.structuredContent["clips"]["curve"]["mask_image"]
    saved = await call_ok(session, "project_get", {"project_id": pid})
    assert (
        saved.structuredContent["revision"] == 1
        and saved.structuredContent["clips"]["curve"]["mask"] is None
    )
    command = {
        "op": "keyframe.move",
        "clip_id": "curve",
        "from_ticks": 2 * TIMEBASE,
        "keyframe": {"property": "opacity", "at_ticks": TIMEBASE, "value": 0.8},
    }
    request = edit("curve-move", 1, [command])
    result = await call_ok(session, "timeline_edit", {"project_id": pid, "request": request})
    assert (
        result.structuredContent["project"]["clips"]["curve"]["keyframes"][-1]["at_ticks"]
        == TIMEBASE
    )
    result = await call_ok(session, "timeline_edit", {"project_id": pid, "request": request})
    assert result.structuredContent["replayed"]

    points = result.structuredContent["project"]["clips"]["curve"]["keyframes"]
    group = {
        "op": "keyframes.move",
        "clip_id": "curve",
        "moves": [
            {"from_ticks": k["at_ticks"], "keyframe": {**k, "at_ticks": TIMEBASE - k["at_ticks"]}}
            for k in points
        ],
    }
    request = edit("curve-swap", 2, [group], True)
    candidate = await call_ok(session, "timeline_edit", {"project_id": pid, "request": request})
    assert candidate.structuredContent["project"]["clips"]["curve"]["keyframes"][0]["value"] == 0.8
    request["dry_run"] = False
    moved = await call_ok(session, "timeline_edit", {"project_id": pid, "request": request})
    assert moved.structuredContent["project"] == candidate.structuredContent["project"]
    removed = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "curve-remove-all",
                3,
                [
                    {
                        "op": "keyframes.remove",
                        "clip_id": "curve",
                        "keyframes": [
                            {"property": k["property"], "at_ticks": k["at_ticks"]} for k in points
                        ],
                    }
                ],
            ),
        },
    )
    assert not removed.structuredContent["project"]["clips"]["curve"]["keyframes"]


async def cut_through_mcp(session, media_root, ffmpeg, ffprobe):
    """Full agent path over MCP stdio: 真实素材 → 导入 → 剪辑 → 渲染 → 校验成品。"""
    source = media_root / "mcp-source.mp4"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=3:sample_rate=48000",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        creationflags=creationflags,
    )
    denied = await session.call_tool(
        "media_import", {"request": {"path": str(Path("C:/Windows/win.ini"))}}
    )
    assert denied.isError and "MEDIA_TYPE_UNSUPPORTED" in denied.content[0].text, denied.content[
        0
    ].text
    outside = source.parent.parent / "outside.mp4"
    shutil.copyfile(source, outside)
    blocked = await session.call_tool("media_import", {"request": {"path": str(outside)}})
    assert blocked.isError and "MEDIA_NOT_ALLOWED" in blocked.content[0].text, blocked.content[
        0
    ].text
    relative = await session.call_tool("media_import", {"request": {"path": "mcp-source.mp4"}})
    assert relative.isError and "MEDIA_PATH_INVALID" in relative.content[0].text, relative.content[
        0
    ].text

    config = await call_ok(session, "media_config", {})
    roots = config.structuredContent["media_roots"]
    assert roots and Path(roots[0]).name == media_root.name, config.structuredContent
    probe = await call_ok(session, "media_import", {"request": {"path": str(source)}})
    record = probe.structuredContent
    assert record["verified"]["has_audio"] is True
    assert len(record["urls"]["thumbnails"]) == 8
    assert record["urls"]["stream"].startswith("http://127.0.0.1")

    created = await call_ok(
        session, "project_create", {"request": {"request_id": "mcp-media", "name": "MCP 剪辑"}}
    )
    pid = created.structuredContent["project"]["id"]
    revision = created.structuredContent["project"]["revision"]
    verified = record["verified"]
    verified["probe_id"] = record["id"]
    plan_edit = edit(
        "mcp-media-cut",
        revision,
        [
            {"op": "track.add", "track": {"id": "mvt", "kind": "video", "name": "画面"}},
            {
                "op": "asset.import",
                "asset_id": "masset",
                "label": "mcp-source",
                "probe_id": record["id"],
                "verified": verified,
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "mclip",
                    "asset_id": "masset",
                    "track_id": "mvt",
                    "position_ticks": 0,
                    "source_in_ticks": TIMEBASE,
                    "duration_ticks": 2 * TIMEBASE,
                },
            },
        ],
    )
    preview = await call_ok(
        session, "timeline_edit", {"project_id": pid, "request": {**plan_edit, "dry_run": True}}
    )
    assert preview.structuredContent["committed"] is False
    committed = await call_ok(session, "timeline_edit", {"project_id": pid, "request": plan_edit})
    revision = committed.structuredContent["project"]["revision"]
    assert committed.structuredContent["project"]["assets"]["masset"]["verified"]["kind"] == "video"

    graph = await call_ok(
        session, "render_plan", {"project_id": pid, "preset_id": "proxy-540p-fast"}
    )
    assert graph.structuredContent["plan"]["mode"] == "cut", graph.structuredContent

    started = await call_ok(
        session,
        "render_start",
        {
            "project_id": pid,
            "request": {
                "request_id": "mcp-render",
                "expected_revision": revision,
                "preset_id": "proxy-540p-fast",
                "filename": "mcp-成品.mp4",
            },
        },
    )
    job_id = started.structuredContent["job"]["id"]
    deadline = time.time() + 150
    status = {}
    while time.time() < deadline:
        polled = await call_ok(session, "job_status", {"job_id": job_id})
        status = polled.structuredContent["job"]
        if status["status"] in ("succeeded", "failed", "cancelled"):
            break
        await asyncio.sleep(0.4)
    assert status["status"] == "succeeded", status
    output = Path(status["output_path"])
    assert output.is_file() and output.stat().st_size > 10_000, str(output)
    meta = json.loads(
        subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
    )
    seconds = float(meta["format"]["duration"])
    assert 1.85 <= seconds <= 2.2, f"MCP 渲染成品时长 {seconds}s，应为 2s（声画同步）"
    jobs = await call_ok(session, "job_list", {"project_id": pid})
    assert jobs.structuredContent["jobs"][0]["id"] == job_id
    return output


async def analysis_through_mcp(session, media_root, ffmpeg):
    """1.79: the 统一响度 / 整轨去空白 family over MCP stdio, on real audio, all the way in.

    These three routes had HTTP endpoints and desktop buttons but no MCP tool, so an Agent could
    align the master and cut the pauses of one clip, and nothing else in that family. Everything
    below is what an Agent can now do: measure, read the plan, land the returned commands with
    `timeline_edit`, and reach a clip that lives inside a nested composition.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def tone(name: str, af: str) -> Path:
        target = media_root / name
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=4:sample_rate=48000",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x202020:s=320x180:r=30:d=4",
                "-af",
                af,
                "-c:a",
                "aac",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                str(target),
            ],
            check=True,
            creationflags=flags,
        )
        return target

    gated = await call_ok(
        session,
        "media_import",
        {
            "request": {
                "path": str(tone("mcp-gated.mp4", "volume=enable='between(t,1,2)':volume=0"))
            }
        },
    )
    quiet = await call_ok(
        session, "media_import", {"request": {"path": str(tone("mcp-quiet.mp4", "volume=0.05"))}}
    )
    created = await call_ok(
        session,
        "project_create",
        {"request": {"request_id": "mcp-analysis", "name": "MCP 音量"}},
    )
    pid = created.structuredContent["project"]["id"]
    revision = created.structuredContent["project"]["revision"]
    seeds = []
    for asset_id, track_id, kind, record in (
        ("mgate", "mvt", "video", gated.structuredContent),
        ("mquiet", "mat", "audio", quiet.structuredContent),
    ):
        verified = record["verified"]
        verified["probe_id"] = record["id"]
        seeds += [
            {"op": "track.add", "track": {"id": track_id, "kind": kind, "name": asset_id}},
            {
                "op": "asset.import",
                "asset_id": asset_id,
                "label": asset_id,
                "probe_id": record["id"],
                "verified": verified,
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": f"c-{asset_id}",
                    "asset_id": asset_id,
                    "track_id": track_id,
                    "position_ticks": 0,
                    "duration_ticks": 4 * TIMEBASE,
                },
            },
        ]
    seeded = await call_ok(
        session,
        "timeline_edit",
        {"project_id": pid, "request": edit("mcp-analysis-seed", revision, seeds)},
    )
    revision = seeded.structuredContent["project"]["revision"]

    loud = await call_ok(
        session,
        "clip_loudness",
        {
            "project_id": pid,
            "clip_id": "c-mquiet",
            "request": {"request_id": "mcp-q", "expected_revision": revision},
        },
    )
    read = loud.structuredContent["loudness"]
    assert loud.structuredContent["committed"] is False
    # FFmpeg's own ebur128 puts a 5 % tone at -47.8 LUFS, so the one honest answer is the clamp at
    # MAX_GAIN: the tool reports which limit bound it instead of pretending the target was reached.
    assert abs(read["integrated_lufs"] - -47.8) <= 0.3, read
    assert read["gain"] == 4.0 and read["limited_by"] == "gain_range", read
    assert read["reaches_target"] is False, read
    assert read["predicted_lufs"] < read["target_lufs"], read

    # The gated clip is a full-level 440 Hz sine (-22.2 LUFS): that one lifts onto the target.
    lifted = await call_ok(
        session,
        "clip_loudness",
        {
            "project_id": pid,
            "clip_id": "c-mgate",
            "request": {"request_id": "mcp-g", "expected_revision": revision},
        },
    )
    plan = lifted.structuredContent["loudness"]
    assert abs(plan["integrated_lufs"] - -22.2) <= 0.3, plan
    assert plan["limited_by"] == "" and plan["reaches_target"] is True, plan
    assert abs(plan["predicted_lufs"] - plan["target_lufs"]) <= 0.2, plan
    assert 1.0 < plan["gain"] < 4.0, plan
    assert plan["lra_lu"] is None or plan["lra_lu"] >= 0.0, plan

    # The tool is read-only by construction: asking for `apply` cannot make it write.
    forced = await call_ok(
        session,
        "clip_loudness",
        {
            "project_id": pid,
            "clip_id": "c-mquiet",
            "request": {
                "request_id": "mcp-q-apply",
                "expected_revision": revision,
                "apply": True,
                "dry_run": True,
            },
        },
    )
    assert forced.structuredContent["committed"] is False
    assert forced.structuredContent["project"]["revision"] == revision

    track = await call_ok(
        session,
        "track_loudness",
        {
            "project_id": pid,
            "track_id": "mat",
            "request": {"request_id": "mcp-track-q", "expected_revision": revision},
        },
    )
    body = track.structuredContent["loudness"]
    assert body["measured"] == 1 and body["changed"] == 1, body
    assert [c["clip_id"] for c in body["commands"]] == ["c-mquiet"], body
    landed = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit("mcp-track-q-land", revision, body["commands"]),
        },
    )
    revision = landed.structuredContent["project"]["revision"]
    gain = landed.structuredContent["project"]["clips"]["c-mquiet"]["effects"]["gain"]
    assert gain == body["commands"][0]["effects"]["gain"], (gain, body)

    again = await call_ok(
        session,
        "track_loudness",
        {
            "project_id": pid,
            "track_id": "mat",
            "request": {"request_id": "mcp-track-again", "expected_revision": revision},
        },
    )
    assert again.structuredContent["loudness"]["changed"] == 0, again.structuredContent

    quieted = await call_ok(
        session,
        "track_silence",
        {
            "project_id": pid,
            "track_id": "mvt",
            "request": {
                "request_id": "mcp-silence",
                "expected_revision": revision,
                "threshold_db": -35.0,
                "min_silence_ms": 300,
            },
        },
    )
    scan = quieted.structuredContent["silence"]
    assert scan["clips"][0]["clip_id"] == "c-mgate", scan
    # One second gated to silence in the middle: edges are the clip ends, the gap is the cut.
    removed = scan["removed_ticks"]
    assert 0.7 * TIMEBASE <= removed <= 1.3 * TIMEBASE, removed / TIMEBASE
    cut = await call_ok(
        session,
        "timeline_edit",
        {"project_id": pid, "request": edit("mcp-silence-land", revision, scan["commands"])},
    )
    revision = cut.structuredContent["project"]["revision"]
    pieces = [
        c for c in cut.structuredContent["project"]["clips"].values() if c["track_id"] == "mvt"
    ]
    assert len(pieces) >= 2, sorted(c["id"] for c in pieces)
    span = sum(c["duration_ticks"] for c in pieces)
    assert 2.7 * TIMEBASE <= span <= 3.3 * TIMEBASE, span / TIMEBASE

    # Inside a comp: the same track id on the root is honestly empty, and the tool reads the comp.
    nested = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "mcp-nest",
                revision,
                [
                    {
                        "op": "sequence.nest",
                        "clip_ids": sorted(c["id"] for c in pieces),
                        "name": "口播",
                        "sequence_id": "mcomp",
                        "asset_id": "mseq",
                        "clip_id": "mcn",
                    }
                ],
            ),
        },
    )
    revision = nested.structuredContent["project"]["revision"]
    empty = await session.call_tool(
        "track_loudness",
        {
            "project_id": pid,
            "track_id": "mvt",
            "request": {"request_id": "mcp-root-blind", "expected_revision": revision},
        },
    )
    assert empty.isError and "NOT_FOUND" in empty.content[0].text, empty.content[0].text
    # 1.79: an existing track with nothing on it refuses the same way in all four track routes.
    # Before this it answered "measured 0", and with `apply` it claimed the clips were aligned.
    assert "this track holds no clips" in empty.content[0].text, empty.content[0].text
    assert "mvt" in empty.content[0].text, empty.content[0].text
    # 1.83: 自动调色也进得了合成。这一段用的平板素材本来就是一块均匀的暗板（0x202020），所以正确答案
    # 是**点名拒绝并给出量到的两个数**，而不是假装拉开层次，更不是写一条什么都改不了的节点进工程。
    # 这里同时钉住三件事：工具存在、`sequence_id` 读的是合成里的那一段、拒绝不涨 revision。
    graded = await session.call_tool(
        "clip_auto_grade",
        {
            "project_id": pid,
            "clip_id": pieces[0]["id"],
            "request": {
                "request_id": "mcp-auto-grade",
                "expected_revision": revision,
                "sequence_id": "mcomp",
                "mode": "luma",
                "percentile": 0.0,
                "samples": 4,
            },
        },
    )
    refused = graded.content[0].text
    assert graded.isError, refused
    assert "AUTO_GRADE_NO_RANGE" in refused, refused
    assert '"low"' in refused and '"high"' in refused, refused
    unchanged = await call_ok(session, "project_get", {"project_id": pid})
    assert unchanged.structuredContent["revision"] == revision, "a refusal burned a revision"
    inside = await call_ok(
        session,
        "track_loudness",
        {
            "project_id": pid,
            "track_id": "mvt",
            "request": {
                "request_id": "mcp-comp-loud",
                "expected_revision": revision,
                "sequence_id": "mcomp",
                "target_lufs": -10.0,
            },
        },
    )
    plan = inside.structuredContent["loudness"]
    assert plan["measured"] == len(pieces), plan
    assert plan["changed"] >= 1 and plan["target_lufs"] == -10.0, plan
    wrote = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit("mcp-comp-loud-land", revision, plan["commands"], sequence_id="mcomp"),
        },
    )
    document = wrote.structuredContent["project"]
    comp_clips = document["sequences"]["mcomp"]["clips"]
    moved = {c["clip_id"]: c["effects"]["gain"] for c in plan["commands"]}
    for clip_id, wanted in moved.items():
        assert comp_clips[clip_id]["effects"]["gain"] == wanted, (clip_id, wanted)
    assert document["clips"]["mcn"]["effects"]["gain"] == 1.0, document["clips"]["mcn"]


async def frame_through_mcp(session, media_root, ffmpeg):
    """1.80: 让 Agent 看得见成片画面，也管得动派生缓存。

    The bytes come from the exporter's own renderer, so a change that leaves this picture alone
    leaves the delivered file alone too. The sha256 is what makes the claim checkable for a client
    that cannot see images: "did my edit do anything?" becomes a comparison, and "did pruning the
    cache change the cut?" becomes the same comparison after the delete.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    source = media_root / "mcp-frame.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=30:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(source),
        ],
        check=True,
        creationflags=flags,
    )
    probe = await call_ok(session, "media_import", {"request": {"path": str(source)}})
    record = probe.structuredContent
    created = await call_ok(
        session,
        "project_create",
        {
            "request": {
                "request_id": "mcp-frame-new",
                "name": "MCP 画面",
                "settings": {
                    "width": 320,
                    "height": 180,
                    "frame_rate": {"numerator": 30, "denominator": 1},
                },
            }
        },
    )
    pid = created.structuredContent["project"]["id"]
    revision = created.structuredContent["project"]["revision"]
    verified = record["verified"]
    verified["probe_id"] = record["id"]
    seeded = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "mcp-frame-seed",
                revision,
                [
                    {"op": "track.add", "track": {"id": "fv", "kind": "video", "name": "画面"}},
                    {
                        "op": "asset.import",
                        "asset_id": "fa",
                        "label": "fa",
                        "probe_id": record["id"],
                        "verified": verified,
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "fc",
                            "asset_id": "fa",
                            "track_id": "fv",
                            "position_ticks": 0,
                            "duration_ticks": 2 * TIMEBASE,
                        },
                    },
                ],
            ),
        },
    )
    revision = seeded.structuredContent["project"]["revision"]

    first = await call_ok(session, "preview_frame", {"project_id": pid, "at_ticks": TIMEBASE // 2})
    frame = first.structuredContent
    raw = base64.b64decode(frame["png_base64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", frame
    assert frame["sha256"] == hashlib.sha256(raw).hexdigest(), frame["sha256"]
    assert frame["bytes"] == len(raw), frame
    assert frame["at_ticks"] == TIMEBASE // 2, frame  # 0.5 秒在 30fps 上就是一帧边界
    # 传输上限：长边 256，宽高比保持（320x180 的工程量到 256x144）
    assert (frame["width"], frame["height"]) == (256, 144), frame
    assert frame["width"] * 180 == frame["height"] * 320, frame
    assert frame["revision"] == revision, frame

    # 夹到整帧网格：多给一 tick，报回来的是真正取样那一帧，像素也必须是同一帧
    clamp = await call_ok(
        session, "preview_frame", {"project_id": pid, "at_ticks": TIMEBASE // 2 + 1}
    )
    assert clamp.structuredContent["at_ticks"] == TIMEBASE // 2, clamp.structuredContent
    assert clamp.structuredContent["sha256"] == frame["sha256"], "two samples of one frame differ"

    base0 = await call_ok(session, "preview_frame", {"project_id": pid, "at_ticks": 0})
    moved = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "mcp-frame-move",
                revision,
                [{"op": "clip.patch", "clip_id": "fc", "effects": {"x": 0.4}}],
            ),
        },
    )
    revision = moved.structuredContent["project"]["revision"]
    second = await call_ok(session, "preview_frame", {"project_id": pid, "at_ticks": 0})
    assert second.structuredContent["revision"] == revision, second.structuredContent
    assert second.structuredContent["sha256"] != base0.structuredContent["sha256"], (
        "a 40 % sideways shift changed nothing on the composited frame"
    )

    nested = await call_ok(
        session,
        "timeline_edit",
        {
            "project_id": pid,
            "request": edit(
                "mcp-frame-nest",
                revision,
                [
                    {
                        "op": "sequence.nest",
                        "clip_ids": ["fc"],
                        "name": "特写",
                        "sequence_id": "fs",
                        "asset_id": "fseq",
                        "clip_id": "fcn",
                    }
                ],
            ),
        },
    )
    revision = nested.structuredContent["project"]["revision"]
    inside = await call_ok(
        session, "preview_frame", {"project_id": pid, "at_ticks": 0, "sequence_id": "fs"}
    )
    outside = await call_ok(session, "preview_frame", {"project_id": pid, "at_ticks": 0})
    assert inside.structuredContent["revision"] == revision, inside.structuredContent
    assert inside.structuredContent["width"] == 256, inside.structuredContent
    # 外层看的是容器，合成里看的是那条片段：同一个 tick，两种视角，画面应当一致
    assert inside.structuredContent["sha256"] == outside.structuredContent["sha256"], (
        inside.structuredContent["sha256"],
        outside.structuredContent["sha256"],
    )

    cache = (await call_ok(session, "media_cache_read", {})).structuredContent
    assert cache["limit_bytes"] > 0 and isinstance(cache["entries"], list), cache
    used = cache["used_bytes"]
    plan = (
        await call_ok(
            session,
            "media_cache_prune",
            {"request": {"max_bytes": 0, "keep": [], "dry_run": True}},
        )
    ).structuredContent
    assert plan["dry_run"] is True, plan
    assert plan["used_bytes_after"] == plan["used_bytes_before"] - plan["freed_bytes"], plan
    assert plan["used_bytes_before"] == used, (plan, used)
    after_dry = (await call_ok(session, "media_cache_read", {})).structuredContent
    assert after_dry["used_bytes"] >= used, "a dry run deleted cache entries"
    if plan["removed"]:
        done = (
            await call_ok(session, "media_cache_prune", {"request": {"max_bytes": 0}})
        ).structuredContent
        assert done["dry_run"] is False and done["freed_bytes"] == plan["freed_bytes"], done
        after = (await call_ok(session, "media_cache_read", {})).structuredContent
        assert after["used_bytes"] <= used - plan["freed_bytes"], (after["used_bytes"], used)
    rebuilt = await call_ok(session, "preview_frame", {"project_id": pid, "at_ticks": 0})
    assert rebuilt.structuredContent["sha256"] == outside.structuredContent["sha256"], (
        "pruning the derived cache changed what the timeline looks like"
    )
    await call_ok(session, "media_proxies_prune", {"request": {"max_bytes": 0}})


@contextmanager
def running_api(env, port, log, media_root=None, ffmpeg="", ffprobe=""):
    argv = [sys.executable, "-m", "agentcut", "api", "--port", str(port)]
    if media_root:
        argv += [
            "--data-dir",
            str(media_root.parent),
            "--media-root",
            str(media_root),
            "--ffmpeg",
            ffmpeg or "ffmpeg",
            "--ffprobe",
            ffprobe or "ffprobe",
        ]
    server = subprocess.Popen(
        argv,
        env=env,
        stdout=log,
        stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        for _ in range(100):
            try:
                if httpx.get(env["AGENTCUT_API_URL"] + "/health", timeout=0.3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if server.poll() is not None:
                raise AssertionError("API process exited before becoming healthy")
            time.sleep(0.1)
        else:
            raise AssertionError("API did not become healthy")
        yield
    finally:
        server.terminate()
        server.wait(timeout=10)


def media_tools() -> tuple[str, str]:
    """Locate ffmpeg/ffprobe the same way the packaged app does; empty means skip media."""
    root = Path(__file__).resolve().parent.parent / "desktop" / "node_modules"
    candidates = {
        "ffmpeg": [root / "ffmpeg-static" / "ffmpeg.exe", shutil.which("ffmpeg") or ""],
        "ffprobe": [
            root / "ffprobe-static" / "bin" / "win32" / "x64" / "ffprobe.exe",
            shutil.which("ffprobe") or "",
        ],
    }
    found = []
    for name in ("ffmpeg", "ffprobe"):
        hit = next(
            (str(item) for item in candidates[name] if item and Path(str(item)).is_file()), ""
        )
        found.append(hit)
    return found[0], found[1]


def main():
    ffmpeg, ffprobe = media_tools()
    with tempfile.TemporaryDirectory(prefix="agentcut-check-") as scratch:
        db_path = Path(scratch) / "projects.sqlite3"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        media_root = Path(scratch) / "media"
        media_root.mkdir()
        env = {
            **os.environ,
            "AGENTCUT_TOKEN": TOKEN,
            "AGENTCUT_DB": str(db_path),
            "AGENTCUT_API_URL": base_url,
            "AGENTCUT_FFMPEG": ffmpeg,
            "AGENTCUT_FFPROBE": ffprobe,
            "AGENTCUT_MEDIA_ROOT": str(media_root),
        }
        with open(Path(scratch) / "server.log", "w", encoding="utf-8") as log:
            with running_api(env, port, log, media_root, ffmpeg, ffprobe):
                project_id = check_http(base_url, db_path, bool(ffmpeg))
                check_clocks_and_images(base_url)
                asyncio.run(check_mcp(env, project_id, log, media_root, ffmpeg, ffprobe))
                subprocess.run(
                    [sys.executable, "examples/agent_workflow.py"],
                    env=env,
                    check=True,
                    timeout=15,
                    stdout=log,
                    stderr=log,
                )
            # Restart the actual API process, then retry a pre-restart MCP write over HTTP.
            with running_api(env, port, log, media_root, ffmpeg, ffprobe):
                response = httpx.post(
                    f"{base_url}/v1/projects/{project_id}/edits",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json=edit("mcp-edit", 6, [{"op": "clip.remove", "clip_id": "c1"}]),
                )
                assert response.status_code == 200, response.text
                assert response.json()["replayed"]
                assert response.json()["project"]["revision"] == 7
    print(
        "PASS: clocks, images/audio, HTTP, atomic edits, retries, concurrency, history, "
        "MCP stdio, example, API restart"
    )


if __name__ == "__main__":
    main()
