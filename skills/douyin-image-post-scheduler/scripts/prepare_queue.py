#!/usr/bin/env python3
"""Validate structured Douyin image-post assets and build a reproducible queue."""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


POST_DIR_RE = re.compile(r"^(\d{3})_")
IMAGE_PREFIX_RE = re.compile(r"^(\d+)_")
TAG_RE = re.compile(r"#[^\s#]+")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SENTENCE_ENDINGS = "。！？!?"


def parse_hhmm(value: str) -> int:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("时间必须使用 HH:MM 格式") from exc
    return parsed.hour * 60 + parsed.minute


def format_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def numeric_image_key(path: Path) -> tuple[int, str]:
    match = IMAGE_PREFIX_RE.match(path.stem)
    return (int(match.group(1)) if match else 10**9, path.name)


def title_from_first_image(path: Path) -> str:
    return IMAGE_PREFIX_RE.sub("", path.stem, count=1).strip()


def fit_body_to_topics(body: str, tags: list[str], body_limit: int) -> tuple[str, bool]:
    # Active topics add non-breaking spaces and line separators in Douyin's editor.
    topic_overhead = sum(len(tag) for tag in tags) + len(tags) * 4
    max_body = body_limit - 10 - topic_overhead
    if max_body <= 0:
        raise ValueError("标签占用空间超过正文限制")
    body = body.strip()
    if len(body) <= max_body:
        return body, False

    candidate = body[:max_body]
    sentence_index = max(candidate.rfind(mark) for mark in SENTENCE_ENDINGS)
    if sentence_index < math.floor(max_body * 0.65):
        sentence_index = candidate.rfind("\n")
    if sentence_index < 1:
        sentence_index = max_body - 1
    return candidate[: sentence_index + 1].rstrip(), True


def sample_day_times(
    rng: random.Random,
    window_start: int,
    window_end: int,
    count: int,
    min_gap: int,
) -> list[int]:
    if window_end <= window_start:
        raise ValueError("结束时间必须晚于开始时间")
    if count < 1:
        raise ValueError("每天发布条数必须大于 0")
    if (count - 1) * min_gap > window_end - window_start:
        raise ValueError("时间窗口无法容纳当前条数和最小间隔")

    population = range(window_start, window_end + 1)
    for _ in range(5000):
        values = sorted(rng.sample(population, count))
        if all(right - left >= min_gap for left, right in zip(values, values[1:])):
            return values
    raise RuntimeError("无法生成满足间隔要求的随机时间，请扩大时间窗口")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def collect_posts(args: argparse.Namespace) -> tuple[list[dict], list[str], list[str]]:
    post_dirs: list[tuple[int, Path]] = []
    for child in args.content_root.iterdir():
        if not child.is_dir():
            continue
        match = POST_DIR_RE.match(child.name)
        if match:
            number = int(match.group(1))
            if args.from_id <= number <= args.to_id:
                post_dirs.append((number, child))
    post_dirs.sort(key=lambda item: item[0])

    errors: list[str] = []
    warnings: list[str] = []
    posts: list[dict] = []
    for number, post_dir in post_dirs:
        image_dir = post_dir / "01_图片内容"
        body_path = post_dir / "02_文字内容.txt"
        source_title_path = post_dir / "03_标题内容.txt"
        tags_path = post_dir / "04_标签内容.txt"
        required = [image_dir, body_path, tags_path]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            errors.append(f"{post_dir.name}: 缺少 {', '.join(missing)}")
            continue

        images = sorted(
            (path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS),
            key=numeric_image_key,
        )
        if len(images) != args.image_count:
            errors.append(
                f"{post_dir.name}: 图片数量为 {len(images)}，预期 {args.image_count}"
            )
            continue

        title = title_from_first_image(images[0])
        if not title:
            errors.append(f"{post_dir.name}: 无法从第一张图片取得标题")
            continue
        if len(title) > args.title_limit:
            errors.append(
                f"{post_dir.name}: 第一张图片标题 {len(title)} 字，超过 {args.title_limit} 字"
            )
            continue

        tags = TAG_RE.findall(read_text(tags_path))[: args.max_tags]
        if len(tags) < args.max_tags:
            errors.append(
                f"{post_dir.name}: 仅找到 {len(tags)} 个标签，预期 {args.max_tags} 个"
            )
            continue

        body = read_text(body_path)
        try:
            body_excerpt, body_truncated = fit_body_to_topics(
                body, tags, args.body_limit
            )
        except ValueError as exc:
            errors.append(f"{post_dir.name}: {exc}")
            continue
        if body_truncated:
            warnings.append(
                f"{post_dir.name}: 正文从 {len(body)} 字按完整句子截断为 {len(body_excerpt)} 字"
            )

        posts.append(
            {
                "id": f"{number:03d}",
                "directory": str(post_dir.resolve()),
                "title": title,
                "source_title": read_text(source_title_path)
                if source_title_path.exists()
                else None,
                "body": body_excerpt,
                "body_truncated": body_truncated,
                "tags": tags,
                "images": [str(path.resolve()) for path in images],
            }
        )

    if not post_dirs:
        errors.append("没有找到以三位编号开头的内容目录")
    return posts, errors, warnings


def assign_schedule(args: argparse.Namespace, posts: list[dict], seed: int) -> None:
    rng = random.Random(seed)
    for day_index in range(math.ceil(len(posts) / args.posts_per_day)):
        start = day_index * args.posts_per_day
        day_posts = posts[start : start + args.posts_per_day]
        times = sample_day_times(
            rng,
            args.window_start,
            args.window_end,
            len(day_posts),
            args.min_gap_minutes,
        )
        publish_date = args.start_date + timedelta(days=day_index)
        for post, publish_minutes in zip(day_posts, times):
            post["schedule"] = f"{publish_date.isoformat()} {format_hhmm(publish_minutes)}"


def write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# 抖音图文发布排期",
        "",
        f"- 时区：{payload['timezone']}",
        f"- 每天：{payload['posts_per_day']} 条",
        f"- 随机种子：{payload['seed']}",
        "",
        "| 编号 | 发布时间 | 发布标题 |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {item['id']} | {item['schedule']} | {item['title']} |"
        for item in payload["items"]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="预检本地抖音图文素材并生成可复现的发布队列"
    )
    parser.add_argument("content_root", type=Path)
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--posts-per-day", type=int, default=3)
    parser.add_argument("--window-start", type=parse_hhmm, default=parse_hhmm("09:00"))
    parser.add_argument("--window-end", type=parse_hhmm, default=parse_hhmm("22:00"))
    parser.add_argument("--min-gap-minutes", type=int, default=90)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--from-id", type=int, default=0)
    parser.add_argument("--to-id", type=int, default=999)
    parser.add_argument("--image-count", type=int, default=8)
    parser.add_argument("--max-tags", type=int, default=5)
    parser.add_argument("--title-limit", type=int, default=20)
    parser.add_argument("--body-limit", type=int, default=1000)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.content_root = args.content_root.expanduser().resolve()
    if not args.content_root.is_dir():
        print(f"错误：素材目录不存在：{args.content_root}", file=sys.stderr)
        return 2

    posts, errors, warnings = collect_posts(args)
    if errors:
        for error in errors:
            print(f"错误：{error}", file=sys.stderr)
        return 2

    seed = args.seed if args.seed is not None else secrets.randbits(32)
    try:
        assign_schedule(args, posts, seed)
    except (ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    payload = {
        "content_root": str(args.content_root),
        "timezone": args.timezone,
        "posts_per_day": args.posts_per_day,
        "window": {
            "start": format_hhmm(args.window_start),
            "end": format_hhmm(args.window_end),
            "min_gap_minutes": args.min_gap_minutes,
        },
        "seed": seed,
        "defaults": {
            "visibility": "public",
            "allow_save": True,
            "cross_platform_sync": False,
            "music": "first_favorite",
        },
        "warnings": warnings,
        "items": posts,
    }

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown_output:
        write_markdown(args.markdown_output, payload)

    print(
        json.dumps(
            {
                "status": "ok",
                "items": len(posts),
                "seed": seed,
                "warnings": len(warnings),
                "json_output": str(args.json_output.resolve())
                if args.json_output
                else None,
                "markdown_output": str(args.markdown_output.resolve())
                if args.markdown_output
                else None,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
