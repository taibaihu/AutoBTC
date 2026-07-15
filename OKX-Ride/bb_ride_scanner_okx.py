#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
布林骑行扫描器 — OKX 版
条件: 连续15根15分钟K线≥12根阳线/阴线, 无暴涨暴跌K线, 24h量>1000万USDT
只扫描24h成交量排名前200的币种, 过滤TradFi/虚拟货币
每天每币种只保留最优一条
结果输出到 JSON 文件，供前端展示
"""
import sys, time, logging, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor
import ccxt

from config import OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE

DB_CONFIG = {
    "host": "rm-j6cn8z161cj4lil55to.mysql.rds.aliyuncs.com",
    "port": 3306,
    "user": "bitgetok",
    "password": "bitgetOk123",
    "database": "ll_test",
}

TIMEFRAME = "15m"
WINDOW_CANDLES = 15
MIN_BULLISH = 12
MAX_CANDLE_SURGE = 0.05
MIN_24H_VOL = 10_000_000  # 1000万 USDT（OKX流动性不如币安）
FETCH_LIMIT = 130
TOP_N = 200

TRADFI_BLACKLIST = {
    "AAPL","TSLA","NVDA","AMZN","MSFT","GOOGL","META","NFLX","COIN","MSTR",
    "COST","AMD","INTC","ARM","DATA","CARDS","DELL","CBRS","NBIS","AXTI","SKHYNIX","QCOM","NOK","GLW","ARM","HOOD","PLTR","BABA","DIS","UBER","PYPL",
    "CRM","ADBE","ORCL","IBM","CSCO","DATA","CARDS","DELL","CBRS","NBIS","AXTI","SKHYNIX","QCOM","TXN","AVGO","AMAT","ASML",
    "MU","MRVL","DELL","SMCI","JPM","GS","MS","V","MA","WMT","HD",
    "NKE","MCD","SBUX","KO","PEP","BA","CAT","GE","XOM","CVX",
    "JNJ","PFE","ABBV","LLY","UNH","SPY","QQQ","IWM","DIA",
    "BZ","TSM","JD","BIDU","NIO","RIVN","GM","F",
    "T","VZ","NEE","WFC","C",
    "AMC","GME","BB","MARA","RIOT","SOFI","RBLX","DKNG","ABNB",
    "GLD","SLV","USO","UNG","GDX","GDXJ",
    "LITE","CRCL","DRAM","AERO","BZ","TSM","SAMSUNG","SNDK",
    "XAU","XAG","XPT","PAXG",
}

LARGE_CAP_FILTER = {"BTC", "ETH", "BNB", "XRP", "SOL", "HYPE", "DOGE", "TRX", "LINK", "XMR", "BCH"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("BB_Ride_OKX")

RESULT_FILE = str(Path(__file__).parent / "bb_ride_scanner_okx_results.json")


def is_tradfi(coin: str) -> bool:
    if coin in TRADFI_BLACKLIST:
        return True
    if coin.startswith("1000"):
        return True
    return False


def check_window(candles, direction="up"):
    """与币安版完全相同的窗口检测逻辑"""
    results = []
    if len(candles) < WINDOW_CANDLES + 1:
        return results

    max_start = len(candles) - WINDOW_CANDLES - 1
    min_start = max(1, len(candles) - FETCH_LIMIT + WINDOW_CANDLES)

    for start_idx in range(min_start, max_start + 1):
        end_idx = start_idx + WINDOW_CANDLES - 1

        match_count = 0
        has_extreme = False
        max_extreme = 0

        for i in range(WINDOW_CANDLES):
            idx = start_idx + i
            c = candles[idx]
            o, cl = c[1], c[4]

            if direction == "up":
                if cl > o:
                    match_count += 1
                gain = (cl - o) / o if o > 0 else 0
                max_extreme = max(max_extreme, gain)
                if gain > MAX_CANDLE_SURGE:
                    has_extreme = True
            else:
                if cl < o:
                    match_count += 1
                loss = (o - cl) / o if o > 0 else 0
                max_extreme = max(max_extreme, loss)
                if loss > MAX_CANDLE_SURGE:
                    has_extreme = True

        if match_count < MIN_BULLISH:
            continue
        if has_extreme:
            continue

        start_open = candles[start_idx][1]
        end_close = candles[end_idx][4]
        if direction == "up":
            if end_close <= start_open:
                continue
            total_change = (end_close - start_open) / start_open * 100
        else:
            if end_close >= start_open:
                continue
            total_change = (end_close - start_open) / start_open * 100

        if abs(total_change) < 3 or abs(total_change) > 15:
            continue

        window_vol = sum(candles[i][4] * candles[i][5] for i in range(start_idx, end_idx + 1))
        avg_vol = window_vol / WINDOW_CANDLES
        est_24h = avg_vol * 96
        if est_24h < MIN_24H_VOL:
            continue

        start_ts = candles[start_idx][0] / 1000
        start_bj = datetime.fromtimestamp(start_ts, tz=timezone(timedelta(hours=8)))

        abs_change = abs(total_change)
        score = 0
        if match_count >= 13:
            score += 2
        elif match_count >= 12:
            score += 1
        if abs_change < 8:
            score += 1
        if abs_change < 5:
            score += 1
        if max_extreme < 0.02:
            score += 1

        results.append({
            "coin": "",
            "current_price": candles[end_idx][4],
            "pattern_start_bj": start_bj,
            "pattern_end_bj": datetime.fromtimestamp(candles[end_idx][0] / 1000, tz=timezone(timedelta(hours=8))),
            "rise_pct": total_change,
            "volume_24h": est_24h,
            "match_count": match_count,
            "max_extreme": max_extreme * 100,
            "score": min(score, 5),
            "direction": direction,
        })

    return results


def _ensure_table():
    """确保 bb_ride_scanner_okx 表存在"""
    try:
        conn = pymysql.connect(**DB_CONFIG, cursorclass=DictCursor, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bb_ride_scanner_okx (
                id INT AUTO_INCREMENT PRIMARY KEY,
                coin VARCHAR(20) NOT NULL,
                scan_time DATETIME NOT NULL,
                current_price DECIMAL(20,8),
                bb_mid DECIMAL(20,8) DEFAULT 0,
                bb_upper DECIMAL(20,8) DEFAULT 0,
                bb_lower DECIMAL(20,8) DEFAULT 0,
                pct_from_mid DECIMAL(10,4) DEFAULT 0,
                pattern_start_bj DATETIME,
                pattern_day DATE,
                rise_pct DECIMAL(10,4),
                volume_24h DECIMAL(20,2),
                volume_ratio DECIMAL(10,4) DEFAULT 0,
                trend_1h VARCHAR(10) DEFAULT '',
                score INT DEFAULT 0,
                direction VARCHAR(10) DEFAULT 'up',
                signal_time DATETIME,
                INDEX idx_coin_day (coin, pattern_day, direction),
                INDEX idx_signal_time (signal_time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.close()
        logger.info("✅ 确保 bb_ride_scanner_okx 表存在")
    except Exception as e:
        logger.warning(f"建表失败: {e}")


def save_to_db(rows: list):
    """保存扫描结果到 bb_ride_scanner_okx 表，供策略读取"""
    if not rows:
        logger.info("💾 无新数据写入")
        return
    try:
        conn = pymysql.connect(**DB_CONFIG, cursorclass=DictCursor)
        cur = conn.cursor()
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        now_bj = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            "SELECT coin, pattern_day, direction FROM bb_ride_scanner_okx WHERE scan_time >= %s",
            (cutoff_24h,)
        )
        existing_days = set()
        for r in cur.fetchall():
            existing_days.add(f"{r['coin']}|{r['pattern_day']}|{r.get('direction','up')}")

        inserted = 0
        skipped = 0
        sql = """INSERT INTO bb_ride_scanner_okx
            (coin, scan_time, current_price, bb_mid, bb_upper, bb_lower,
             pct_from_mid, pattern_start_bj, pattern_day, rise_pct, volume_24h, volume_ratio, trend_1h, score, direction, signal_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""

        for r in rows:
            # 高价过滤: 价格>100USDT 不参与底部启动
            if r['current_price'] and float(r['current_price']) > 100:
                continue
            date_key = r["pattern_start_bj"].strftime("%Y-%m-%d")
            key = f"{r['coin']}|{date_key}|{r.get('direction','up')}"
            if key in existing_days:
                skipped += 1
                continue

            start_full = r["pattern_start_bj"].strftime("%Y-%m-%d %H:%M:%S")
            # 发现时间 = 开始时间 + 15根K线
            signal_bj = r["pattern_start_bj"] + timedelta(minutes=WINDOW_CANDLES * 15)
            signal_bj_str = signal_bj.strftime("%Y-%m-%d %H:%M:%S")
            try:
                cur.execute(sql, (
                    r["coin"], now_utc, r["current_price"], 0, 0, 0,
                    r["max_extreme"], start_full, date_key,
                    r["rise_pct"], r["volume_24h"], r["match_count"], "",
                    min(r["score"], 5), r.get("direction", "up"),
                    signal_bj_str,
                ))
                inserted += 1
            except Exception:
                skipped += 1

        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"💾 写入 bb_ride_scanner_okx {inserted} 条（跳过 {skipped} 条重复）")
    except Exception as e:
        logger.error(f"数据库写入失败: {e}")


def save_results(results: list):
    """保存扫描结果到JSON文件，供前端读取"""
    data = {
        "scan_time": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
        "exchange": "OKX",
        "total_signals": len(results),
        "signals": results,
    }
    try:
        with open(RESULT_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"💾 结果已保存到 {RESULT_FILE} ({len(results)}条)")
    except Exception as e:
        logger.error(f"保存结果失败: {e}")


def main():
    logger.info("🚀 OKX 底部启动扫描器启动")
    logger.info(f"   阳线: ≥{MIN_BULLISH}/{WINDOW_CANDLES}阳 单根涨幅≤{MAX_CANDLE_SURGE*100}%")
    logger.info(f"   阴线: ≥{MIN_BULLISH}/{WINDOW_CANDLES}阴 单根跌幅≤{MAX_CANDLE_SURGE*100}%")
    logger.info(f"   量≥{MIN_24H_VOL/1e6:.0f}M TOP{TOP_N} TradFi过滤")

    # 确保数据库表存在
    _ensure_table()

    # OKX 永续合约，无需 API Key 也可扫公开数据
    ex = ccxt.okx({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    ex.load_markets()

    # OKX 的合约 symbol 格式: BTC/USDT:USDT
    symbols = [s for s in ex.symbols if s.endswith("/USDT:USDT")]
    logger.info(f"总合约{len(symbols)}个，获取24h成交量排名...")

    try:
        tickers = ex.fetch_tickers()
        time.sleep(0.5)
    except Exception as e:
        logger.warning(f"获取tickers失败: {e}")
        tickers = {}

    vol_list = []
    for s in symbols:
        coin = s.split("/")[0]
        if is_tradfi(coin):
            continue
        if coin in LARGE_CAP_FILTER:
            continue
        t = tickers.get(s)
        if not t:
            continue
        info = t.get("info", {}); base_vol = float(info.get("volCcy24h", 0) or 0)
        last = float(t.get("last", 0) or 0)
        vol = base_vol * last  # 换算成USDT成交量
        if vol <= 0:
            continue
        vol_list.append((coin, s, vol))

    vol_list.sort(key=lambda x: -x[2])
    scan_list = vol_list[:TOP_N]

    logger.info(f"过滤TradFi后取前{TOP_N}名")
    if scan_list:
        logger.info(f"  第1名: {scan_list[0][0]} ${scan_list[0][2]/1e6:.0f}M")
        logger.info(f"  第{TOP_N}名: {scan_list[-1][0]} ${scan_list[-1][2]/1e6:.0f}M")

    all_results = []
    errors = 0

    for idx, (coin, symbol, volume) in enumerate(scan_list):
        sys.stdout.write(f"\r  扫描: {idx+1}/{len(scan_list)}  {coin}  Vol=${volume/1e6:.0f}M")
        sys.stdout.flush()

        try:
            candles = ex.fetch_ohlcv(symbol, TIMEFRAME, limit=FETCH_LIMIT)
            time.sleep(0.12)
        except Exception:
            errors += 1
            time.sleep(0.15)
            continue

        if not candles or len(candles) < WINDOW_CANDLES + 1:
            continue

        last_close = candles[-1][4]
        if last_close > 100:
            continue

        for direction in ("up", "down"):
            windows = check_window(candles, direction=direction)
            for w in windows:
                w["coin"] = coin
                w["volume_24h"] = volume
                all_results.append(w)

    print()
    logger.info(f"扫描完成，共发现 {len(all_results)} 个形态窗口，{errors}个错误")

    # 去重：每天每币每方向只保留最优一条
    best_per_coin_day = {}
    for r in all_results:
        dkey = r["pattern_start_bj"].strftime("%Y-%m-%d")
        key = (r["coin"], dkey, r.get("direction", "up"))
        if key not in best_per_coin_day:
            best_per_coin_day[key] = r
        else:
            ex_rec = best_per_coin_day[key]
            if r["score"] > ex_rec["score"]:
                best_per_coin_day[key] = r

    deduped = list(best_per_coin_day.values())
    logger.info(f"按币种+天+方向去重后: {len(deduped)} 条")

    # 按信号时间（窗口结束时间）排序
    deduped.sort(key=lambda r: (r["pattern_start_bj"], r.get("direction", "")))

    if deduped:
        logger.info(f"\n{'='*80}")
        logger.info(f"OKX 扫描结果:")
        logger.info(f"{'币种':<8} {'方向':<6} {'窗口(北京)':<22} {'匹配':<6} {'涨跌幅%':<8} {'单根最大%':<10} {'评分':<6} {'24h量':<10}")
        logger.info("-" * 80)
        for r in deduped:
            start = r["pattern_start_bj"].strftime("%m/%d %H:%M")
            end = r["pattern_end_bj"].strftime("%H:%M")
            dir_icon = "🟢阳" if r["direction"] == "up" else "🔴阴"
            logger.info(f"{r['coin']:<8} {dir_icon:<6} {start}-{end:<13} {r['match_count']}/{WINDOW_CANDLES} {r['rise_pct']:<+7.2f}% {r['max_extreme']:<+7.2f}% "
                        f"{r['score']}/5 {'★'*r['score']}  ${r['volume_24h']/1e6:.0f}M")

    save_results(deduped)
    save_to_db(deduped)


if __name__ == "__main__":
    main()
