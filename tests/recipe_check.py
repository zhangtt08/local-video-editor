"""Delivery recipes: the batch a project ships has to be storable as project state, replayable,
undoable, and — the part that matters — the stored items must be what the batch actually renders."""

import json
import subprocess
import time
from pathlib import Path

import scratch
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import (
    SCHEMA_VERSION,
    DeliveryRecipe,
    EditBatch,
    Project,
    RenderBatchItem,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.projects import ProjectStore

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
FRAME = 2_352_000
SEGMENTS = (("red", 440), ("green", 880), ("blue", 1320))


def run(args, timeout=420):
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def source(folder: Path) -> Path:
    """Six seconds: red/green/blue, two seconds and one distinct tone each."""
    target = folder / "recipe.mp4"
    argv = [str(FFMPEG), "-v", "error", "-y", "-nostdin"]
    for colour, tone in SEGMENTS:
        argv += ["-f", "lavfi", "-i", f"color=c={colour}:s=320x180:r=30:d=2"]
        argv += ["-f", "lavfi", "-i", f"sine=frequency={tone}:duration=2"]
    graph = "".join(f"[{2 * i}:v][{2 * i + 1}:a]" for i in range(3)) + "concat=n=3:v=1:a=1[v][a]"
    argv += [
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        str(target),
    ]
    run(argv)
    return target


def item(preset_id, filename, **extra):
    return {"preset_id": preset_id, "filename": filename, **extra}


def recipe(recipe_id="r-web", name="网络交付", items=None, **extra):
    return {
        "id": recipe_id,
        "name": name,
        "items": items
        if items is not None
        else [
            item("h264-1080p", "horizontal.mp4"),
            item("h264-1080x1920-vertical", "vertical.mp4", fit="cover"),
        ],
        **extra,
    }


def contract_suite() -> None:
    payload = {
        "id": "p",
        "name": "n",
        "settings": {
            "width": 320,
            "height": 180,
            "frame_rate": {"numerator": 30, "denominator": 1},
        },
    }
    plain = Project.model_validate(payload)
    assert plain.recipes == [], "a project without recipes reads as none, not as a crash"
    stored = Project.model_validate({**payload, "recipes": [recipe()]})
    assert stored.recipes[0].items[1].fit == "cover", stored

    five = [item("h264-1080p", f"{name}.mp4") for name in "abcde"]
    for bad, why in (
        ([], "no deliverables at all"),
        (five, "five items is more than one batch ships"),
        (
            [item("h264-1080p", "same.mp4"), item("h264-720p-web", "same.mp4")],
            "two deliverables writing one file",
        ),
        ([item("h264-1080p", "sub/dir.mp4")], "a filename that carries a path"),
        ([item("h264-1080p", "nope.avi")], "a filename that is not an mp4"),
    ):
        try:
            DeliveryRecipe.model_validate({"id": "r", "name": "n", "items": bad})
        except ValidationError:
            continue
        raise AssertionError(f"recipe accepted {why}: {bad}")
    try:
        DeliveryRecipe.model_validate(
            {"id": "r", "name": "x" * 65, "items": [item("h264-1080p", "a.mp4")]}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("recipe accepted a name longer than 64")
    try:
        DeliveryRecipe.model_validate(
            {"id": "r", "name": "n", "items": [item("h264-1080p", "a.mp4")], "crf": 20}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("a recipe accepted an encoder flag")

    # The union has to actually resolve the new ops: this is the same parse the HTTP body and the
    # MCP schema generated from the contract go through.
    batch = EditBatch.model_validate(
        {
            "request_id": "x",
            "expected_revision": 1,
            "commands": [
                {"op": "recipe.set", "recipe": recipe()},
                {"op": "recipe.remove", "recipe_id": "r-web"},
            ],
        }
    )
    assert [type(command).__name__ for command in batch.commands] == [
        "RecipeSet",
        "RecipeRemove",
    ], batch
    assert RenderBatchItem.model_validate(item("h264-1080p", "a.mp4")).range == "full"
    print("   recipes: the contract stores items, refuses paths, duplicates, oversize and flags")


def http_suite(folder: Path) -> None:
    media = MediaService(folder / "rc-db.sqlite3", [folder], folder / "rc-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "rc-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "recipechk" + "f" * 53
    app = create_app(folder / "rc-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["project_schema_version"] == SCHEMA_VERSION, caps["project_schema_version"]
        assert caps["features"]["delivery_recipes"] is True, caps["features"]
        assert "recipe.set" in caps["commands"] and "recipe.remove" in caps["commands"], caps[
            "commands"
        ]

        clip = source(folder)
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post("/v1/projects", json={"request_id": "new", "name": "recipes"}).json()[
            "project"
        ]
        path = f"/v1/projects/{created['id']}"
        assert created["schema_version"] == SCHEMA_VERSION
        assert created["recipes"] == [], created
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "recipe",
                        "probe_id": probe["verified"]["probe_id"],
                        "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 6 * T,
                        },
                    },
                ],
            },
        )
        revision = seeded.json()["project"]["revision"]

        saved = client.post(
            path + "/edits",
            json={
                "request_id": "r-save",
                "expected_revision": revision,
                "commands": [{"op": "recipe.set", "recipe": recipe()}],
            },
        )
        body = saved.json()["project"]
        assert saved.status_code == 200 and body["revision"] == revision + 1, saved.text
        assert [entry["name"] for entry in body["recipes"]] == ["网络交付"], body["recipes"]
        assert body["recipes"][0]["items"][1]["fit"] == "cover", body["recipes"]

        replay = client.post(
            path + "/edits",
            json={
                "request_id": "r-save",
                "expected_revision": revision,
                "commands": [{"op": "recipe.set", "recipe": recipe()}],
            },
        )
        assert replay.json()["replayed"] is True, replay.text
        assert client.get(path).json()["revision"] == revision + 1, (
            "a replay must not add a revision"
        )
        assert len(client.get(path).json()["recipes"]) == 1, (
            "a replay must not duplicate the recipe"
        )

        replaced = client.post(
            path + "/edits",
            json={
                "request_id": "r-replace",
                "expected_revision": revision + 1,
                "commands": [{"op": "recipe.set", "recipe": recipe(name="网络交付 v2")}],
            },
        )
        now = replaced.json()["project"]
        assert now["revision"] == revision + 2 and len(now["recipes"]) == 1, now["recipes"]
        assert now["recipes"][0]["name"] == "网络交付 v2", now["recipes"]
        print(
            "   recipes: one write is one revision, a replay returns its receipt, a re-set replaces"
        )

        dry = client.post(
            path + "/edits",
            json={
                "request_id": "r-dry",
                "expected_revision": revision + 2,
                "dry_run": True,
                "commands": [{"op": "recipe.set", "recipe": recipe("r-other", "草稿")}],
            },
        )
        assert dry.status_code == 200 and dry.json()["committed"] is False, dry.text
        # A dry run describes the project it *would* produce, so the proof it wrote nothing is the
        # stored project: same revision, same single recipe.
        assert dry.json()["project"]["revision"] == revision + 3, dry.text
        assert dry.json()["project"]["recipes"][1]["name"] == "草稿", dry.text
        after_dry = client.get(path).json()
        assert after_dry["revision"] == revision + 2, after_dry
        assert len(after_dry["recipes"]) == 1, "a dry run wrote a recipe"

        unknown = client.post(
            path + "/edits",
            json={
                "request_id": "r-bogus",
                "expected_revision": revision + 2,
                "commands": [
                    {
                        "op": "recipe.set",
                        "recipe": recipe("r-bad", "坏方案", [item("not-a-preset", "x.mp4")]),
                    }
                ],
            },
        )
        assert unknown.status_code == 422, unknown.text
        assert unknown.json()["error"]["code"] == "INVALID_RECIPE", unknown.text
        assert "not-a-preset" in unknown.json()["error"]["message"], unknown.json()["error"]
        assert client.get(path).json()["revision"] == revision + 2, (
            "a refused recipe burned a revision"
        )
        print("   recipes: an unknown preset is refused by name and costs no revision")

        stale = client.post(
            path + "/edits",
            json={
                "request_id": "r-stale",
                "expected_revision": revision,
                "commands": [{"op": "recipe.remove", "recipe_id": "r-web"}],
            },
        )
        assert stale.status_code == 409, stale.text
        missing = client.post(
            path + "/edits",
            json={
                "request_id": "r-missing",
                "expected_revision": revision + 2,
                "commands": [{"op": "recipe.remove", "recipe_id": "nope"}],
            },
        )
        assert missing.status_code == 404, missing.text

        # The stored items have to be what the batch actually renders — otherwise the recipe is a
        # decoration and the client still has to rebuild the request by hand.
        plan = client.post(
            path + "/renders/batch",
            json={
                "request_id": "b-preview",
                "expected_revision": revision + 2,
                "dry_run": True,
                "items": client.get(path).json()["recipes"][0]["items"],
            },
        )
        assert plan.status_code == 200 and len(plan.json()["jobs"]) == 2, plan.text
        assert [job["fit"] for job in plan.json()["jobs"]] == ["contain", "cover"], plan.text
        assert client.get(f"{path}/jobs").json()["jobs"] == [], "a previewed batch queued work"

        sent = client.post(
            path + "/renders/batch",
            json={
                "request_id": "b-real",
                "expected_revision": revision + 2,
                "items": client.get(path).json()["recipes"][0]["items"],
            },
        )
        assert sent.status_code == 200, sent.text
        finished = {}
        for job in sent.json()["jobs"]:
            status = {}
            for _ in range(600):
                status = client.get("/v1/jobs/" + job["id"]).json()["job"]
                if status["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.5)
            assert status["status"] == "succeeded", (job, status)
            finished[job["filename"]] = status
        assert set(finished) == {"horizontal.mp4", "vertical.mp4"}, finished
        sizes = {}
        for name, status in finished.items():
            out = run(
                [
                    str(FFPROBE),
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "json",
                    status["output_path"],
                ]
            )
            stream = json.loads(out.decode())["streams"][0]
            sizes[name] = (int(stream["width"]), int(stream["height"]))
        assert sizes["horizontal.mp4"] == (1920, 1080) and sizes["vertical.mp4"] == (1080, 1920), (
            sizes
        )
        print(f"   recipes: the saved items drove the batch — {sizes}")

        # A recipe with a marked range ships that window, and refuses when there is none.
        marked = client.post(
            path + "/edits",
            json={
                "request_id": "r-marks",
                "expected_revision": revision + 2,
                "commands": [
                    {
                        "op": "recipe.set",
                        "recipe": recipe(
                            "r-cut",
                            "区间交付",
                            [item("h264-720p-web", "cut.mp4", **{"range": "marks"})],
                        ),
                    }
                ],
            },
        )
        head = marked.json()["project"]["revision"]
        queued_before = len(client.get(f"{path}/jobs").json()["jobs"])
        without = client.post(
            path + "/renders/batch",
            json={
                "request_id": "b-nomarks",
                "expected_revision": head,
                "items": [item("h264-720p-web", "cut.mp4", **{"range": "marks"})],
            },
        )
        assert without.status_code == 422 and without.json()["error"]["code"] == "INVALID_MARKS", (
            without.text
        )
        assert len(client.get(f"{path}/jobs").json()["jobs"]) == queued_before, (
            "a batch that cannot compile queued a job"
        )

        settings = marked.json()["project"]["settings"]
        marked_range = client.post(
            f"/v1/projects/{created['id']}",
            json={
                "request_id": "s-marks",
                "expected_revision": head,
                "settings": {**settings, "in_ticks": 2 * T, "out_ticks": 4 * T},
            },
        )
        assert marked_range.status_code == 200, marked_range.text
        head = marked_range.json()["project"]["revision"]
        shipped = client.post(
            path + "/renders/batch",
            json={
                "request_id": "b-marks",
                "expected_revision": head,
                "items": client.get(path).json()["recipes"][-1]["items"],
            },
        )
        assert shipped.status_code == 200, shipped.text
        status = {}
        for _ in range(600):
            status = client.get("/v1/jobs/" + shipped.json()["jobs"][0]["id"]).json()["job"]
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.5)
        assert status["status"] == "succeeded", status
        out = run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                status["output_path"],
            ]
        )
        seconds = float(json.loads(out.decode())["format"]["duration"])
        assert abs(seconds - 2.0) <= 0.05, seconds
        assert status["range"] == "marks", status
        print(f"   recipes: a stored range=marks item shipped {seconds:.3f} s of the window")

        undone = client.post(
            path + "/restore",
            json={"request_id": "undo", "expected_revision": head, "target_revision": revision + 2},
        )
        back = undone.json()["project"]
        assert undone.status_code == 200 and back["revision"] == head + 1, undone.text
        assert [entry["id"] for entry in back["recipes"]] == ["r-web"], back["recipes"]
        print("   recipes: restoring an older snapshot brings the recipe list back as it was")

        reopened = ProjectStore(folder / "rc-api.sqlite3").get(created["id"])
        assert [entry.id for entry in reopened.recipes] == ["r-web"], reopened.recipes
        assert reopened.recipes[0].items[0].preset_id == "h264-1080p", reopened.recipes[0]
        print("   recipes: a fresh store over the same file reads the recipes back off disk")

        removed = client.post(
            path + "/edits",
            json={
                "request_id": "r-drop",
                "expected_revision": head + 1,
                "commands": [{"op": "recipe.remove", "recipe_id": "r-web"}],
            },
        )
        assert removed.json()["project"]["recipes"] == [], removed.text
        print("   recipes: removing the last recipe leaves an empty list, not a missing key")


def main() -> None:
    folder = scratch.make("agentcut-recipes-")
    contract_suite()
    http_suite(folder)
    print("PASS: delivery recipes are project state — validated, replayable, undoable, shipped")


if __name__ == "__main__":
    main()
