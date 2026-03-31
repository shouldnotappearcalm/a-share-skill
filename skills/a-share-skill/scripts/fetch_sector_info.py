#!/usr/bin/env python3
"""
个股板块信息查询脚本
数据源：东方财富 HTTP API

功能：
- 查询单只股票所属的行业板块
- 查询单只股票所属的概念板块
- 支持批量查询

依赖安装：pip install requests

用法示例：
  python3 fetch_sector_info.py --code 600519
  python3 fetch_sector_info.py --code 600519 --json
  python3 fetch_sector_info.py --codes 600519,000001,300750
  python3 fetch_sector_info.py --batch-test  # 使用内置40只股票测试
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import requests


def _build_session() -> requests.Session:
    """构建带重试机制的 HTTP Session"""
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    
    retry = Retry(
        total=3,
        connect=2,
        read=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def normalize_code(code: str) -> tuple:
    """
    标准化股票代码，返回 (市场代码, 纯代码)
    市场代码: 1=沪市, 0=深市
    """
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


def get_sector_info_http(code6: str, market: str, timeout: int = 10, include_concepts: bool = True, retries: int = 2) -> Dict:
    """
    通过东方财富 HTTP API 获取个股板块信息
    """
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
    
    session = _build_session()
    secid = f"{market}.{code6}"
    
    # 接口1：个股基本信息（名称 + 行业）- 带重试
    for attempt in range(retries + 1):
        try:
            url = "https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                "secid": secid,
                "fields": "f57,f58,f127",  # 代码、名称、行业
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            }
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("data"):
                result["name"] = data["data"].get("f58")
                result["industry"] = data["data"].get("f127")
                if result["name"] or result["industry"]:
                    break  # 成功获取数据，跳出重试循环
        except Exception as e:
            result["error"] = str(e)
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))  # 递增等待时间
    
    # 接口2：获取概念板块（可选）- 带重试
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
                break  # 成功，跳出重试循环
            except Exception:
                if attempt < retries:
                    time.sleep(0.3 * (attempt + 1))
    
    return result


def get_sector_info(code: str, timeout: int = 10, include_concepts: bool = True) -> Dict:
    """
    获取个股板块信息（主函数）
    """
    market, code6 = normalize_code(code)
    return get_sector_info_http(code6, market, timeout, include_concepts)


def batch_get_sector_info(codes: List[str], timeout: int = 10, max_workers: int = 5, include_concepts: bool = True) -> List[Dict]:
    """
    批量获取多只股票的板块信息
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
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


def print_batch_results(results: List[Dict], output_json: bool = False):
    """打印批量查询结果"""
    if output_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    
    print(f"\n{'='*80}")
    print(f"{'代码':<10} {'名称':<12} {'行业':<15} {'概念数量':<8} {'数据源':<10}")
    print(f"{'-'*80}")
    
    success_count = 0
    for r in results:
        code = r.get("code", "N/A")
        name = r.get("name") or "未知"
        industry = r.get("industry") or "未知"
        concept_count = len(r.get("concepts", []))
        source = r.get("source", "未知")
        error = r.get("error")
        
        # 判断成功：有名称或行业即可
        is_success = bool(r.get("name") or r.get("industry"))
        status = "✓" if is_success else "✗"
        print(f"{code:<10} {name:<12} {industry:<15} {concept_count:<8} {source:<10} {status}")
        if is_success:
            success_count += 1
    
    print(f"{'-'*80}")
    print(f"总计: {len(results)} 只, 成功: {success_count} 只, 失败: {len(results) - success_count} 只")
    print(f"{'='*80}\n")


# 内置测试股票代码（沪深40只，覆盖各行业和板块）
TEST_CODES = [
    # 沪市主板 - 金融
    "600519",  # 贵州茅台 - 白酒
    "601318",  # 中国平安 - 保险
    "600036",  # 招商银行 - 银行
    "601166",  # 兴业银行 - 银行
    "601398",  # 工商银行 - 银行
    "601288",  # 农业银行 - 银行
    "600000",  # 浦发银行 - 银行
    "601939",  # 建设银行 - 银行
    "601988",  # 中国银行 - 银行
    "600030",  # 中信证券 - 证券
    "601211",  # 国泰君安 - 证券
    # 沪市主板 - 消费/医药
    "600276",  # 恒瑞医药 - 医药
    "600887",  # 伊利股份 - 食品饮料
    "601888",  # 中国中免 - 免税
    # 沪市主板 - 能源/工业
    "600900",  # 长江电力 - 电力
    "601012",  # 隆基绿能 - 光伏
    "600309",  # 万华化学 - 化工
    "601899",  # 紫金矿业 - 有色金属
    "600585",  # 海螺水泥 - 水泥
    "600104",  # 上汽集团 - 汽车
    # 深市主板
    "000001",  # 平安银行 - 银行
    "000002",  # 万科A - 房地产
    "000333",  # 美的集团 - 家电
    "000651",  # 格力电器 - 家电
    "000858",  # 五粮液 - 白酒
    "000568",  # 泸州老窖 - 白酒
    "000538",  # 云南白药 - 中药
    "000063",  # 中兴通讯 - 通信
    # 创业板
    "300750",  # 宁德时代 - 电池
    "300059",  # 东方财富 - 证券
    "300015",  # 爱尔眼科 - 医疗服务
    "300014",  # 亿纬锂能 - 电池
    "300274",  # 阳光电源 - 光伏
    "300124",  # 汇川技术 - 工控
    "300033",  # 同花顺 - 金融IT
    "300498",  # 温氏股份 - 养殖
    # 科创板
    "688981",  # 中芯国际 - 半导体
    "688599",  # 天合光能 - 光伏
    "688111",  # 金山办公 - 软件
]


def run_batch_test(codes: List[str] = None, include_concepts: bool = True) -> bool:
    """
    运行批量测试
    返回: True 表示全部成功，False 表示有失败
    """
    test_codes = codes or TEST_CODES
    # 去重
    test_codes = list(dict.fromkeys(test_codes))
    
    print(f"\n开始测试 {len(test_codes)} 只股票的板块信息查询...")
    print(f"{'='*80}\n")
    
    start_time = time.time()
    results = batch_get_sector_info(test_codes, timeout=15, max_workers=3, include_concepts=include_concepts)
    elapsed = time.time() - start_time
    
    # 统计
    success_count = sum(1 for r in results if r.get("industry") or r.get("name"))
    fail_count = len(results) - success_count
    
    print_batch_results(results, output_json=False)
    
    print(f"耗时: {elapsed:.2f} 秒")
    print(f"成功率: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
    
    if fail_count > 0:
        print(f"\n失败股票:")
        for r in results:
            if not (r.get("industry") or r.get("name")):
                print(f"  - {r.get('code')}: {r.get('error', '未知错误')}")
        return False
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="查询个股板块信息（行业 + 概念板块）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 fetch_sector_info.py --code 600519
  python3 fetch_sector_info.py --code 600519 --json
  python3 fetch_sector_info.py --codes 600519,000001,300750
  python3 fetch_sector_info.py --batch-test
  python3 fetch_sector_info.py --batch-test --no-concepts
        """
    )
    
    parser.add_argument("--code", help="单只股票代码，如 600519 / sh600519")
    parser.add_argument("--codes", help="多只股票代码，逗号分隔")
    parser.add_argument("--batch-test", action="store_true", help="使用内置40只股票进行批量测试")
    parser.add_argument("--timeout", type=int, default=10, help="单只股票查询超时时间（秒），默认 10")
    parser.add_argument("--no-concepts", action="store_true", help="不查询概念板块（提高速度）")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    
    args = parser.parse_args()
    
    include_concepts = not args.no_concepts
    
    if args.batch_test:
        success = run_batch_test(include_concepts=include_concepts)
        sys.exit(0 if success else 1)
    
    if args.code:
        result = get_sector_info(args.code, timeout=args.timeout, include_concepts=include_concepts)
        print_single_result(result, output_json=args.output_json)
        sys.exit(0 if result.get("industry") or result.get("name") else 1)
    
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        results = batch_get_sector_info(codes, timeout=args.timeout, include_concepts=include_concepts)
        print_batch_results(results, output_json=args.output_json)
        success = all(r.get("industry") or r.get("name") for r in results)
        sys.exit(0 if success else 1)
    
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()