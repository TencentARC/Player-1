"""Open an explicitly selected local recording; never infer its game identity."""

from pathlib import Path

from player1_data.sources.common import SamplingConfig

ADAPTER_IDS = {
    "vpt": "vpt-contractor",
    "pixel2play": "pixel2play",
    "gaming500": "gaming-500-hours",
    "d2e": "d2e",
}


def open_recording(record):
    source, path = record["source"], Path(record["input"])
    options = {"source_revision": record["source_revision"]} if "source_revision" in record else {}
    if source == "vpt":
        from player1_data.sources.vpt.adapter import VPTContractorAdapter

        return VPTContractorAdapter(path, Path(record["video"]) if record.get("video") else None, **options)
    if source == "pixel2play":
        from player1_data.sources.pixel2play.adapter import Pixel2PlayAdapter

        return Pixel2PlayAdapter(path, **options)
    if source == "gaming500":
        from player1_data.sources.gaming500.adapter import Gaming500HoursAdapter

        return Gaming500HoursAdapter(path, **options)
    if source != "d2e":
        raise ValueError(f"Unknown recording source: {source}")
    from player1_data.sources.allowlist import load_desktop_mcap_session_allowlist
    from player1_data.sources.d2e.adapter import D2EAdapter

    start = record.get("start_ms", 2000)
    if record.get("mode", "gameplay") == "gameplay":
        options.update(
            capture_geometry_action_range_ms=(start, start + record.get("count", 1) * 10000),
            bounded_read_config=SamplingConfig(
                start_time_ms=start,
                max_samples=record.get("count", 1) * 50,
            ),
        )
    adapter = D2EAdapter(path, Path(record["video"]) if record.get("video") else None, **options)
    root = Path(record["source_root"])
    allowlist = load_desktop_mcap_session_allowlist(Path(record["session_allowlist"]), source_root=root)
    session = adapter.session
    if not allowlist.contains_source(
        dataset_id=session.dataset_id,
        source_revision=session.source_revision,
        session_id=session.session_id,
        local_input=path.relative_to(root).as_posix(),
    ):
        raise ValueError("D2E recording is outside its reviewed session allowlist")
    return adapter
