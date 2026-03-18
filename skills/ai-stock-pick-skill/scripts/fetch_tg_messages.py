#!/usr/bin/env python3

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:
    print("缺少依赖：请先安装 `pip install requests`", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("缺少依赖：请先安装 `pip install beautifulsoup4`", file=sys.stderr)
    sys.exit(1)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
}


ISO_Z_RE = re.compile(r"Z$")
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class TgMessage:
    message_id: str
    published_at: datetime
    text: str
    link: str
    views: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "published_at": self.published_at.isoformat(),
            "text": self.text,
            "link": self.link,
            "views": self.views,
        }


def parse_datetime(value: str, tz: ZoneInfo, *, is_end: bool) -> datetime:
    v = value.strip()
    if DATE_ONLY_RE.match(v):
        day_dt = datetime.strptime(v, "%Y-%m-%d")
        if is_end:
            return datetime(day_dt.year, day_dt.month, day_dt.day, 23, 59, 59, 999999, tzinfo=tz)
        return datetime(day_dt.year, day_dt.month, day_dt.day, 0, 0, 0, 0, tzinfo=tz)

    if ISO_Z_RE.search(v):
        v = v[:-1] + "+00:00"

    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def clean_text(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = WS_RE.sub(" ", s).strip()
    return s


def extract_message_id(data_post: str) -> Optional[str]:
    if not data_post:
        return None
    parts = data_post.split("/")
    if len(parts) == 2 and parts[1].isdigit():
        return parts[1]
    if parts[-1].isdigit():
        return parts[-1]
    return None


def extract_message_id_from_wrap(wrap: Any) -> Optional[str]:
    data_post = wrap.get("data-post")
    message_id = extract_message_id(data_post) if data_post else None
    if message_id:
        return message_id

    date_link = wrap.select_one("a.tgme_widget_message_date[href]")
    if date_link is not None:
        href = date_link.get("href", "")
        m = re.search(r"/(\d+)(?:\?|$)", href)
        if m:
            return m.group(1)
    return None


def parse_message_wrap(channel: str, wrap: Any) -> Optional[TgMessage]:
    message_id = extract_message_id_from_wrap(wrap)
    if not message_id:
        return None

    time_tag = wrap.find("time")
    published_at: Optional[datetime] = None
    if time_tag is not None:
        dt_str = time_tag.get("datetime")
        if dt_str:
            published_at = parse_datetime(dt_str, ZoneInfo("UTC"), is_end=False)

    if published_at is None:
        return None

    msg_text_el = wrap.select_one(".tgme_widget_message_text")
    if msg_text_el is None:
        msg_text_el = wrap

    text = clean_text(msg_text_el.get_text(" ", strip=True))

    views: Optional[int] = None
    views_el = wrap.select_one(".tgme_widget_message_views")
    if views_el is not None:
        m = re.search(r"\d+", views_el.get_text())
        if m:
            views = int(m.group(0))

    link = f"https://t.me/{channel}/{message_id}"
    return TgMessage(
        message_id=message_id,
        published_at=published_at,
        text=text,
        link=link,
        views=views,
    )


def fetch_page(base_url: str, before_id: Optional[str], *, timeout_s: int) -> Tuple[List[TgMessage], Optional[str]]:
    url = base_url
    if before_id:
        url = f"{base_url}?before={before_id}"

    resp = requests.get(url, headers=HEADERS, timeout=timeout_s)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    wraps = soup.select("div.tgme_widget_message_wrap")
    if not wraps:
        wraps = soup.select("[data-post]")

    messages: List[TgMessage] = []
    oldest_id: Optional[str] = None
    channel = channel_from_base(base_url)

    for wrap in wraps:
        candidate_id = extract_message_id_from_wrap(wrap)
        if candidate_id:
            oldest_id = candidate_id

        msg = parse_message_wrap(channel=channel, wrap=wrap)
        if msg is not None:
            messages.append(msg)

    next_before = oldest_id
    return messages, next_before


def channel_from_base(base_url: str) -> str:
    # base_url: https://t.me/s/<channel>
    return base_url.rstrip("/").split("/")[-1]


def filter_and_collect(
    channel: str,
    start_dt: datetime,
    end_dt: datetime,
    *,
    limit: int,
    max_pages: int,
    timeout_s: int,
) -> List[TgMessage]:
    base_url = f"https://t.me/s/{channel}"

    collected: List[TgMessage] = []
    before_id: Optional[str] = None

    last_before_seen: Optional[str] = None

    for _ in range(max_pages):
        messages, page_oldest_id = fetch_page(base_url, before_id, timeout_s=timeout_s)
        if not messages:
            break

        if page_oldest_id is None:
            break

        if before_id == last_before_seen and len(messages) == 0:
            break

        for msg in messages:
            if msg.published_at < start_dt:
                continue
            if msg.published_at > end_dt:
                continue
            collected.append(msg)
            if len(collected) >= limit:
                break

        if len(collected) >= limit:
            break

        # 如果这一页已经包含了比 start_dt 更旧的消息，那么下一页也只会更旧，可以提前结束。
        oldest_in_page = min(m.published_at for m in messages)
        if oldest_in_page < start_dt:
            break

        last_before_seen = before_id
        before_id = page_oldest_id

    collected.sort(key=lambda m: m.published_at)
    return collected


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 Telegram 公开频道指定时间范围内的消息（基于 https://t.me/s/ 公开页面）。")
    parser.add_argument("--channel", default="AI_News_CN", help="Telegram 频道名，不带 @，例如 AI_News_CN")
    parser.add_argument("--start", required=True, help="开始时间，YYYY-MM-DD 或 ISO 8601，例如 2026-03-18 或 2026-03-18T00:00:00+08:00")
    parser.add_argument("--end", required=True, help="结束时间，YYYY-MM-DD 或 ISO 8601，例如 2026-03-19 或 2026-03-19T23:59:59+08:00")
    parser.add_argument("--tz", default="Asia/Shanghai", help="当时间字符串不带时区时采用的时区，默认 Asia/Shanghai")
    parser.add_argument("--limit", type=int, default=200, help="最多返回多少条消息，默认 200")
    parser.add_argument("--max-pages", type=int, default=20, help="最多翻页多少次，默认 20")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP 超时时间，默认 20 秒")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    try:
        tz = ZoneInfo(args.tz)
    except Exception:
        print(f"时区无效：{args.tz}", file=sys.stderr)
        sys.exit(1)

    try:
        start_dt = parse_datetime(args.start, tz, is_end=False)
        end_dt = parse_datetime(args.end, tz, is_end=True)
    except ValueError as e:
        print(f"时间解析失败：{e}", file=sys.stderr)
        sys.exit(1)

    # 页面中的 time datetime 由 HTML 提供，通常带时区。这里统一转成 UTC 方便过滤。
    start_dt_utc = start_dt.astimezone(ZoneInfo("UTC"))
    end_dt_utc = end_dt.astimezone(ZoneInfo("UTC"))

    # 解析消息时使用 UTC 作为基准
    messages = filter_and_collect(
        channel=args.channel,
        start_dt=start_dt_utc,
        end_dt=end_dt_utc,
        limit=args.limit,
        max_pages=args.max_pages,
        timeout_s=args.timeout,
    )

    payload = {
        "channel": args.channel,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "count": len(messages),
        "messages": [m.to_dict() for m in messages],
        "fetched_at": datetime.now(tz).isoformat(),
        "source": f"https://t.me/s/{args.channel}",
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"抓取 {payload['count']} 条消息：{payload['source']}")
    for m in payload["messages"]:
        print("-" * 60)
        print(m["published_at"], m["link"])
        print(m["text"])


if __name__ == "__main__":
    main()

