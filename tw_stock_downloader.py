#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台股歷史資料批次下載器（普通股名冊修正版）
=================================================
用途：下載 TWSE / TPEx 個股日K，輸出給「六脈神劍選股系統.html」上傳使用。

這版修正：
1. --all 預設改抓「上市/上櫃普通股」公司基本資料名冊，避免把 ETF、ETN、債券、權證等非普通股商品一起塞進股票池。
2. 若要抓全部可交易商品才使用 --all-products；若要額外納入 ETF/ETN，可用 --include-etf / --include-etn。
3. 上櫃股票優先走新版 TPEx endpoint，legacy st43_result 只當備援。
4. 若 TPEx 官方端點查無或被暫時限流，改走 Yahoo Finance chart API 備援。
5. 已知上市/上櫃市場時不再每檔都先打 TWSE 再打 TPEx，降低請求量。

安裝需求：
    pip install requests

用法：
    # 建議：普通股全市場（預設，不含 ETF / ETN / 權證 / 債券商品）
    python tw_stock_downloader.py --all --out history.csv --months 4 --sleep 0.8 --resume

    # 只抓上櫃普通股
    python tw_stock_downloader.py --all --only-tpex --out otc_history.csv --months 4 --sleep 1 --resume

    # 如真的需要包含 ETF，可額外加 --include-etf
    python tw_stock_downloader.py --all --include-etf --out history_with_etf.csv --months 4

    # 指定代號
    python tw_stock_downloader.py --codes 2330,3481,1240 --out history.csv

    # 舊式超寬名冊（不建議，會包含大量非股票商品）
    python tw_stock_downloader.py --all-products --out all_products.csv
"""

import argparse
import csv
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:
    sys.exit("缺少 requests 套件，請先執行：pip install requests")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 15


def safe_get_json(url, retries=2, sleep_base=1.0):
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            text = r.text.strip()
            if not text:
                raise RuntimeError("empty response")
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(sleep_base * (attempt + 1) + random.random() * 0.5)
    raise last_err


def parse_num(v):
    s = str(v).strip().replace(",", "").replace("--", "").replace("－", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", ".", "-"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_date(v):
    s = str(v).strip()
    parts = re.split(r"[/\-.]", s)
    if len(parts) >= 3 and all(p.strip().isdigit() for p in parts[:3]):
        y, m, d = [int(p) for p in parts[:3]]
        if y < 1911:
            y += 1911
        return f"{y:04d}-{m:02d}-{d:02d}"
    return None


def extract_code_name(obj):
    code, name, industry, capital = None, None, "", ""
    for k, v in obj.items():
        sv = str(v).strip()
        lk = str(k).lower()
        if re.fullmatch(r"\d{4,6}", sv) and code is None:
            code = sv
        if ("name" in lk or "名稱" in str(k) or "公司簡稱" in str(k)) and name is None and sv and not re.fullmatch(r"\d+", sv):
            name = sv
        if ("industry" in lk or "產業" in str(k)) and sv:
            industry = sv
        if ("capital" in lk or "股本" in str(k) or "實收資本額" in str(k)) and sv:
            capital = sv
    return code, name, industry, capital



NON_STOCK_KEYWORDS = [
    "購", "售", "權證", "牛", "熊", "認購", "認售", "牛證", "熊證",
    "債", "公司債", "金融債", "受益證券", "受益", "指數", "指數投資證券",
    "ETN", "存託憑證", "TDR", "特別股", "特股", "DR"
]
ETF_KEYWORDS = ["ETF", "富邦", "元大", "國泰", "群益", "凱基", "復華", "永豐", "統一", "兆豐", "新光", "台新", "中信", "第一金", "野村", "街口", "主動"]
ETN_KEYWORDS = ["ETN", "指數投資證券"]


def normalize_capital_to_yi(v):
    """把實收資本額或股本欄位盡量轉為「億元」。"""
    n = parse_num(v)
    if n is None:
        return ""
    # 常見基本資料 API 是元；若數字很大，除以一億。
    if n > 1000000:
        return str(round(n / 100000000, 4))
    # 若已是千元或百萬元口徑，保守留空避免誤算。
    return str(n)


def pick_field(obj, names):
    for name in names:
        if name in obj and str(obj.get(name, "")).strip():
            return str(obj.get(name, "")).strip()
    for k, v in obj.items():
        sk = str(k)
        if any(name in sk for name in names) and str(v).strip():
            return str(v).strip()
    return ""


def is_probably_etf_or_etn(name, industry=""):
    txt = f"{name} {industry}".upper()
    if any(k.upper() in txt for k in ETN_KEYWORDS):
        return "etn"
    if "ETF" in txt or "指數股票型" in txt or "基金" in txt or "債" in txt:
        return "etf"
    return "stock"


def is_non_stock_product(code, name, industry=""):
    if not re.fullmatch(r"\d{4}", str(code)):
        return True
    txt = f"{name} {industry}"
    # 明確公司產業別通常就是普通股，避免把「金融業」裡的債字誤殺。
    if industry and industry not in ("ETF", "ETN", "受益證券", "指數類", "認購(售)權證"):
        return False
    if any(k in txt for k in NON_STOCK_KEYWORDS):
        return True
    return False


def merge_unique(items):
    seen = set()
    out = []
    for item in items:
        code = item.get("code")
        market = item.get("market")
        key = (market, code)
        if not code or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def get_twse_stock_list():
    """上市普通股公司基本資料。比 STOCK_DAY_ALL 乾淨，不會把 ETF/ETN/權證全部抓進來。"""
    urls = [
        "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    ]
    out = []
    last_err = None
    for url in urls:
        try:
            data = safe_get_json(url)
            if not isinstance(data, list):
                continue
            for d in data:
                if not isinstance(d, dict):
                    continue
                code = pick_field(d, ["公司代號", "Code", "有價證券代號"])
                # 某些資料第一欄可能是日期，若取錯就再掃描欄位。
                if not re.fullmatch(r"\d{4}", code or ""):
                    for k, v in d.items():
                        sv = str(v).strip()
                        if re.fullmatch(r"\d{4}", sv):
                            code = sv
                            break
                name = pick_field(d, ["公司簡稱", "公司名稱", "Name", "有價證券名稱"])
                industry = pick_field(d, ["產業別", "industry"])
                capital = pick_field(d, ["實收資本額", "實收資本額(元)", "股本", "capital"])
                if re.fullmatch(r"\d{4}", code or "") and not is_non_stock_product(code, name, industry):
                    out.append({"code": code, "name": name or code, "market": "twse", "industry": industry, "capital": normalize_capital_to_yi(capital)})
            if out:
                return merge_unique(out)
        except Exception as e:
            last_err = e
    print(f"  ⚠️ 上市普通股名冊抓取失敗：{last_err}，改用日行情名冊過濾")
    return [x for x in get_twse_list() if not is_non_stock_product(x.get("code"), x.get("name"), x.get("industry"))]


def get_tpex_stock_list():
    """上櫃普通股公司基本資料。避免 tpex quotes 端點抓到大量非普通股商品。"""
    urls = [
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    ]
    out = []
    last_err = None
    for url in urls:
        try:
            data = safe_get_json(url)
            if not isinstance(data, list):
                continue
            for d in data:
                if not isinstance(d, dict):
                    continue
                code = pick_field(d, ["公司代號", "Code", "有價證券代號"])
                if not re.fullmatch(r"\d{4}", code or ""):
                    for k, v in d.items():
                        sv = str(v).strip()
                        if re.fullmatch(r"\d{4}", sv):
                            code = sv
                            break
                name = pick_field(d, ["公司簡稱", "公司名稱", "Name", "有價證券名稱"])
                industry = pick_field(d, ["產業別", "industry"])
                capital = pick_field(d, ["實收資本額", "實收資本額(元)", "股本", "capital"])
                if re.fullmatch(r"\d{4}", code or "") and not is_non_stock_product(code, name, industry):
                    out.append({"code": code, "name": name or code, "market": "tpex", "industry": industry, "capital": normalize_capital_to_yi(capital)})
            if out:
                return merge_unique(out)
        except Exception as e:
            last_err = e
    print(f"  ⚠️ 上櫃普通股名冊抓取失敗：{last_err}，改用日行情名冊過濾")
    return [x for x in get_tpex_list() if not is_non_stock_product(x.get("code"), x.get("name"), x.get("industry"))]


def filter_optional_products(items, include_etf=False, include_etn=False, include_beneficiary=False):
    out = []
    for x in items:
        code, name, industry = x.get("code", ""), x.get("name", ""), x.get("industry", "")
        if not re.fullmatch(r"\d{4}", str(code)):
            continue
        kind = is_probably_etf_or_etn(name, industry)
        txt = f"{name} {industry}"
        if kind == "etf" and include_etf:
            out.append(x)
        elif kind == "etn" and include_etn:
            out.append(x)
        elif ("受益" in txt) and include_beneficiary:
            out.append(x)
    return out

def get_twse_list():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    data = safe_get_json(url)
    out = []
    for d in data:
        code = str(d.get("Code", "") or d.get("證券代號", "")).strip()
        name = str(d.get("Name", "") or d.get("證券名稱", "")).strip()
        if re.fullmatch(r"\d{4,6}", code):
            out.append({"code": code, "name": name or code, "market": "twse", "industry": "", "capital": ""})
    return out


def get_tpex_list():
    urls = [
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
    ]
    last_err = None
    for url in urls:
        try:
            data = safe_get_json(url)
            out = []
            for d in data:
                if not isinstance(d, dict):
                    continue
                code, name, industry, capital = extract_code_name(d)
                if code:
                    out.append({"code": code, "name": name or code, "market": "tpex", "industry": industry, "capital": capital})
            if out:
                return out
        except Exception as e:
            last_err = e
    print(f"  ⚠️ 上櫃名冊抓取失敗：{last_err}")
    return []


def recent_months(n):
    months = []
    now = datetime.now()
    y, m = now.year, now.month
    for _ in range(n):
        months.append({
            "ym": f"{y}{m:02d}",
            "roc": f"{y-1911}/{m:02d}",
            "ad_slash": f"{y}/{m:02d}/01",
        })
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return months


def rows_from_payload(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or payload.get("aaData") or []
    fields = payload.get("fields") or payload.get("columns") or []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
    if not isinstance(data, list):
        return []
    rows = []
    for raw in data:
        if not isinstance(raw, (list, tuple)) or len(raw) < 6:
            continue
        dt = parse_date(raw[0])
        if not dt:
            continue
        # 常見格式：日期, 成交股數/成交仟股, 成交金額, 開盤, 最高, 最低, 收盤...
        o = parse_num(raw[3] if len(raw) > 3 else None)
        h = parse_num(raw[4] if len(raw) > 4 else None)
        l = parse_num(raw[5] if len(raw) > 5 else None)
        c = parse_num(raw[6] if len(raw) > 6 else None)
        vol = parse_num(raw[1] if len(raw) > 1 else None)
        if o is None or h is None or l is None or c is None:
            # 新版API若欄位順序不同，使用欄位名稱防禦解析
            mapping = {str(fields[i]): raw[i] for i in range(min(len(fields), len(raw)))} if isinstance(fields, list) else {}
            def by_kw(*kws):
                for k, v in mapping.items():
                    if all(kw in k for kw in kws):
                        return v
                return None
            o = parse_num(by_kw("開盤"))
            h = parse_num(by_kw("最高"))
            l = parse_num(by_kw("最低"))
            c = parse_num(by_kw("收盤"))
            vol = parse_num(by_kw("成交", "股")) or parse_num(by_kw("成交", "量"))
        if o is None or h is None or l is None or c is None:
            continue
        rows.append({
            "date": dt,
            "open": str(o),
            "high": str(h),
            "low": str(l),
            "close": str(c),
            "volume": str(vol or 0),
        })
    return rows


def fetch_twse_month(code, m):
    urls = [
        f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={m['ym']}01&stockNo={code}",
        f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?response=json&date={m['ym']}01&stockNo={code}",
    ]
    for url in urls:
        try:
            j = safe_get_json(url, retries=1)
            rows = rows_from_payload(j)
            if rows:
                return rows
        except Exception:
            continue
    return []


def fetch_tpex_month(code, m):
    # 新版 TPEx 優先，legacy st43_result 當備援。
    urls = [
        f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={code}&date={quote(m['ad_slash'], safe='')}&response=json",
        f"https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d={quote(m['roc'], safe='')}&stkno={code}",
    ]
    for url in urls:
        try:
            j = safe_get_json(url, retries=1)
            rows = rows_from_payload(j)
            if rows:
                return rows
        except Exception:
            continue
    return []


def yahoo_chart_rows(code, market, months_back):
    suffix = ".TWO" if market == "tpex" else ".TW"
    symbol = f"{code}{suffix}"
    # 用 period1/period2 避免 range 對台股偶爾回傳不穩
    now = int(time.time())
    period1 = now - int(months_back * 32 * 86400)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={period1}&period2={now}&interval=1d&events=history&includeAdjustedClose=true")
    try:
        j = safe_get_json(url, retries=2, sleep_base=1.5)
        result = (((j or {}).get("chart") or {}).get("result") or [None])[0]
        if not result:
            return []
        ts = result.get("timestamp") or []
        q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = q.get("open") or []
        highs = q.get("high") or []
        lows = q.get("low") or []
        closes = q.get("close") or []
        vols = q.get("volume") or []
        rows = []
        for i, t in enumerate(ts):
            try:
                o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                if o is None or h is None or l is None or c is None:
                    continue
                dt = datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%d")
                rows.append({
                    "date": dt,
                    "open": str(round(float(o), 4)),
                    "high": str(round(float(h), 4)),
                    "low": str(round(float(l), 4)),
                    "close": str(round(float(c), 4)),
                    "volume": str(float(vols[i] or 0)),
                })
            except Exception:
                continue
        return rows
    except Exception:
        return []


def fetch_history(code, market="auto", months_back=4):
    months = recent_months(months_back)
    candidates = []
    if market in ("twse", "tpex"):
        candidates = [market]
    else:
        candidates = ["twse", "tpex"]

    for src in candidates:
        rows = []
        # 先試當月，確認來源。
        try:
            first = fetch_twse_month(code, months[0]) if src == "twse" else fetch_tpex_month(code, months[0])
            if first:
                rows.extend(first)
                for m in months[1:]:
                    time.sleep(0.08)
                    more = fetch_twse_month(code, m) if src == "twse" else fetch_tpex_month(code, m)
                    rows.extend(more)
                return src, dedupe_rows(rows), "official"
        except Exception:
            pass

    # 官方端點查不到或被暫時擋，走 Yahoo 備援。若 auto，TWSE/TPEX 都試。
    for src in candidates:
        rows = yahoo_chart_rows(code, src, months_back)
        if rows:
            return src, dedupe_rows(rows), "yahoo"

    return None, [], "none"


def dedupe_rows(rows):
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda x: x["date"]):
        if r["date"] in seen:
            continue
        seen.add(r["date"])
        uniq.append(r)
    return uniq


def load_done_codes(out_path):
    p = Path(out_path)
    if not p.exists():
        return set()
    done = set()
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("code"):
                    done.add(row["code"])
    except Exception:
        pass
    return done


def main():
    parser = argparse.ArgumentParser(description="台股歷史資料批次下載器（普通股名冊修正版）")
    parser.add_argument("--codes", help="逗號分隔的股票代號清單，例如 2330,2317,2454")
    parser.add_argument("--all", action="store_true", help="抓取全市場普通股（預設建議；不含ETF/ETN/權證/債券商品）")
    parser.add_argument("--all-products", action="store_true", help="抓取超寬全市場商品名冊（不建議；可能含ETF/ETN/權證/債券等大量非普通股商品）")
    parser.add_argument("--include-etf", action="store_true", help="搭配 --all 時額外納入 ETF / 債券ETF 等商品")
    parser.add_argument("--include-etn", action="store_true", help="搭配 --all 時額外納入 ETN")
    parser.add_argument("--include-beneficiary", action="store_true", help="搭配 --all 時額外納入受益證券")
    parser.add_argument("--only-twse", action="store_true", help="只抓上市")
    parser.add_argument("--only-tpex", action="store_true", help="只抓上櫃")
    parser.add_argument("--out", default="history.csv", help="輸出CSV檔名（預設 history.csv）")
    parser.add_argument("--months", type=int, default=4, help="回溯月數（預設4個月）")
    parser.add_argument("--sleep", type=float, default=0.5, help="每檔股票之間延遲秒數（預設0.5秒）")
    parser.add_argument("--resume", action="store_true", help="續跑：跳過輸出檔已存在的代號")
    parser.add_argument("--limit", type=int, default=0, help="本次最多抓幾檔，0=不限")
    args = parser.parse_args()

    if args.all or args.all_products:
        targets = []
        if args.all_products:
            if not args.only_tpex:
                print("正在抓取上市超寬名冊（含非普通股商品，僅供特殊用途）…")
                twse = get_twse_list()
                print(f"  上市商品 {len(twse)} 檔")
                targets.extend(twse)
            if not args.only_twse:
                print("正在抓取上櫃超寬名冊（含非普通股商品，僅供特殊用途）…")
                tpex = get_tpex_list()
                print(f"  上櫃商品 {len(tpex)} 檔")
                targets.extend(tpex)
        else:
            if not args.only_tpex:
                print("正在抓取上市普通股名冊…")
                twse = get_twse_stock_list()
                print(f"  上市普通股 {len(twse)} 檔")
                targets.extend(twse)
                if args.include_etf or args.include_etn or args.include_beneficiary:
                    extra = filter_optional_products(get_twse_list(), args.include_etf, args.include_etn, args.include_beneficiary)
                    print(f"  上市額外商品 {len(extra)} 檔")
                    targets.extend(extra)
            if not args.only_twse:
                print("正在抓取上櫃普通股名冊…")
                tpex = get_tpex_stock_list()
                print(f"  上櫃普通股 {len(tpex)} 檔")
                targets.extend(tpex)
                if args.include_etf or args.include_etn or args.include_beneficiary:
                    extra = filter_optional_products(get_tpex_list(), args.include_etf, args.include_etn, args.include_beneficiary)
                    print(f"  上櫃額外商品 {len(extra)} 檔")
                    targets.extend(extra)
        targets = merge_unique(targets)
    elif args.codes:
        codes = [c.strip() for c in re.split(r"[,，\s]+", args.codes) if c.strip()]
        targets = [{"code": c, "name": c, "market": "auto", "industry": "", "capital": ""} for c in codes]
    else:
        parser.error("請指定 --codes 2330,2317,... 或使用 --all 抓普通股全市場；特殊需求可用 --all-products")
        return

    if args.limit and args.limit > 0:
        targets = targets[:args.limit]

    done_codes = load_done_codes(args.out) if args.resume else set()
    mode = "a" if args.resume and Path(args.out).exists() else "w"
    write_header = not (mode == "a" and Path(args.out).exists() and Path(args.out).stat().st_size > 0)

    print(f"共 {len(targets)} 檔，開始下載近 {args.months} 個月歷史資料…")
    if done_codes:
        print(f"續跑模式：已存在 {len(done_codes)} 檔，會自動跳過。")
    print("提示：--all 預設只抓普通股；若官方 TPEx 暫時限流，程式會自動改用 Yahoo 備援。\n")

    ok_count = 0
    yahoo_count = 0
    fail_count = 0
    with open(args.out, mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["code", "name", "market", "industry", "date", "open", "high", "low", "close", "volume"])
        for i, item in enumerate(targets):
            code = item["code"]
            name = item.get("name") or code
            market_hint = item.get("market") or "auto"
            industry = item.get("industry") or ""
            if code in done_codes:
                print(f"[{i+1}/{len(targets)}] {code} {name} ... SKIP（已存在）")
                continue
            print(f"[{i+1}/{len(targets)}] {code} {name} ...", end=" ", flush=True)
            try:
                source, rows, provider = fetch_history(code, market_hint, args.months)
                if not rows:
                    fail_count += 1
                    print("查無資料")
                    continue
                for r in rows:
                    writer.writerow([code, name, source or market_hint, industry, r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]])
                f.flush()
                ok_count += 1
                if provider == "yahoo":
                    yahoo_count += 1
                print(f"OK（{source} / {provider}，{len(rows)}筆）")
            except Exception as e:
                fail_count += 1
                print(f"失敗：{e}")
            time.sleep(args.sleep + random.random() * 0.15)

    print(f"\n完成。成功 {ok_count} 檔，其中 Yahoo 備援 {yahoo_count} 檔；失敗 {fail_count} 檔。")
    print(f"已寫入 {args.out}")
    print("接下來把 CSV 上傳到 HTML 的「②上傳離線下載的CSV資料」區塊即可。")


if __name__ == "__main__":
    main()
