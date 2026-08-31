"""How much open interest history can you actually get, and in which column?

Freqtrade gained open interest candles on 2026-08-30. Before building a
strategy on them, two things decide whether the idea is testable at all:

  1. HOW FAR BACK the exchange serves open interest. This is nothing like
     candle history, and venues differ by orders of magnitude: one major
     venue serves roughly a month and rejects anything older outright,
     another serves back to the instrument's listing date.

  2. WHICH COLUMN carries data. Freqtrade exposes `open_interest_amount`
     (base currency) and `open_interest_value` (quote currency). Exchanges
     report one, the other, or both -- and a column that is all NaN looks
     exactly like a failed download.

This script answers both by hitting the public endpoints directly. No API key,
no freqtrade install, no downloaded data required.

    python check_oi_coverage.py
    python check_oi_coverage.py --symbol ETHUSDT
"""
import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request

TIMEOUT = 20
PROBE_DAYS = (7, 30, 90, 365, 730, 1460, 2190)


def fetch(url):
    """Return (payload, error_string). HTTP errors are data here, not crashes:
    a venue refusing an old window is exactly what we are measuring."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, type(e).__name__


def window(days_ago, span_hours=48):
    end = dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)
    start = end - dt.timedelta(hours=span_hours)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


# ------------------------------------------------------------------- venues

def bybit(symbol):
    base = "https://api.bybit.com/v5/market/open-interest"

    latest, err = fetch(f"{base}?category=linear&symbol={symbol}"
                        f"&intervalTime=1h&limit=200")
    rows = (latest or {}).get("result", {}).get("list", []) if not err else []

    depth = {}
    for days in PROBE_DAYS:
        start, end = window(days)
        d, e = fetch(f"{base}?category=linear&symbol={symbol}&intervalTime=1h"
                     f"&startTime={start}&endTime={end}&limit=200")
        depth[days] = e or len((d or {}).get("result", {}).get("list", []))

    # Bybit linear reports contracts in the base currency only.
    fields = sorted(rows[0].keys()) if rows else []
    return {
        "venue": "bybit (linear)",
        "latest_rows": len(rows),
        "fields": fields,
        "base_column": "openInterest" in fields,
        "quote_column": any("value" in f.lower() for f in fields),
        "depth": depth,
    }


def binance(symbol):
    base = "https://fapi.binance.com/futures/data/openInterestHist"

    latest, err = fetch(f"{base}?symbol={symbol}&period=1h&limit=500")
    rows = latest if isinstance(latest, list) and not err else []

    depth = {}
    for days in PROBE_DAYS:
        start, end = window(days)
        d, e = fetch(f"{base}?symbol={symbol}&period=1h"
                     f"&startTime={start}&endTime={end}&limit=500")
        depth[days] = e or (len(d) if isinstance(d, list) else 0)

    fields = sorted(rows[0].keys()) if rows else []
    return {
        "venue": "binance (usdt-m)",
        "latest_rows": len(rows),
        "fields": fields,
        "base_column": "sumOpenInterest" in fields,
        "quote_column": "sumOpenInterestValue" in fields,
        "depth": depth,
    }


# ------------------------------------------------------------------ report

def span(rows_key, report):
    if not report["latest_rows"]:
        return "no data"
    return f"{report['latest_rows']} rows in one request"


def render(reports):
    print("Open interest coverage, 1h, measured just now\n")

    for r in reports:
        print(f"  {r['venue']}")
        if not r["latest_rows"]:
            print("    no data returned -- symbol may not exist on this venue\n")
            continue

        print(f"    fields returned : {', '.join(r['fields'])}")
        base = "yes" if r["base_column"] else "NO"
        quote = "yes" if r["quote_column"] else "NO  <- open_interest_value will be all-NaN"
        print(f"    base amount     : {base}")
        print(f"    quote value     : {quote}")
        print("    history probe (48h window ending N days ago):")
        for days, result in r["depth"].items():
            if isinstance(result, str):
                mark = f"{result}  <- refused"
            elif result == 0:
                mark = "0 rows  <- empty"
            else:
                mark = f"{result} rows"
            print(f"      {days:>4} days ago : {mark}")
        print()

    usable = [(r["venue"], max((d for d, v in r["depth"].items()
                               if isinstance(v, int) and v > 0), default=0))
              for r in reports if r["latest_rows"]]
    if usable:
        best = max(usable, key=lambda x: x[1])
        print(f"Deepest usable history: {best[0]} at {best[1]}+ days.")
        print("Download open interest from the venue with the history, even if "
              "you intend to trade somewhere else -- for a backtest, depth of "
              "history beats matching the execution venue.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbol", default="BTCUSDT",
                    help="perpetual symbol, venue-native form (default BTCUSDT)")
    args = ap.parse_args()

    reports = [bybit(args.symbol), binance(args.symbol)]
    render(reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
