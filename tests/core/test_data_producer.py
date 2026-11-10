"""Recording-wide scheduling and producer-lock recovery."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from player1_data import pipeline
from player1_data.files import file_digest, fingerprint
from player1_data.sources.common import SampleAnchor, SourceSession
from player1_data.sources.recording import ADAPTER_IDS
from player1_data.standardize import trajectory


def test_supported_recording_sources():
    assert set(ADAPTER_IDS) == {"vpt", "pixel2play", "gaming500", "d2e"}


def test_work_lock_rejects_concurrent_writer_and_recovers_after_exit(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    (work / ".writer.lock").write_text("12345")
    child = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys, threading\n"
            "from pathlib import Path\n"
            "from player1_data import pipeline\n"
            "def wait(*args, **kwargs):\n"
            "    print('locked', flush=True)\n"
            "    threading.Event().wait()\n"
            "pipeline.write_dataset = wait\n"
            "pipeline.run({'recordings': []}, work=Path(sys.argv[1]), output=Path(sys.argv[2]), client=object())\n",
            str(work),
            str(tmp_path / "child-output"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    reader = ThreadPoolExecutor(max_workers=1)
    try:
        assert reader.submit(child.stdout.readline).result(timeout=15).strip() == "locked"
        monkeypatch.setattr(pipeline, "write_dataset", lambda *args, **kwargs: "written")
        with pytest.raises(ValueError, match="locked by a producer"):
            pipeline.run({"recordings": []}, work=work, output=tmp_path / "blocked", client=object())
        child.terminate()
        child.wait(timeout=10)
        for name in ("restarted", "repeated"):
            assert pipeline.run({"recordings": []}, work=work, output=tmp_path / name, client=object()) == "written"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        reader.shutdown(wait=True)
        child.stdout.close()


def test_gameplay_growth_preserves_source_offset_and_cached_prefix(tmp_path, monkeypatch):
    source = tmp_path / "recording"
    source.write_bytes(b"recorded inputs")
    sampled = []

    def anchors(config):
        sampled.append(config.max_samples)
        for index in range(config.max_samples):
            yield SampleAnchor(max(50, config.start_time_ms) + index * 200)

    def ordinary(adapter, record, selected, partition, root, calibrations):
        picture = root / "frame.jpg"
        picture.write_bytes(b"recorded frame")
        turns = [
            {
                "index": index,
                "action": {"key_hold": ["w" if index % 2 else "a"]},
                "canonical_action": str(index % 2),
                "image": picture.name,
                "image_sha256": file_digest(picture)["sha256"],
                "action_time_ns": interval.start_ns,
            }
            for index, interval in enumerate(partition.intervals)
        ]
        return turns, [partition.coverage_start_ns, partition.coverage_end_ns], []

    adapter = SimpleNamespace(
        session=SourceSession("fixture", "1", "session", "Fixture", (source,), {}),
        iter_anchors=anchors,
        source_native_action_clock_ns=lambda anchor: round(anchor.video_time_ms * 1e6),
        source_native_onset_owner_policy="anchor_interval",
    )
    record = {"source": "vpt", "input": str(source), "game": {"name": "Fixture", "version": "1"}, "start_ms": 0}
    monkeypatch.setattr(trajectory, "_ordinary", ordinary)
    first = trajectory.prepare_recording(adapter, record, tmp_path / "work")
    prefix = (first[0][0] / "prepared.json").read_bytes()
    grown = trajectory.prepare_recording(adapter, {**record, "count": 2}, tmp_path / "work")
    assert sampled == [50, 100]
    assert (first[0][0] / "prepared.json").read_bytes() == prefix
    assert [item["source_span_ns"] for _, item in grown] == [
        [50_000_000, 10_050_000_000],
        [10_050_000_000, 20_050_000_000],
    ]
    cached = json.loads(prefix)
    cached["trajectory"]["turns"][0]["action_time_ns"] += 1
    cached["sha256"] = fingerprint(cached["trajectory"])
    (first[0][0] / "prepared.json").write_text(json.dumps(cached))
    with pytest.raises(ValueError, match="different action schedule"):
        trajectory.prepare_recording(adapter, record, tmp_path / "work")
