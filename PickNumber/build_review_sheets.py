"""Download official thumbnails and assemble manual-review contact sheets."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

from PickNumber.draw_context_collection import DEFAULT_CONTEXT_DIR, read_jsonl


def download_thumbnail(source: dict, path: Path) -> str:
    urls = [
        source["source_thumbnail_url"],
        f"https://i.ytimg.com/vi/{source['video_id']}/hqdefault.jpg",
    ]
    for index, url in enumerate(urls):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "hotnumber-context-research/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                path.write_bytes(response.read())
            return "maxresdefault" if index == 0 else "hqdefault"
        except urllib.error.HTTPError:
            if index == len(urls) - 1:
                raise
    raise RuntimeError("No thumbnail URL was attempted")


def build_sheets(context_dir: Path, batch_path: Path, output_dir: Path) -> dict:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    sources = {
        int(record["round"]): record
        for record in read_jsonl(context_dir / "video_sources.jsonl")
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    images = []
    fallback_rounds = []
    for round_number in batch["rounds"]:
        path = output_dir / f"{round_number}.jpg"
        method = download_thumbnail(sources[round_number], path)
        if method == "hqdefault":
            fallback_rounds.append(round_number)
        image = Image.open(path).convert("RGB")
        image.thumbnail((640, 360))
        canvas = Image.new("RGB", (640, 360), "black")
        canvas.paste(image, ((640 - image.width) // 2, (360 - image.height) // 2))
        images.append((round_number, canvas))

    for start in range(0, len(images), 4):
        sheet = Image.new("RGB", (1280, 720), "white")
        draw = ImageDraw.Draw(sheet)
        for index, (round_number, image) in enumerate(images[start : start + 4]):
            x = (index % 2) * 640
            y = (index // 2) * 360
            sheet.paste(image, (x, y))
            draw.rectangle((x, y, x + 72, y + 24), fill="black")
            draw.text((x + 4, y + 4), str(round_number), fill="white")
        sheet.save(output_dir / f"sheet_{start // 4 + 1:02d}.jpg", quality=92)

    return {
        "rounds": len(images),
        "sheets": (len(images) + 3) // 4,
        "hqdefault_fallback_rounds": fallback_rounds,
        "output_dir": str(output_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_sheets(args.context_dir, args.batch, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
