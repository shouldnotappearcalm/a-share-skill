#!/usr/bin/env python3
"""
个股板块信息查询脚本
数据源：东方财富 HTTP API

功能：
- 查询单只/多只股票所属的行业板块
- 查询单只/多只股票所属的概念板块
- 默认并行查询，速度快

依赖安装：pip install requests

用法示例：
  python3 fetch_sector_info.py 600519
  python3 fetch_sector_info.py 600519 000001 300750
  python3 fetch_sector_info.py 600519,000001,300750
  python3 fetch_sector_info.py --json 600519 000001
  python3 fetch_sector_info.py --batch-test
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# 全局共享 Session（连接池复用，提高并发性能）
_SHARED_SESSION = None

# 默认并发数（经过测试，8是较好的平衡点）
DEFAULT_WORKERS = 8


def _get_shared_session() -> requests.Session:
    """获取全局共享的 Session"""
    global _SHARED_SESSION
    if _SHARED_SESSION is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Connection": "keep-alive",
        })
        
        retry = Retry(
            total=3,
            connect=2,
            read=2,
            backoff_factor=0.2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        # 连接池大小与并发数匹配
        adapter = HTTPAdapter(max_retries=retry, pool_connections=DEFAULT_WORKERS, pool_maxsize=DEFAULT_WORKERS)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        _SHARED_SESSION = session
    return _SHARED_SESSION


def normalize_code(code: str) -> tuple:
    """标准化股票代码，返回 (市场代码, 纯代码)"""
    code = code.strip()
    if code.lower().startswith("sh"):
        return ("1", code[2:].zfill(6))
    elif code.lower().startswith("sz"):
        return ("0", code[2:].zfill(6))
    elif code.startswith("6"):
        return ("1", code.zfill(6))
    elif code.startswith(("0", "2", "3")):
        return ("0", code.zfill(6))
    elif "." in code:
        parts = code.split(".")
        if len(parts) == 2:
            if parts[0].upper() == "XSHG" or parts[1].upper() == "SH":
                return ("1", parts[1].zfill(6) if parts[1].isdigit() else parts[0].zfill(6))
            elif parts[0].upper() == "XSHE" or parts[1].upper() == "SZ":
                return ("0", parts[1].zfill(6) if parts[1].isdigit() else parts[0].zfill(6))
    return (None, code.zfill(6))


def get_sector_info_http(code6: str, market: str, timeout: int = 8, include_concepts: bool = True, retries: int = 2) -> Dict:
    """通过东方财富 HTTP API 获取个股板块信息"""
    result = {
        "code": code6,
        "name": None,
        "industry": None,
        "concepts": [],
        "source": "eastmoney",
        "error": None,
    }
    
    if market is None:
        market = "1" if code6.startswith("6") else "0"
    
    session = _get_shared_session()
    secid = f"{market}.{code6}"
    
    # 接口1：个股基本信息（名称 + 行业）
    for attempt in range(retries + 1):
        try:
            url = "https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                "secid": secid,
                "fields": "f57,f58,f127",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            }
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("data"):
                result["name"] = data["data"].get("f58")
                result["industry"] = data["data"].get("f127")
                if result["name"] or result["industry"]:
                    break
        except Exception as e:
            result["error"] = str(e)
            if attempt < retries:
                time.sleep(0.2 * (attempt + 1))
    
    # 接口2：获取概念板块（可选）
    if include_concepts:
        for attempt in range(retries + 1):
            try:
                url2 = "https://push2.eastmoney.com/api/qt/slist/get"
                params2 = {
                    "secid": secid,
                    "fields": "f12,f14",
                    "spt": "3",
                    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                }
                resp2 = session.get(url2, params=params2, timeout=timeout)
                resp2.raise_for_status()
                data2 = resp2.json()
                
                if data2.get("data") and data2["data"].get("diff"):
                    for item in data2["data"]["diff"]:
                        name = item.get("f14", "")
                        if name and name not in result["concepts"]:
                            result["concepts"].append(name)
                break
            except Exception:
                if attempt < retries:
                    time.sleep(0.1 * (attempt + 1))
    
    return result


def get_sector_info(code: str, timeout: int = 8, include_concepts: bool = True) -> Dict:
    """获取个股板块信息"""
    market, code6 = normalize_code(code)
    return get_sector_info_http(code6, market, timeout, include_concepts)


def batch_get_sector_info(codes: List[str], timeout: int = 8, max_workers: int = DEFAULT_WORKERS, include_concepts: bool = True) -> List[Dict]:
    """批量并行获取多只股票的板块信息"""
    if not codes:
        return []
    
    # 单只股票直接查询
    if len(codes) == 1:
        return [get_sector_info(codes[0], timeout, include_concepts)]
    
    # 多只股票并行查询
    results = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(codes))) as executor:
        future_to_code = {
            executor.submit(get_sector_info, code, timeout, include_concepts): code
            for code in codes
        }
        
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append({
                    "code": code,
                    "name": None,
                    "industry": None,
                    "concepts": [],
                    "source": "error",
                    "error": str(e),
                })
    
    # 按原始顺序排序
    code_order = {c: i for i, c in enumerate(codes)}
    results.sort(key=lambda x: code_order.get(x.get("code", ""), 999))
    
    return results


def print_single_result(result: Dict, output_json: bool = False):
    """打印单个股票的板块信息"""
    if output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    code = result.get("code", "N/A")
    name = result.get("name") or "未知"
    industry = result.get("industry") or "未知"
    concepts = result.get("concepts", [])
    source = result.get("source", "未知")
    error = result.get("error")
    
    print(f"{'='*60}")
    print(f"  代码: {code}")
    print(f"  名称: {name}")
    print(f"  行业: {industry}")
    print(f"  概念板块 ({len(concepts)}个):")
    if concepts:
        for i, concept in enumerate(concepts, 1):
            print(f"    {i}. {concept}")
    else:
        print("    (暂无)")
    print(f"  数据源: {source}")
    if error:
        print(f"  错误: {error}")
    print(f"{'='*60}")


def print_batch_results(results: List[Dict], output_json: bool = False, show_elapsed: float = None):
    """打印批量查询结果"""
    if output_json:
        output = {"data": results}
        if show_elapsed is not None:
            output["elapsed_seconds"] = round(show_elapsed, 2)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    
    print(f"\n{'='*80}")
    print(f"{'代码':<10} {'名称':<12} {'行业':<15} {'概念数':<6} {'数据源':<10}")
    print(f"{'-'*80}")
    
    success_count = 0
    for r in results:
        code = r.get("code", "N/A")
        name = r.get("name") or "未知"
        industry = r.get("industry") or "未知"
        concept_count = len(r.get("concepts", []))
        source = r.get("source", "未知")
        
        is_success = bool(r.get("name") or r.get("industry"))
        status = "✓" if is_success else "✗"
        print(f"{code:<10} {name:<12} {industry:<15} {concept_count:<6} {source:<10} {status}")
        if is_success:
            success_count += 1
    
    print(f"{'-'*80}")
    print(f"总计: {len(results)} 只, 成功: {success_count} 只, 失败: {len(results) - success_count} 只", end="")
    if show_elapsed is not None:
        print(f", 耗时: {show_elapsed:.2f}秒")
    else:
        print()
    print(f"{'='*80}\n")


# 内置测试股票代码（沪深40只，覆盖各行业和板块）
TEST_CODES = [
    # 沪市主板 - 金融
    "600519", "601318", "600036", "601166", "601398", "601288", "600000", "601939", "601988", "600030",
    "601211",
    # 沪市主板 - 消费/医药/能源
    "600276", "600887", "601888", "600900", "601012", "600309", "601899", "600585", "600104",
    # 深市主板
    "000001", "000002", "000333", "000651", "000858", "000568", "000538", "000063",
    # 创业板
    "300750", "300059", "300015", "300014", "300274", "300124", "300033", "300498",
    # 科创板
    "688981", "688599", "688111",
]


def run_batch_test(max_workers: int = DEFAULT_WORKERS, include_concepts: bool = True) -> bool:
    """运行批量测试"""
    test_codes = list(dict.fromkeys(TEST_CODES))  # 去重
    
    print(f"\n{'='*60}")
    print(f"  批量测试: {len(test_codes)} 只股票")
    print(f"  并发数: {max_workers}")
    print(f"{'='*60}")
    
    start_time = time.time()
    results = batch_get_sector_info(test_codes, timeout=8, max_workers=max_workers, include_concepts=include_concepts)
    elapsed = time.time() - start_time
    
    success_count = sum(1 for r in results if r.get("industry") or r.get("name"))
    fail_count = len(results) - success_count
    
    print_batch_results(results, show_elapsed=elapsed)
    
    if fail_count > 0:
        print(f"失败股票:")
        for r in results:
            if not (r.get("industry") or r.get("name")):
                print(f"  - {r.get('code')}: {r.get('error', '未知错误')}")
        return False
    
    return True


def parse_codes_from_args(args) -> List[str]:
    """从参数中解析股票代码列表"""
    codes = []
    
    # 从位置参数获取
    for code in args.codes:
        # 支持逗号分隔
        if ',' in code:
            codes.extend([c.strip() for c in code.split(',') if c.strip()])
        else:
            codes.append(code.strip())
    
    return codes


def main():
    parser = argparse.ArgumentParser(
        description="查询个股板块信息（行业 + 概念板块），默认并行查询",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 fetch_sector_info.py 600519                    # 单只股票
  python3 fetch_sector_info.py 600519 000001 300750     # 多只股票（并行）
  python3 fetch_sector_info.py 600519,000001,300750     # 逗号分隔
  python3 fetch_sector_info.py --json 600519 000001     # JSON输出
  python3 fetch_sector_info.py --batch-test             # 内置40只股票测试
  python3 fetch_sector_info.py --batch-test --workers 8 # 指定并发数
        """
    )
    
    parser.add_argument("codes", nargs="*", help="股票代码（支持多个，空格或逗号分隔）")
    parser.add_argument("--batch-test", action="store_true", help="使用内置40只股票进行批量测试")
    parser.add_argument("--timeout", type=int, default=8, help="单只股票查询超时（秒），默认8")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"并发数，默认{DEFAULT_WORKERS}")
    parser.add_argument("--no-concepts", action="store_true", help="不查询概念板块（更快）")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    
    args = parser.parse_args()
    include_concepts = not args.no_concepts
    
    # 批量测试模式
    if args.batch_test:
        success = run_batch_test(max_workers=args.workers, include_concepts=include_concepts)
        sys.exit(0 if success else 1)
    
    # 解析股票代码
    codes = parse_codes_from_args(args)
    
    if not codes:
        parser.print_help()
        sys.exit(1)
    
    # 并行查询
    start_time = time.time()
    results = batch_get_sector_info(codes, timeout=args.timeout, max_workers=args.workers, include_concepts=include_concepts)
    elapsed = time.time() - start_time
    
    # 输出结果
    if len(results) == 1:
        print_single_result(results[0], output_json=args.output_json)
    else:
        print_batch_results(results, output_json=args.output_json, show_elapsed=elapsed)
    
    # 退出码
    success = all(r.get("industry") or r.get("name") for r in results)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()