#!/usr/bin/env python3
"""Read-only live probes of data commands. Never imports or runs strategies.

Each probe runs in a subprocess with a hard deadline. A zero exit status alone
does not mean success: JSON, errors, empty collections and event counts are checked.
Raw stdout/stderr are retained alongside the machine-readable summary.
"""
import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent


def probes():
    # Use a weekday explicitly for date-specific feeds; holidays can still be empty.
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    date = day.strftime("%Y%m%d")
    start = (day - timedelta(days=14)).strftime("%Y%m%d")
    result = []

    def add(name, script, *args):
        result.append((name, script, list(args) + ["--json"]))

    rt, hist, dang = "fetch_realtime.py", "fetch_history.py", "fetch_danginvest.py"
    add("quote", rt, "--quote", "600519")
    add("multi_quote", rt, "--multi-quote", "600519,000001,300750")
    for freq in ("1d", "5m", "1w", "1M"):
        add("kline_" + freq, rt, "--kline", "600519", "--freq", freq, "--count", "10")
    add("intraday", rt, "--intraday-kline", "600519", "--freq", "5m")
    add("index", rt, "--index")
    add("north_money", rt, "--north-money")
    add("lhb", rt, "--lhb", "--start", start, "--end", date, "--top", "3")
    add("limit_stats", rt, "--limit-stats")
    add("limit_up", rt, "--limit-up-pool", "--date", date, "--top", "3")
    add("consecutive_limit", rt, "--consecutive-limit", "--date", date, "--top", "3")
    add("fund_flow", rt, "--fund-flow", "600519", "--days", "3")
    add("tick", rt, "--tick", "600519", "--top", "3")
    add("all_quote", rt, "--all-quote", "--top", "3")
    add("history", hist, "--kline", "600519", "--count", "10")
    add("history_batch", hist, "--kline-batch", "600519,000001,300750", "--count", "10", "--retries", "0")
    add("basic", hist, "--basic", "600519")
    add("industry", hist, "--industry", "600519")
    add("all_stocks", hist, "--all-stocks")
    add("trade_dates", hist, "--trade-dates", "--start", "2026-01-01", "--end", "2026-12-31")
    for index in ("hs300", "sz50", "zz500"):
        add(index, hist, "--" + index)
    add("dividend", hist, "--dividend", "600519", "--year", "2025")
    for key in ("financials", "profit", "growth", "balance", "cashflow", "dupont", "perf-forecast", "perf-express"):
        add(key, hist, "--" + key, "600519")
    for key in ("deposit-rate", "loan-rate", "reserve-ratio", "money-supply"):
        add(key, hist, "--" + key)
    add("technical", "fetch_technical.py", "600519", "--count", "120", "--no-signal")
    add("events", "fetch_stock_events.py", "--code", "300476", "--name", "胜宏科技", "--limit", "5", "--max-seconds", "20")
    add("ah_stocks", "fetch_ah_stocks.py", "--workers", "4", "--no-cache")
    add("ah_timeline", "fetch_ah_ipo_timeline.py", "--code", "002352")
    add("sector", "fetch_sector_info.py", "--no-concepts", "--timeout", "5", "600519")
    add("market_news", dang, "--news", "--limit", "5", "--retries", "0")
    for mode in ("major", "sub", "concept"):
        add("boards_" + mode, dang, "--summary", "--mode", mode, "--limit", "3", "--retries", "0")
    # A stable documented example; a bad group key is distinguishable in raw output.
    add("board_detail", dang, "--detail", "--mode", "sub", "--group-key", "半导体", "--items-limit", "3", "--retries", "0")
    if (SCRIPTS / "fetch_company_news.py").exists():
        add("company_news", "fetch_company_news.py", "--code", "300476", "--name", "胜宏科技", "--days", "30", "--limit", "5")
    return result


def assess(value):
    if value is None or value == [] or value == {}:
        return "empty", 0
    if isinstance(value, list):
        errors = [v for v in value if isinstance(v, dict) and
                  (v.get("error") or v.get("ok") is False or v.get("profile_error") or
                   v.get("状态", "成功") != "成功")]
        return ("error" if len(errors) == len(value) else "partial" if errors else "ok"), len(value)
    if not isinstance(value, dict):
        return "invalid_payload", 0
    if value.get("error"):
        return "error", 0
    if "performance" in value:
        count = sum(value.get(k, {}).get("count", 0) for k in
                    ("performance", "holder_change_buyback", "regulatory", "major_contracts", "sentiment"))
        return ("ok" if count else "empty"), count
    for key in ("data", "results", "items"):
        if key in value:
            status, count = assess(value[key])
            meta = value.get("meta", {})
            if meta.get("failed") or meta.get("fail") or meta.get("failed_codes") or meta.get("errors") or value.get("errors"):
                status = "partial" if count else "error"
            if value.get("status") in ("unavailable", "partial", "empty"):
                status = value["status"]
            return status, count
    if value.get("success") is False or value.get("status") == "error":
        return "error", 0
    return "ok", 1


def quality_findings(name, value):
    """Check data semantics separately from transport success."""
    findings = []
    if isinstance(value, dict):
        meta = value.get("meta", {})
        if meta.get("stale") is True:
            findings.append("stale: upstream snapshot or feed is outdated")
        if name == "events":
            info = value.get("recent_information", {})
            if info.get("status") in ("partial", "unavailable"):
                findings.append("partial: recent company information has source failures")
        value = value.get("data", value)
    if name == "market_news" and isinstance(value, list):
        stamps = []
        for item in value:
            try:
                stamp = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
                stamps.append(stamp.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if stamp.tzinfo is None else stamp)
            except (KeyError, ValueError, TypeError):
                pass
        if stamps and (datetime.now(ZoneInfo("Asia/Shanghai")) - max(stamps)).total_seconds() > 86400:
            findings.append("stale: newest news in page is over 24 hours old")
    if name == "north_money" and isinstance(value, list) and value and all(
            r.get("净买额(亿)") == 0 and r.get("净流入(亿)") == 0 for r in value):
        findings.append("needs_review: all northbound flow fields are zero; may be upstream placeholders")
    if name == "limit_stats" and datetime.now(ZoneInfo("Asia/Shanghai")).weekday() >= 5:
        findings.append("needs_review: a weekend request is labeled today; underlying trading date is unverified")
    if name == "technical" and isinstance(value, list):
        invalid = [r for r in value if all(isinstance(r.get(k), (int, float)) for k in ("open", "close", "high", "low"))
                   and (r["high"] < max(r["open"], r["close"], r["low"]) or r["low"] > min(r["open"], r["close"]))]
        if invalid:
            findings.append(f"quality_error: {len(invalid)} OHLC bars violate price bounds")
    return findings


def run_probe(probe, timeout, output):
    name, script, args = probe
    cmd = [sys.executable, str(SCRIPTS / script)] + args
    started = time.monotonic()
    env = dict(os.environ, PYTHONWARNINGS="ignore", TQDM_DISABLE="1")
    findings = []
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        try:
            value = json.loads(stdout)
            status, count = assess(value)
            findings = quality_findings(name, value)
            if status == "ok" and findings:
                status = findings[0].split(":")[0]
        except (ValueError, TypeError):
            status, count = "non_json", 0
        if code:
            status = "error"
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, code, status, count = exc.stdout or "", exc.stderr or "", None, "timeout", 0
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
    (output / (name + ".stdout")).write_text(stdout, encoding="utf-8")
    (output / (name + ".stderr")).write_text(stderr, encoding="utf-8")
    return {"name": name, "status": status, "records": count, "exit_code": code,
            "elapsed_sec": round(time.monotonic() - started, 2), "command": shlex.join(cmd),
            "findings": findings, "preview": stdout[:350], "stderr_tail": stderr[-350:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="/tmp/a-share-health")
    parser.add_argument("--only", help="Comma-separated probe names")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=35)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    selected = set(args.only.split(",")) if args.only else None
    checks = [p for p in probes() if selected is None or p[0] in selected]
    if not checks or selected and selected - {p[0] for p in checks}:
        parser.error("Unknown or empty probe selection")
    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        tasks = [pool.submit(run_probe, p, args.timeout, output) for p in checks]
        for future in as_completed(tasks):
            row = future.result()
            results.append(row)
            print(f"{row['name']}: {row['status']} ({row['records']} records, {row['elapsed_sec']}s)", flush=True)
    results.sort(key=lambda r: r["name"])
    payload = {"checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
               "python": sys.version, "platform": platform.platform(),
               "elapsed_sec": round(time.monotonic() - started, 2),
               "summary": dict(Counter(r["status"] for r in results)), "checks": results}
    (output / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
