#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实盘分析工具 —— 从 real_orders 汇总到 real_order_analysis

用法:
  python3 analysis.py                          # 分析所有策略
  python3 analysis.py --strategy fast_range    # 指定策略
  python3 analysis.py --force                  # 强制重新汇总
"""
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_manager import init_database, run_analysis

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="实盘分析汇总工具")
    parser.add_argument("--strategy", "-s", help="策略名称, 不传则分析全部")
    parser.add_argument("--force", "-f", action="store_true", help="强制重新汇总")
    args = parser.parse_args()

    init_database()
    count = run_analysis(strategy_name=args.strategy, force=args.force)
    print(f"✅ 分析完成, 共写入 {count} 条记录")
    sys.exit(0)


if __name__ == "__main__":
    main()
