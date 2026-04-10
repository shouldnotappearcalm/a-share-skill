#!/usr/bin/env python3
"""
fetch_history 统一入口（已切换为 fallback 逻辑）。
兼容旧参数后转发到 fetch_history_fallback.py。
"""

import os
import sys


def _consume_option(args, key):
    if key not in args:
        return None
    idx = args.index(key)
    if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
        value = args[idx + 1]
        del args[idx:idx + 2]
        return value
    del args[idx]
    return None


def _normalize_argv(argv):
    args = list(argv)

    freq = _consume_option(args, "--freq")
    if freq:
        freq_map = {"d": "1d", "w": "1w", "m": "1M", "1d": "1d", "1w": "1w", "1M": "1M"}
        mapped = freq_map.get(freq)
        if mapped is None:
            print(f"当前历史脚本不支持频率 {freq}，仅支持 d/w/m（或 1d/1w/1M）")
            sys.exit(1)
        args.extend(["--freq", mapped])

    limit = _consume_option(args, "--limit")
    if limit and "--count" not in args:
        args.extend(["--count", limit])

    _consume_option(args, "--adjust")

    if "--operation" in args:
        print("当前历史脚本不再支持 --operation，请改用 --financials 或 --profit")
        sys.exit(1)

    if "--industry" in args:
        idx = args.index("--industry")
        next_token = args[idx + 1] if idx + 1 < len(args) else None
        if next_token and not next_token.startswith("--"):
            pass
        else:
            code = _consume_option(args, "--code")
            if code:
                args[idx:idx + 1] = ["--industry", code]
            else:
                print("当前历史脚本请使用 --industry <股票代码> 查询行业")
                sys.exit(1)
    else:
        _consume_option(args, "--code")

    _consume_option(args, "--date")
    _consume_option(args, "--period")
    return args


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    from fetch_history_fallback import main as fallback_main

    normalized = _normalize_argv(sys.argv[1:])
    sys.argv = [sys.argv[0]] + normalized
    fallback_main()


if __name__ == "__main__":
    main()
