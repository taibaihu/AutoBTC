#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BB-Ride OKX \u6267\u884c\u7b56\u7565\u542f\u52a8\u5668"""
import sys, os
# \u6dfb\u52a0\u7236\u76ee\u5f55\uff08\u652f\u6301\u4ece OKX-Ride \u5b50\u6587\u4ef6\u5939\u542f\u52a8\uff09
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from strategy_bb_ride_okx import main

if __name__ == "__main__":
    main()
