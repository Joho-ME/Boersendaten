#!/usr/bin/env python3
"""Holt Tageskurse von Alpha Vantage und schreibt sie ins Repository.

Ausgabe:
  data/prices/<SYMBOL>.csv   Tagesverlauf (Datum, Open, High, Low, Close, Volume),
                             wird bei jedem Lauf zusammengeführt, die Historie wächst also.
  data/latest.json           Momentaufnahme mit Kennzahlen je Symbol, Devisen und Fehlern.

Nur Standardbibliothek, damit die GitHub Action nichts installieren muss.
Der API-Schlüssel kommt aus der Umgebungsvariable ALPHAVANTAGE_API_KEY (GitHub Secret).
"""

import csv
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "config" / "watchlist.json"
PRICES_DIR = ROOT / "data" / "prices"
LATEST = ROOT / "data" / "latest.json"

API_URL = "https://www.alphavantage.co/query"
PAUSE_SECONDS = 13  # Free-Tier: max. 5 Abfragen pro Minute
DAILY_BUDGET = 25   # Free-Tier: max. 25 Abfragen pro Tag

calls_made = 0


class ApiError(Exception):
    pass


def api_call(params: dict) -> dict:
    """Eine Abfrage mit Pause und Prüfung auf Limit- und Fehlermeldungen."""
    global calls_made
    if calls_made >= DAILY_BUDGET:
        raise ApiError("Tagesbudget von 25 Abfragen erreicht, Abfrage übersprungen")
    if calls_made > 0:
        time.sleep(PAUSE_SECONDS)
    params = dict(params, apikey=os.environ["ALPHAVANTAGE_API_KEY"])
    url = API_URL + "?" + urllib.parse.urlencode(params)
    calls_made += 1
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for key in ("Error Message", "Note", "Information"):
        if key in data:
            raise ApiError(f"{key}: {data[key]}")
    return data


def safe_name(symbol: str) -> str:
    return symbol.replace("/", "_").replace(":", "_")


def load_history(symbol: str) -> dict:
    path = PRICES_DIR / f"{safe_name(symbol)}.csv"
    rows = {}
    if path.exists():
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                rows[row["date"]] = row
    return rows


def save_history(symbol: str, rows: dict) -> None:
    path = PRICES_DIR / f"{safe_name(symbol)}.csv"
    fields = ["date", "open", "high", "low", "close", "volume"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for date in sorted(rows):
            writer.writerow({k: rows[date][k] for k in fields})


def fetch_daily(symbol: str) -> dict:
    data = api_call({"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": "compact"})
    series = data.get("Time Series (Daily)")
    if not series:
        raise ApiError(f"Keine Tagesdaten in der Antwort: {list(data)[:3]}")
    rows = {}
    for date, v in series.items():
        rows[date] = {
            "date": date,
            "open": v["1. open"],
            "high": v["2. high"],
            "low": v["3. low"],
            "close": v["4. close"],
            "volume": v["5. volume"],
        }
    return rows


def fetch_sma200(symbol: str):
    data = api_call({"function": "SMA", "symbol": symbol, "interval": "daily",
                     "time_period": 200, "series_type": "close"})
    series = data.get("Technical Analysis: SMA")
    if not series:
        raise ApiError("Keine SMA-Daten in der Antwort")
    last_date = max(series)
    return last_date, float(series[last_date]["SMA"])


def pct(a: float, b: float):
    return round((a / b - 1) * 100, 2) if b else None


def metrics(rows: dict) -> dict:
    dates = sorted(rows)
    closes = [float(rows[d]["close"]) for d in dates]
    last = closes[-1]

    def ret(days):
        return pct(last, closes[-1 - days]) if len(closes) > days else None

    out = {
        "datum": dates[-1],
        "schluss": last,
        "veraenderung_1t_pct": ret(1),
        "veraenderung_5t_pct": ret(5),
        "veraenderung_1m_pct": ret(21),
        "veraenderung_3m_pct": ret(63),
        "veraenderung_6m_pct": ret(126),
        "veraenderung_12m_pct": ret(252),
        "historie_tage": len(closes),
    }
    if len(closes) >= 50:
        sma50 = sum(closes[-50:]) / 50
        out["sma50"] = round(sma50, 4)
        out["abstand_sma50_pct"] = pct(last, sma50)
    if len(closes) >= 21:
        daily = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 20, len(closes))]
        out["volatilitaet_20t_pct"] = round(statistics.stdev(daily) * 100, 2)
        weekly_moves = [abs(pct(closes[i], closes[i - 5])) for i in range(len(closes) - 15, len(closes))]
        out["typische_wochenschwankung_pct"] = round(statistics.median(weekly_moves), 2)
    out["hoch_100t"] = max(closes[-100:])
    out["tief_100t"] = min(closes[-100:])
    return out


def main() -> int:
    if not os.environ.get("ALPHAVANTAGE_API_KEY"):
        print("ALPHAVANTAGE_API_KEY fehlt", file=sys.stderr)
        return 1

    config = json.loads(WATCHLIST.read_text())
    PRICES_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "erzeugt_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "quelle": "Alpha Vantage (Tagesdaten, Schlusskurse in Handelswährung)",
        "symbole": {},
        "devisen": {},
        "fehler": [],
    }

    for item in config["symbole"]:
        symbol = item["symbol"]
        entry = {"name": item["name"], "rolle": item["rolle"]}
        try:
            history = load_history(symbol)
            history.update(fetch_daily(symbol))
            save_history(symbol, history)
            entry.update(metrics(history))
        except (ApiError, OSError, ValueError, KeyError) as exc:
            result["fehler"].append(f"{symbol} Tagesdaten: {exc}")
            entry["fehler"] = str(exc)
            result["symbole"][symbol] = entry
            continue

        if item.get("sma200"):
            try:
                sma_date, sma = fetch_sma200(symbol)
                entry["sma200"] = round(sma, 4)
                entry["sma200_datum"] = sma_date
                entry["abstand_sma200_pct"] = pct(entry["schluss"], sma)
            except (ApiError, OSError, ValueError, KeyError) as exc:
                result["fehler"].append(f"{symbol} SMA200: {exc}")
        result["symbole"][symbol] = entry

    for fx in config.get("devisen", []):
        pair = f"{fx['von']}/{fx['nach']}"
        try:
            data = api_call({"function": "FX_DAILY", "from_symbol": fx["von"], "to_symbol": fx["nach"]})
            series = data["Time Series FX (Daily)"]
            d = max(series)
            result["devisen"][pair] = {"datum": d, "schluss": float(series[d]["4. close"])}
        except (ApiError, OSError, ValueError, KeyError) as exc:
            result["fehler"].append(f"{pair}: {exc}")

    result["abfragen_verbraucht"] = calls_made
    LATEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Nur scheitern, wenn gar nichts geladen wurde
    ok = any("schluss" in v for v in result["symbole"].values())
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
