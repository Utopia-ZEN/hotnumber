"""Collect and audit source-backed physical context for Lotto 6/45 draws."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PickNumber.order_model import Draw, load_draws


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "lotto_data"
DEFAULT_CONTEXT_DIR = DEFAULT_DATA_DIR / "draw_context"
DEFAULT_INDEX_URL = "https://todaylotto.kr/broadcasts"
OFFICIAL_CHANNEL = "동행복권"
OFFICIAL_CHANNEL_URL = "https://www.youtube.com/@donghanglottery"
OFFICIAL_BROADCASTER_ARCHIVES = {
    ("SBS STORY", "https://www.youtube.com/@SBSstory.official"),
    ("SBS STORY", "https://www.youtube.com/channel/UCYZv9v_bwfMGc64gLRe34OA"),
}
DEFAULT_MIN_SAMPLE = 100
TITLE_PATTERN = re.compile(
    r"^로또(?:\s*6/45)?\s*제\s*(?P<round>\d+)회 당첨번호[_\s]+"
    r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일(?:\s*추첨)?$"
)
CARD_PATTERN = re.compile(
    r'<a\s+href="(?P<url>https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]+)"[^>]*>'
    r'.*?<img[^>]+alt="(?P<title>로또(?:\s*6/45)?\s*제\s*\d+회 당첨번호[_\s]+[^"]+)"',
    re.DOTALL,
)
LOOSE_ROUND_PATTERN = re.compile(
    r"로또(?:\s*6/45)?\s*(?:제\s*)?(?P<round>\d+)\s*(?:회)?"
)
ENGLISH_LOTTO_ROUND_PATTERN = re.compile(
    r"\bLotto\s+(?P<round>\d+)(?:st|nd|rd|th)?\b", re.IGNORECASE
)
REUPLOAD_REQUIRED_CHECKS = (
    "round_label_visible",
    "continuous_draw_sequence_visible",
    "winning_numbers_match",
    "bonus_match",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "hotnumber-context-research/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def video_id_from_url(url: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    values = query.get("v", [])
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", values[0]):
        raise ValueError(f"Invalid YouTube watch URL: {url}")
    return values[0]


def source_record_from_title(
    source_url: str,
    title: str,
    discovery_url: str,
    retrieved_at_utc: str,
) -> dict[str, Any] | None:
    title = unicodedata.normalize("NFC", title)
    title_match = TITLE_PATTERN.fullmatch(title)
    if title_match is None:
        return None
    round_number = int(title_match.group("round"))
    draw_date = (
        f"{title_match.group('year')}-{int(title_match.group('month')):02d}-"
        f"{int(title_match.group('day')):02d}"
    )
    video_id = video_id_from_url(source_url)
    return {
        "schema_version": 2,
        "round": round_number,
        "draw_date": draw_date,
        "source_url": source_url,
        "draw_video_url": f"{source_url}&t=325s",
        "video_id": video_id,
        "source_title": title,
        "source_channel": None,
        "source_channel_url": None,
        "source_type": "unverified",
        "source_thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        "source_verified": False,
        "discovery_url": discovery_url,
        "retrieved_at_utc": retrieved_at_utc,
        "review_status": "pending",
        "reviewed_at_utc": None,
        "review_method": None,
        "machine_id": None,
        "ball_set_id": None,
        "ordered_numbers": None,
        "bonus_number": None,
        "machine_start_offset_seconds": None,
        "result_board_offset_seconds": None,
        "ball_position_observations": [],
        "evidence_notes": None,
    }


def source_record_from_search_result(
    source_url: str,
    title: str,
    discovery_url: str,
    retrieved_at_utc: str,
    expected_round: int,
) -> dict[str, Any] | None:
    title = unicodedata.normalize("NFC", title)
    strict = source_record_from_title(source_url, title, discovery_url, retrieved_at_utc)
    if strict is not None:
        return strict if strict["round"] == expected_round else None
    korean_context = "로또" in title and any(token in title for token in ("추첨", "당첨"))
    english_context = "lotto" in title.lower() and "draw" in title.lower()
    if not korean_context and not english_context:
        return None
    rounds = {int(match.group("round")) for match in LOOSE_ROUND_PATTERN.finditer(title)}
    rounds.update(
        int(match.group("round")) for match in ENGLISH_LOTTO_ROUND_PATTERN.finditer(title)
    )
    if rounds != {expected_round}:
        return None
    video_id = video_id_from_url(source_url)
    return {
        "schema_version": 2,
        "round": expected_round,
        "draw_date": None,
        "source_url": source_url,
        "draw_video_url": f"{source_url}&t=240s",
        "video_id": video_id,
        "source_title": title,
        "source_channel": None,
        "source_channel_url": None,
        "source_type": "unverified",
        "source_thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        "source_verified": False,
        "metadata_round_verified": True,
        "discovery_url": discovery_url,
        "retrieved_at_utc": retrieved_at_utc,
        "review_status": "pending",
        "reviewed_at_utc": None,
        "review_method": None,
        "machine_id": None,
        "ball_set_id": None,
        "ordered_numbers": None,
        "bonus_number": None,
        "machine_start_offset_seconds": None,
        "result_board_offset_seconds": None,
        "ball_position_observations": [],
        "evidence_notes": None,
    }


def parse_video_cards(page_html: str, discovery_url: str, retrieved_at_utc: str) -> list[dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    for match in CARD_PATTERN.finditer(page_html):
        title = html.unescape(match.group("title"))
        record = source_record_from_title(
            html.unescape(match.group("url")), title, discovery_url, retrieved_at_utc
        )
        if record is None:
            continue
        records[record["round"]] = record
    return [records[key] for key in sorted(records)]


def _renderer_text(value: dict[str, Any]) -> str:
    return value.get("simpleText", "") or "".join(run.get("text", "") for run in value.get("runs", []))


def _extract_search_page(payload: Any) -> tuple[list[tuple[str, str]], list[str]]:
    videos: list[tuple[str, str]] = []
    continuations: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            renderer = value.get("videoRenderer")
            if renderer:
                title = _renderer_text(renderer.get("title", {}))
                if title and renderer.get("videoId"):
                    videos.append((renderer["videoId"], title))
            continuation = value.get("continuationItemRenderer")
            if continuation:
                find_token(continuation)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    def find_token(value: Any) -> None:
        if isinstance(value, dict):
            command = value.get("continuationCommand")
            if command and command.get("token"):
                continuations.append(command["token"])
            for child in value.values():
                find_token(child)
        elif isinstance(value, list):
            for child in value:
                find_token(child)

    visit(payload)
    return list(dict.fromkeys(videos)), list(dict.fromkeys(continuations))


def discover_official_channel(search_query: str, max_pages: int, retrieved_at_utc: str) -> list[dict[str, Any]]:
    search_url = "https://www.youtube.com/@donghanglottery/search?" + urllib.parse.urlencode(
        {"query": search_query}
    )
    raw = fetch_text(search_url)
    marker = "var ytInitialData = "
    start = raw.index(marker) + len(marker)
    initial, _ = json.JSONDecoder().raw_decode(raw[start:])
    api_key = re.search(r'INNERTUBE_API_KEY\\?"?:\\?"([^"\\]+)', raw)
    client_version = re.search(r'INNERTUBE_CONTEXT_CLIENT_VERSION\\?"?:\\?"([^"\\]+)', raw)
    visitor_data = re.search(r'VISITOR_DATA\\?"?:\\?"([^"\\]+)', raw)
    if not api_key or not client_version or not visitor_data:
        raise ValueError("YouTube channel search metadata is incomplete")

    videos, tokens = _extract_search_page(initial)
    continuation = tokens[0] if tokens else None
    headers = {"User-Agent": "hotnumber-context-research/1.0", "Content-Type": "application/json"}
    for _ in range(max_pages):
        if continuation is None:
            break
        body = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": client_version.group(1),
                    "hl": "ko",
                    "gl": "KR",
                    "visitorData": visitor_data.group(1),
                }
            },
            "continuation": continuation,
        }
        endpoint = "https://www.youtube.com/youtubei/v1/browse?key=" + api_key.group(1)
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
        page_videos, tokens = _extract_search_page(payload)
        videos.extend(page_videos)
        continuation = tokens[0] if tokens else None

    records: dict[int, dict[str, Any]] = {}
    for video_id, title in videos:
        record = source_record_from_title(
            f"https://www.youtube.com/watch?v={video_id}", title, search_url, retrieved_at_utc
        )
        if record is not None:
            records[record["round"]] = record
    return [records[key] for key in sorted(records)]


def discover_exact_round(round_number: int, retrieved_at_utc: str) -> list[dict[str, Any]]:
    records = []
    seen_video_ids = set()
    for query in (
        f"로또6/45 제{round_number}회 당첨번호",
        f"로또 제{round_number}회 당첨번호",
        f"로또 {round_number}회 추첨방송",
    ):
        search_url = "https://www.youtube.com/results?" + urllib.parse.urlencode(
            {"search_query": query}
        )
        raw = fetch_text(search_url)
        marker = "var ytInitialData = "
        start = raw.index(marker) + len(marker)
        initial, _ = json.JSONDecoder().raw_decode(raw[start:])
        videos, _ = _extract_search_page(initial)
        for video_id, title in videos:
            if video_id in seen_video_ids:
                continue
            seen_video_ids.add(video_id)
            record = source_record_from_search_result(
                f"https://www.youtube.com/watch?v={video_id}",
                title,
                search_url,
                retrieved_at_utc,
                round_number,
            )
            if record is not None and record["round"] == round_number:
                records.append(record)
    return records


def verify_youtube_source(record: dict[str, Any]) -> dict[str, Any]:
    endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": record["source_url"], "format": "json"}
    )
    payload = json.loads(fetch_text(endpoint))
    channel = str(payload.get("author_name", "")).strip()
    channel_url = str(payload.get("author_url", "")).strip().rstrip("/")
    title = unicodedata.normalize("NFC", str(payload.get("title", "")).strip())
    expected = TITLE_PATTERN.fullmatch(title)
    record = dict(record)
    record["source_channel"] = channel or None
    record["source_channel_url"] = channel_url or None
    record["source_title"] = title or record["source_title"]
    official_channel = bool(
        channel == OFFICIAL_CHANNEL
        and channel_url == OFFICIAL_CHANNEL_URL
        and expected is not None
        and int(expected.group("round")) == record["round"]
    )
    loose_rounds = {int(match.group("round")) for match in LOOSE_ROUND_PATTERN.finditer(title)}
    loose_rounds.update(
        int(match.group("round")) for match in ENGLISH_LOTTO_ROUND_PATTERN.finditer(title)
    )
    official_archive = bool(
        (channel, channel_url) in OFFICIAL_BROADCASTER_ARCHIVES
        and loose_rounds == {int(record["round"])}
    )
    record["source_verified"] = official_channel or official_archive
    record["metadata_round_verified"] = loose_rounds == {int(record["round"])}
    if official_channel:
        record["source_type"] = "official_channel"
    elif official_archive:
        record["source_type"] = "official_broadcaster_archive"
    else:
        record["source_type"] = "third_party_reupload"
    return record


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return records


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda item: int(item["round"]))
    body = "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in ordered)
    path.write_text(body, encoding="utf-8")


def write_review_queue(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "round",
                "draw_date",
                "source_verified",
                "source_type",
                "source_channel",
                "review_status",
                "review_url",
                "source_title",
            ],
        )
        writer.writeheader()
        for record in sorted(records, key=lambda item: int(item["round"]), reverse=True):
            writer.writerow(
                {
                    "round": record["round"],
                    "draw_date": record["draw_date"],
                    "source_verified": record["source_verified"],
                    "source_type": record.get("source_type", "unverified"),
                    "source_channel": record.get("source_channel"),
                    "review_status": record["review_status"],
                    "review_url": record["draw_video_url"],
                    "source_title": record["source_title"],
                }
            )


def merge_by_round(existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {int(record["round"]): record for record in existing}
    for record in incoming:
        round_number = int(record["round"])
        if merged.get(round_number, {}).get("review_status") == "verified":
            continue
        merged[round_number] = record
    return [merged[key] for key in sorted(merged)]


def replace_by_round(existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {int(record["round"]): record for record in existing}
    merged.update({int(record["round"]): record for record in incoming})
    return [merged[key] for key in sorted(merged)]


def parse_number_list(raw: str | Iterable[int]) -> list[int]:
    if isinstance(raw, str):
        values = [int(value) for value in re.split(r"[\s,]+", raw.strip()) if value]
    else:
        values = [int(value) for value in raw]
    if len(values) != 6 or len(set(values)) != 6 or min(values) < 1 or max(values) > 45:
        raise ValueError("Extraction order must contain six unique numbers from 1 to 45")
    return values


def validate_observation(record: dict[str, Any], draw: Draw) -> None:
    if record.get("review_status") != "verified":
        raise ValueError("Observation must be marked verified")
    official = bool(
        record.get("source_verified")
        and (
            record.get("source_channel") == OFFICIAL_CHANNEL
            or record.get("source_type") == "official_broadcaster_archive"
        )
    )
    if not official:
        checks = record.get("content_verification")
        valid_reupload = bool(
            record.get("source_type") == "third_party_reupload"
            and record.get("source_channel")
            and record.get("source_channel_url")
            and record.get("metadata_round_verified")
            and isinstance(checks, dict)
            and all(checks.get(key) is True for key in REUPLOAD_REQUIRED_CHECKS)
        )
        if not valid_reupload:
            raise ValueError("Third-party reupload requires complete video-content verification")
    ordered = record.get("ordered_numbers")
    if not isinstance(ordered, list) or len(ordered) != 6 or len(set(ordered)) != 6:
        raise ValueError("Verified observation requires six unique ordered numbers")
    if set(int(value) for value in ordered) != set(draw.numbers):
        raise ValueError("Extraction order does not match the official winning-number set")
    if int(record.get("bonus_number")) != draw.bonus:
        raise ValueError("Observed bonus number does not match the official draw")


def build_observation(
    source: dict[str, Any],
    draw: Draw,
    ordered_numbers: list[int],
    bonus_number: int,
    result_offset: float | None,
    machine_id: str | None = None,
    ball_set_id: str | None = None,
    notes: str | None = None,
    review_method: str = "manual_video_review",
    content_verification: dict[str, bool] | None = None,
) -> dict[str, Any]:
    record = dict(source)
    record.update(
        {
            "review_status": "verified",
            "reviewed_at_utc": utc_now(),
            "review_method": review_method,
            "machine_id": machine_id,
            "ball_set_id": ball_set_id,
            "ordered_numbers": ordered_numbers,
            "bonus_number": int(bonus_number),
            "result_board_offset_seconds": float(result_offset) if result_offset is not None else None,
            "ball_position_observations": [
                {
                    "offset_seconds": float(result_offset) if result_offset is not None else None,
                    "phase": "result_rack",
                    "position_basis": "left_to_right",
                    "ordered_visible_numbers": [*ordered_numbers, int(bonus_number)],
                    "confidence": "high",
                }
            ],
            "evidence_notes": notes,
            "content_verification": content_verification,
        }
    )
    validate_observation(record, draw)
    return record


def audit_records(records: Iterable[dict[str, Any]], minimum_sample: int = DEFAULT_MIN_SAMPLE) -> dict[str, Any]:
    records = list(records)
    verified = [record for record in records if record.get("review_status") == "verified"]
    ordered = [record for record in verified if record.get("ordered_numbers")]
    machine_counts = Counter(record["machine_id"] for record in verified if record.get("machine_id"))
    ball_set_counts = Counter(record["ball_set_id"] for record in verified if record.get("ball_set_id"))
    combined_counts = Counter(
        f"{record['machine_id']}|{record['ball_set_id']}"
        for record in verified
        if record.get("machine_id") and record.get("ball_set_id")
    )
    source_type_counts = Counter(
        record.get("source_type")
        or ("official_channel" if record.get("source_verified") else "unknown")
        for record in verified
    )

    def group_report(counts: Counter[str]) -> dict[str, Any]:
        values = dict(sorted(counts.items()))
        return {
            "counts": values,
            "eligible_values": sorted(key for key, count in counts.items() if count >= minimum_sample),
        }

    return {
        "generated_at_utc": utc_now(),
        "minimum_sample": minimum_sample,
        "records_total": len(records),
        "verified_records": len(verified),
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "ordered_sequence": {
            "count": len(ordered),
            "eligible": len(ordered) >= minimum_sample,
        },
        "machine": group_report(machine_counts),
        "ball_set": group_report(ball_set_counts),
        "machine_ball_set": group_report(combined_counts),
        "conditional_model_allowed": bool(
            len(ordered) >= minimum_sample
            or any(count >= minimum_sample for count in machine_counts.values())
            or any(count >= minimum_sample for count in ball_set_counts.values())
            or any(count >= minimum_sample for count in combined_counts.values())
        ),
    }


def require_model_gate(report: dict[str, Any], category: str, value: str | None = None) -> None:
    if category == "ordered_sequence":
        eligible = bool(report[category]["eligible"])
    elif category in {"machine", "ball_set", "machine_ball_set"}:
        if value is None:
            raise ValueError(f"{category} gate requires a condition value")
        eligible = value in report[category]["eligible_values"]
    else:
        raise ValueError(f"Unknown context category: {category}")
    if not eligible:
        raise RuntimeError(
            f"Conditional model gate is closed for {category}"
            + (f"={value}" if value else "")
            + f"; at least {report['minimum_sample']} verified draws are required"
        )


def command_discover(args: argparse.Namespace) -> None:
    retrieved = utc_now()
    records = parse_video_cards(fetch_text(args.index_url), args.index_url, retrieved)
    records = [
        record
        for record in records
        if (args.min_round is None or record["round"] >= args.min_round)
        and (args.max_round is None or record["round"] <= args.max_round)
    ]
    if not args.skip_oembed:
        verified_records = []
        for record in records:
            try:
                verified_records.append(verify_youtube_source(record))
            except (OSError, ValueError, json.JSONDecodeError):
                verified_records.append(record)
        records = verified_records
    manifest = args.context_dir / "video_sources.jsonl"
    merged = merge_by_round(read_jsonl(manifest), records)
    write_jsonl(manifest, merged)
    observations = {
        int(record["round"]): record for record in read_jsonl(args.context_dir / "observations.jsonl")
    }
    queue_records = []
    for record in merged:
        queue_record = dict(record)
        if record["round"] in observations:
            queue_record["review_status"] = observations[record["round"]]["review_status"]
        queue_records.append(queue_record)
    write_review_queue(args.context_dir / "review_queue.csv", queue_records)
    verified_count = sum(bool(record["source_verified"]) for record in records)
    print(f"discovered={len(records)} official_verified={verified_count} manifest={manifest}")


def command_discover_channel(args: argparse.Namespace) -> None:
    retrieved = utc_now()
    records = discover_official_channel(args.query, args.pages, retrieved)
    records = [
        record
        for record in records
        if (args.min_round is None or record["round"] >= args.min_round)
        and (args.max_round is None or record["round"] <= args.max_round)
    ]
    verified_records = []
    for record in records:
        try:
            verified_records.append(verify_youtube_source(record))
        except (OSError, ValueError, json.JSONDecodeError):
            verified_records.append(record)
    records = verified_records
    manifest = args.context_dir / "video_sources.jsonl"
    merged = merge_by_round(read_jsonl(manifest), records)
    write_jsonl(manifest, merged)
    observations = {
        int(record["round"]): record for record in read_jsonl(args.context_dir / "observations.jsonl")
    }
    queue_records = []
    for record in merged:
        queue_record = dict(record)
        if record["round"] in observations:
            queue_record["review_status"] = observations[record["round"]]["review_status"]
        queue_records.append(queue_record)
    write_review_queue(args.context_dir / "review_queue.csv", queue_records)
    verified_count = sum(bool(record["source_verified"]) for record in records)
    print(f"discovered={len(records)} official_verified={verified_count} manifest={manifest}")


def command_discover_rounds(args: argparse.Namespace) -> None:
    retrieved = utc_now()
    records = []
    missing = []
    for round_number in range(args.max_round, args.min_round - 1, -1):
        verified = []
        reuploads = []
        for record in discover_exact_round(round_number, retrieved):
            try:
                candidate = verify_youtube_source(record)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if candidate["source_verified"]:
                verified.append(candidate)
            elif (
                args.allow_reuploads
                and candidate.get("metadata_round_verified")
                and (args.reupload_channel is None or candidate.get("source_channel") == args.reupload_channel)
            ):
                reuploads.append(candidate)
        if verified:
            records.append(verified[0])
        elif reuploads:
            records.append(reuploads[0])
        else:
            missing.append(round_number)

    manifest = args.context_dir / "video_sources.jsonl"
    merged = merge_by_round(read_jsonl(manifest), records)
    write_jsonl(manifest, merged)
    observations = {
        int(record["round"]): record for record in read_jsonl(args.context_dir / "observations.jsonl")
    }
    queue_records = []
    for record in merged:
        queue_record = dict(record)
        if record["round"] in observations:
            queue_record["review_status"] = observations[record["round"]]["review_status"]
        queue_records.append(queue_record)
    write_review_queue(args.context_dir / "review_queue.csv", queue_records)
    print(
        f"requested={args.max_round - args.min_round + 1} discovered={len(records)} "
        f"missing={missing} manifest={manifest}"
    )


def command_annotate(args: argparse.Namespace) -> None:
    manifest = args.context_dir / "video_sources.jsonl"
    sources = {int(record["round"]): record for record in read_jsonl(manifest)}
    source = sources.get(args.round)
    if source is None:
        raise ValueError(f"Round {args.round} is not present in the video-source manifest")
    draws = {draw.round: draw for draw in load_draws(args.data_dir)}
    draw = draws.get(args.round)
    if draw is None:
        raise ValueError(f"Official draw data is missing for round {args.round}")
    observation = build_observation(
        source=source,
        draw=draw,
        ordered_numbers=parse_number_list(args.order),
        bonus_number=args.bonus,
        result_offset=args.result_offset,
        machine_id=args.machine_id,
        ball_set_id=args.ball_set_id,
        notes=args.notes,
        review_method=args.review_method,
    )
    path = args.context_dir / "observations.jsonl"
    observations = replace_by_round(read_jsonl(path), [observation])
    write_jsonl(path, observations)
    statuses = {int(record["round"]): record["review_status"] for record in observations}
    queue_records = []
    for source_record in sources.values():
        queue_record = dict(source_record)
        if source_record["round"] in statuses:
            queue_record["review_status"] = statuses[source_record["round"]]
        queue_records.append(queue_record)
    write_review_queue(args.context_dir / "review_queue.csv", queue_records)
    print(f"verified round={args.round} order={observation['ordered_numbers']} observations={path}")


def import_reviewed_batch(
    batch: dict[str, Any], sources: dict[int, dict[str, Any]], draws: dict[int, Draw]
) -> list[dict[str, Any]]:
    rows = batch.get("reviewed_rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Reviewed batch requires a non-empty reviewed_rows list")
    rejected_rows = batch.get("rejected_rows", [])
    if not isinstance(rejected_rows, list):
        raise ValueError("Rejected batch rows must be a list")
    declared_rounds = [int(value) for value in batch.get("rounds", [])]
    row_rounds = [int(row["round"]) for row in rows]
    rejected_rounds = [int(row["round"]) for row in rejected_rows]
    if len(row_rounds) != len(set(row_rounds)):
        raise ValueError("Reviewed batch contains duplicate rounds")
    if len(rejected_rounds) != len(set(rejected_rounds)):
        raise ValueError("Rejected batch contains duplicate rounds")
    if set(row_rounds) & set(rejected_rounds):
        raise ValueError("A batch round cannot be both reviewed and rejected")
    if set(row_rounds) | set(rejected_rounds) != set(declared_rounds):
        raise ValueError("Reviewed and rejected rows must exactly match the batch round selection")
    for rejected in rejected_rows:
        reason = rejected.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Rejected batch rows require a non-empty reason")

    observations = []
    notes_by_method = batch.get("evidence_notes_by_method", {})
    for row in rows:
        round_number = int(row["round"])
        source = sources.get(round_number)
        draw = draws.get(round_number)
        if source is None or draw is None:
            raise ValueError(f"Missing source or official draw for round {round_number}")
        observations.append(
            build_observation(
                source=source,
                draw=draw,
                ordered_numbers=parse_number_list(row["order"]),
                bonus_number=int(row["bonus"]),
                result_offset=row.get("result_offset"),
                machine_id=row.get("machine_id"),
                ball_set_id=row.get("ball_set_id"),
                notes=row.get("notes") or notes_by_method.get(row.get("review_method")),
                review_method=row.get("review_method", "manual_video_review"),
                content_verification=row.get("content_verification"),
            )
        )
    return observations


def command_import_batch(args: argparse.Namespace) -> None:
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    manifest = args.context_dir / "video_sources.jsonl"
    sources = {int(record["round"]): record for record in read_jsonl(manifest)}
    draws = {draw.round: draw for draw in load_draws(args.data_dir)}
    incoming = import_reviewed_batch(batch, sources, draws)

    path = args.context_dir / "observations.jsonl"
    observations = replace_by_round(read_jsonl(path), incoming)
    write_jsonl(path, observations)
    statuses = {int(record["round"]): record["review_status"] for record in observations}
    queue_records = []
    for source_record in sources.values():
        queue_record = dict(source_record)
        if source_record["round"] in statuses:
            queue_record["review_status"] = statuses[source_record["round"]]
        queue_records.append(queue_record)
    write_review_queue(args.context_dir / "review_queue.csv", queue_records)
    print(f"imported={len(incoming)} observations_total={len(observations)} observations={path}")


def command_audit(args: argparse.Namespace) -> None:
    observations = read_jsonl(args.context_dir / "observations.jsonl")
    report = audit_records(observations, args.minimum_sample)
    path = args.context_dir / "coverage_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    commands = parser.add_subparsers(dest="command", required=True)

    discover = commands.add_parser("discover", help="discover and verify official draw-video sources")
    discover.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    discover.add_argument("--min-round", type=int)
    discover.add_argument("--max-round", type=int)
    discover.add_argument("--skip-oembed", action="store_true")
    discover.set_defaults(handler=command_discover)

    channel = commands.add_parser(
        "discover-channel", help="discover older draw videos through the official channel search"
    )
    channel.add_argument("--query", default="로또6/45 당첨번호")
    channel.add_argument("--pages", type=int, default=8)
    channel.add_argument("--min-round", type=int)
    channel.add_argument("--max-round", type=int)
    channel.set_defaults(handler=command_discover_channel)

    rounds = commands.add_parser(
        "discover-rounds", help="discover exact older rounds through general YouTube search"
    )
    rounds.add_argument("--min-round", type=int, required=True)
    rounds.add_argument("--max-round", type=int, required=True)
    rounds.add_argument("--allow-reuploads", action="store_true")
    rounds.add_argument("--reupload-channel")
    rounds.set_defaults(handler=command_discover_rounds)

    annotate = commands.add_parser("annotate", help="store one manually reviewed draw observation")
    annotate.add_argument("--round", type=int, required=True)
    annotate.add_argument("--order", required=True, help="six numbers in extraction order")
    annotate.add_argument("--bonus", type=int, required=True)
    annotate.add_argument("--result-offset", type=float)
    annotate.add_argument(
        "--review-method",
        choices=["manual_video_review", "manual_official_thumbnail_review"],
        default="manual_video_review",
    )
    annotate.add_argument("--machine-id")
    annotate.add_argument("--ball-set-id")
    annotate.add_argument("--notes")
    annotate.set_defaults(handler=command_annotate)

    import_batch = commands.add_parser(
        "import-batch", help="atomically validate and import a preselected reviewed batch"
    )
    import_batch.add_argument("--batch", type=Path, required=True)
    import_batch.set_defaults(handler=command_import_batch)

    audit = commands.add_parser("audit", help="report coverage and conditional-model gates")
    audit.add_argument("--minimum-sample", type=int, default=DEFAULT_MIN_SAMPLE)
    audit.set_defaults(handler=command_audit)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
