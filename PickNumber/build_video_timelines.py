"""Download official draw videos and render late-video review timelines."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PickNumber.draw_context_collection import DEFAULT_CONTEXT_DIR, read_jsonl


def parse_rounds(raw: str) -> list[int]:
    return [int(value) for value in raw.replace(",", " ").split()]


def build_timelines(
    context_dir: Path,
    output_dir: Path,
    rounds: list[int],
    yt_dlp_lib: Path,
    timeline_start: int = 240,
) -> dict:
    sys.path.insert(0, str(yt_dlp_lib))
    import yt_dlp  # type: ignore[import-not-found]

    sources = {
        int(record["round"]): record
        for record in read_jsonl(context_dir / "video_sources.jsonl")
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = []
    for round_number in rounds:
        video_path = output_dir / f"{round_number}_full.mp4"
        if not video_path.exists():
            options = {
                "format": "134",
                "outtmpl": str(video_path),
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([sources[round_number]["source_url"]])

        timeline_path = output_dir / f"{round_number}_timeline.png"
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(timeline_start),
                "-i",
                str(video_path),
                "-vf",
                "fps=1/5,scale=480:-1,format=rgb24,tile=4x4",
                "-frames:v",
                "1",
                "-update",
                "1",
                str(timeline_path),
            ],
            check=True,
        )
        completed.append(round_number)
    return {"completed_rounds": completed, "output_dir": str(output_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rounds", required=True)
    parser.add_argument("--yt-dlp-lib", type=Path, required=True)
    parser.add_argument("--timeline-start", type=int, default=240)
    args = parser.parse_args()
    result = build_timelines(
        args.context_dir,
        args.output_dir,
        parse_rounds(args.rounds),
        args.yt_dlp_lib,
        args.timeline_start,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
