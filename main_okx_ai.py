#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX AI策略启动器 — 基于 okx_top_value 评分数据"""
import sys
sys.path.insert(0, ".")

from strategy_okx_ai import main

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    main()
