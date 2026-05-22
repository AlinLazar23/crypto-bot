"""
Advanced Personal Crypto Bot
==============================
Features:
- Personal portfolio tracking with P&L
- Whale tracker (large transactions)
- Daily personalized report
- EMA crossover alerts
- Multi-language (RO/EN)
- Per-user settings

Requirements:
    pip install python-telegram-bot[job-queue] requests pytz
"""

import os
import json
import time
import asyncio
import logging
import datetime
import requests
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
DATA_DIR       = "/data" if os.path.isdir("/data") else "."
DATA_FILE      = os.path.join(DATA_DIR, "user_data.json")
CHECK_INTERVAL = 60

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── TRANSLATIONS ──────────────────────────────────────────────────────────────
T = {
    "ro": {
        "welcome":            "Bun venit la CryptoPersonal Bot!\n\nBotul tau personal de crypto cu portofoliu, alerte tehnice si rapoarte zilnice.\n\nApasa /help pentru comenzi.",
        "portfolio_empty":    "Portofoliul tau este gol.\nFoloseste /portfolio add BTC 0.5 45000",
        "portfolio_added":    "Adaugat in portofoliu: {} {} la pretul de {}",
        "portfolio_removed":  "Sters din portofoliu: {}",
        "portfolio_not_found":"{} nu este in portofoliu.",
        "watchlist_empty":    "Watchlist-ul tau este gol.\nFoloseste /watchlist add BTC",
        "watchlist_added":    "{} adaugat in watchlist.",
        "watchlist_removed":  "{} sters din watchlist.",
        "loading":            "Se incarca...",
        "no_data":            "Nu s-au putut obtine datele. Incearca din nou.",
        "lang_set":           "Limba setata: Romana",
        "currency_set":       "Moneda setata: {}",
        "report_set":         "Raportul zilnic va fi trimis la {}",
        "report_title":       "Raport Zilnic Personal",
        "alert_fear_set":     "Alerta Fear & Greed setata: sub {}",
        "alerts_empty":       "Nu ai alerte active.",
        "pnl_empty":          "Nu ai monede in portofoliu pentru P&L.",
    },
    "en": {
        "welcome":            "Welcome to CryptoPersonal Bot!\n\nYour personal crypto bot with portfolio tracking, technical alerts and daily reports.\n\nPress /help for commands.",
        "portfolio_empty":    "Your portfolio is empty.\nUse /portfolio add BTC 0.5 45000",
        "portfolio_added":    "Added to portfolio: {} {} at {}",
        "portfolio_removed":  "Removed from portfolio: {}",
        "portfolio_not_found":"{} is not in your portfolio.",
        "watchlist_empty":    "Your watchlist is empty.\nUse /watchlist add BTC",
        "watchlist_added":    "{} added to watchlist.",
        "watchlist_removed":  "{} removed from watchlist.",
        "loading":            "Loading...",
        "no_data":            "Could not fetch data. Try again.",
        "lang_set":           "Language set: English",
        "currency_set":       "Currency set: {}",
        "report_set":         "Daily report will be sent at {}",
        "report_title":       "Daily Personal Report",
        "alert_fear_set":     "Fear & Greed alert set: below {}",
        "alerts_empty":       "You have no active alerts.",
        "pnl_empty":          "No coins in portfolio for P&L.",
    }
}

def t(uid, key, *args):
    lang = get_user(uid).get("lang", "ro")
    text = T.get(lang, T["ro"]).get(key, key)
    if args:
        try:
            text = text.format(*args)
        except Exception:
            pass
    return text

# ─── USER DATA ─────────────────────────────────────────────────────────────────

JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "")
JSONBIN_BIN_ID  = os.environ.get("JSONBIN_BIN_ID", "")
JSONBIN_URL     = "https://api.jsonbin.io/v3/b/"

def load_data():
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try:
            r = requests.get(
                JSONBIN_URL + JSONBIN_BIN_ID + "/latest",
                headers={"X-Master-Key": JSONBIN_API_KEY},
                timeout=10,
            )
            if r.status_code == 200:
                raw = r.json().get("record", {})
                logger.info("Data loaded from JSONBin")
                return {int(k): v for k, v in raw.items() if k != "init"}
        except Exception as e:
            logger.error("JSONBin load error: " + str(e))
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
        except Exception as e:
            logger.error("load_data error: " + str(e))
    return {}

def save_data():
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try:
            r = requests.put(
                JSONBIN_URL + JSONBIN_BIN_ID,
                json=user_data,
                headers={
                    "X-Master-Key": JSONBIN_API_KEY,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if r.status_code == 200:
                return
            logger.error("JSONBin save error: " + str(r.status_code))
        except Exception as e:
            logger.error("JSONBin save error: " + str(e))
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(user_data, f, indent=2)
    except Exception as e:
        logger.error("save_data error: " + str(e))

user_data = load_data()

def get_user(uid):
    uid = int(uid)
    if uid not in user_data:
        user_data[uid] = {
            "lang":           "ro",
            "currency":       "USD",
            "portfolio":      {},
            "watchlist":      [],
            "alerts":         {"ema": {}, "fear": None},
            "report_time":    "08:00",
            "report_enabled": True,
        }
    # Ensure alerts structure exists
    if "alerts" not in user_data[uid]:
        user_data[uid]["alerts"] = {"ema": {}, "fear": None}
    if "ema" not in user_data[uid]["alerts"]:
        user_data[uid]["alerts"]["ema"] = {}
    return user_data[uid]

# ─── CACHE ─────────────────────────────────────────────────────────────────────
_cache = {}
CACHE_TTL     = 300
CACHE_TTL_EMA = 600

# State pentru ForceReply
_user_state = {}

def cache_get(key):
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None

def cache_set(key, data):
    _cache[key] = (data, time.time())

# ─── COIN SLUG MAP ─────────────────────────────────────────────────────────────
COIN_SLUG_MAP = {
    # Core
    "BTC": "bitcoin",           "ETH": "ethereum",          "SOL": "solana",
    "BNB": "binancecoin",       "XRP": "ripple",             "ADA": "cardano",
    "DOGE": "dogecoin",         "DOT": "polkadot",           "AVAX": "avalanche-2",
    "LINK": "chainlink",        "ALGO": "algorand",          "SUI": "sui",
    "ARB": "arbitrum",          "FET": "fetch-ai",           "EGLD": "elrond-erd-2",
    "HYPE": "hyperliquid",      "VIRTUAL": "virtual-protocol",
    # Top 100 CoinGecko
    "ZEC": "zcash",             "XMR": "monero",             "TON": "the-open-network",
    "XLM": "stellar",           "LTC": "litecoin",           "DAI": "dai",
    "HBAR": "hedera-hashgraph", "SHIB": "shiba-inu",         "CRO": "crypto-com-chain",
    "TAO": "bittensor",         "UNI": "uniswap",            "MNT": "mantle",
    "NEAR": "near",             "ONDO": "ondo-finance",      "OKB": "okb",
    "ICP": "internet-computer", "AAVE": "aave",              "ETC": "ethereum-classic",
    "QNT": "quant-network",     "ENA": "ethena",             "ATOM": "cosmos",
    "KAS": "kaspa",             "POL": "polygon-ecosystem-token", "RENDER": "render-token",
    "WLD": "worldcoin-wld",     "APT": "aptos",              "FIL": "filecoin",
    "JUP": "jupiter-exchange-solana", "VET": "vechain",      "BONK": "bonk",
    "PENGU": "pudgy-penguins",  "ASTER": "aster-2",          "PUMP": "pump-fun",
    "WLFI": "world-liberty-financial",
}

def resolve_slug(symbol):
    return COIN_SLUG_MAP.get(symbol.upper(), symbol.lower())


# ─── MONEDE PREDEFINITE ────────────────────────────────────────────────────────
# Adauga sau sterge monede din aceasta lista dupa preferinta
PREDEFINED_COINS = [
    "BTC",  "ETH",  "SOL",   "BNB",   "XRP",
    "ADA",  "DOGE", "AVAX",  "LINK",  "DOT",
    "ALGO", "SUI",  "ARB",   "FET",   "HYPE",
    "EGLD", "VIRTUAL",
    # Top 100
    "ZEC",  "XMR",  "TON",   "XLM",   "LTC",
    "DAI",  "HBAR", "SHIB",  "CRO",   "TAO",
    "UNI",  "MNT",  "NEAR",  "ONDO",  "OKB",
    "ICP",  "AAVE", "ETC",   "QNT",   "ENA",
    "ATOM", "KAS",  "POL",   "RENDER","WLD",
    "APT",  "FIL",  "JUP",   "VET",   "BONK",
    "PENGU","ASTER","PUMP",  "WLFI",
]
# ─── SECTOARE ──────────────────────────────────────────────────────────────────
SECTORS = {
    "ai":      ("artificial-intelligence",    "AI & Big Data"),
    "defi":    ("decentralized-finance-defi", "DeFi"),
    "gaming":  ("gaming",                     "Gaming & GameFi"),
    "layer1":  ("layer-1",                    "Layer 1"),
    "layer2":  ("layer-2",                    "Layer 2"),
    "rwa":     ("real-world-assets-rwa",      "Real World Assets"),
    "privacy": ("privacy-coins",              "Privacy Coins"),
}

# ─── CURRENCY ──────────────────────────────────────────────────────────────────
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "RON": "RON "}

def get_currency_rate(currency):
    if currency == "USD":
        return 1.0
    cached = cache_get("rate:" + currency)
    if cached:
        return cached
    try:
        r = requests.get(
            COINGECKO_BASE + "/simple/price",
            params={"ids": "tether", "vs_currencies": currency.lower()},
            timeout=8,
        )
        if r.status_code == 200:
            rate = r.json().get("tether", {}).get(currency.lower(), 1.0)
            cache_set("rate:" + currency, rate)
            return rate
    except Exception:
        pass
    return 1.0

def fmt_currency(value, currency="USD"):
    rate = get_currency_rate(currency)
    converted = value * rate
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    if converted >= 1:
        return symbol + "{:,.2f}".format(converted)
    return symbol + "{:.6f}".format(converted)

def fmt_price(value):
    if value is None:
        return "N/A"
    try:
        if value >= 1:
            return "$" + "{:,.2f}".format(value)
        return "$" + "{:.6f}".format(value)
    except Exception:
        return "N/A"

def fmt_pct(value):
    if value is None:
        return "N/A"
    sign  = "+" if value >= 0 else ""
    emoji = "🟢" if value >= 0 else "🔴"
    return emoji + " " + sign + "{:.2f}%".format(value)

def fmt_large(value):
    try:
        if value >= 1000000000:
            return "$" + "{:.2f}B".format(value / 1000000000)
        if value >= 1000000:
            return "$" + "{:.1f}M".format(value / 1000000)
        if value >= 1000:
            return "$" + "{:.1f}K".format(value / 1000)
        return "$" + "{:,.2f}".format(value)
    except Exception:
        return "N/A"

# ─── COINGECKO API ─────────────────────────────────────────────────────────────

def cg_get(endpoint, params=None, timeout=15):
    for attempt in range(3):
        if attempt > 0:
            time.sleep(8)
        try:
            r = requests.get(
                COINGECKO_BASE + endpoint,
                params=params,
                timeout=timeout,
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 30)))
                continue
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.error("cg_get error: " + str(e))
    return None

def get_price(slug):
    cached = cache_get("price:" + slug)
    if cached:
        return cached
    data = cg_get("/simple/price", params={
        "ids": slug, "vs_currencies": "usd",
        "include_24hr_change": "true", "include_market_cap": "true",
    })
    if data and slug in data:
        result = {
            "price":      data[slug].get("usd", 0),
            "change_24h": data[slug].get("usd_24h_change", 0),
            "market_cap": data[slug].get("usd_market_cap", 0),
        }
        cache_set("price:" + slug, result)
        return result
    return None

def get_current_price_simple(slug):
    pd = get_price(slug)
    return pd["price"] if pd else None

def get_prices_batch(slugs):
    if not slugs:
        return {}
    uncached = [s for s in slugs if not cache_get("price:" + s)]
    if uncached:
        data = cg_get("/simple/price", params={
            "ids": ",".join(uncached), "vs_currencies": "usd",
            "include_24hr_change": "true", "include_market_cap": "true",
        })
        if data:
            for slug in uncached:
                if slug in data:
                    result = {
                        "price":      data[slug].get("usd", 0),
                        "change_24h": data[slug].get("usd_24h_change", 0),
                        "market_cap": data[slug].get("usd_market_cap", 0),
                    }
                    cache_set("price:" + slug, result)
    return {s: cache_get("price:" + s) for s in slugs}

def get_fear_greed(fresh=False):
    if not fresh:
        cached = cache_get("fear_greed")
        if cached:
            return cached
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=2", timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                result = {
                    "value":     int(data[0]["value"]),
                    "label":     data[0]["value_classification"],
                    "yesterday": int(data[1]["value"]) if len(data) > 1 else int(data[0]["value"]),
                }
                cache_set("fear_greed", result)
                return result
    except Exception as e:
        logger.error("get_fear_greed error: " + str(e))
    return None

def get_fear_greed_stats():
    cached = cache_get("fear_greed_stats")
    if cached:
        return cached
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=8", timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                week_vals = [int(d["value"]) for d in data]
                result = {
                    "value":     int(data[0]["value"]),
                    "label":     data[0]["value_classification"],
                    "yesterday": int(data[1]["value"]) if len(data) > 1 else int(data[0]["value"]),
                    "week_avg":  round(sum(week_vals) / len(week_vals), 1),
                }
                cache_set("fear_greed_stats", result)
                return result
    except Exception as e:
        logger.error("get_fear_greed_stats error: " + str(e))
    return None

def get_ema(slug, period=200, timeframe="daily"):
    cache_key = "ema:" + slug + ":" + str(period) + ":" + timeframe
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if time.time() - ts < CACHE_TTL_EMA:
            return data
    try:
        data = cg_get("/coins/" + slug + "/market_chart",
                      params={"vs_currency": "usd", "days": "365", "interval": "daily"})
        if not data or "prices" not in data:
            return None
        prices = [p[1] for p in data["prices"]]
        if not prices:
            return None
        effective_period = min(period, len(prices))
        k   = 2 / (effective_period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = price * k + ema * (1 - k)
        ema = round(ema, 2)
        cache_set(cache_key, ema)
        return ema
    except Exception as e:
        logger.error("get_ema error: " + str(e))
    return None

def get_trending_coins():
    cached = cache_get("trending")
    if cached is not None:
        for coin in cached:
            if "change_24h" not in coin["item"]:
                coin["item"]["change_24h"] = 0
        return cached
    try:
        r = requests.get(
            COINGECKO_BASE + "/search/trending",
            timeout=10,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        if r.status_code != 200:
            return []
        coins = r.json().get("coins", [])
        for coin in coins:
            item = coin["item"]
            try:
                chg = item["data"]["price_change_percentage_24h"]["usd"]
                item["change_24h"] = round(chg, 2)
            except Exception:
                item["change_24h"] = 0
        cache_set("trending", coins)
        return coins
    except Exception as e:
        logger.error("get_trending_coins error: " + str(e))
    return []

def get_global_market():
    cached = cache_get("global_market")
    if cached:
        return cached
    data = cg_get("/global")
    if not data:
        return None
    d = data.get("data", {})
    result = {
        "total_market_cap":      d.get("total_market_cap", {}).get("usd", 0),
        "total_volume_24h":      d.get("total_volume", {}).get("usd", 0),
        "btc_dominance":         round(d.get("market_cap_percentage", {}).get("btc", 0), 2),
        "eth_dominance":         round(d.get("market_cap_percentage", {}).get("eth", 0), 2),
        "market_cap_change_24h": d.get("market_cap_change_percentage_24h_usd", 0),
    }
    cache_set("global_market", result)
    return result

def get_btc_eth_prices():
    cached = cache_get("btc_eth_prices")
    if cached:
        return cached
    data = cg_get("/coins/markets", params={
        "vs_currency": "usd", "ids": "bitcoin,ethereum",
        "order": "market_cap_desc", "per_page": 2, "page": 1, "sparkline": "false",
    })
    if not data:
        return {}
    result = {}
    for c in data:
        if c["id"] == "bitcoin":
            result["btc_price"]  = c.get("current_price", 0)
            result["btc_change"] = c.get("price_change_percentage_24h") or 0
        elif c["id"] == "ethereum":
            result["eth_price"]  = c.get("current_price", 0)
            result["eth_change"] = c.get("price_change_percentage_24h") or 0
    cache_set("btc_eth_prices", result)
    return result

def get_sector_coins(category_id, limit=15):
    cached = cache_get("sector:" + category_id)
    if cached:
        return cached
    # Sector coins au cache TTL mai mare (10 min) ca sa nu faca request la fiecare click
    try:
        r = requests.get(
            COINGECKO_BASE + "/coins/markets",
            params={
                "vs_currency": "usd", "category": category_id,
                "order": "market_cap_desc", "per_page": limit,
                "page": 1, "sparkline": "false",
            },
            timeout=10,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            result = [{
                "symbol":     c["symbol"].upper(),
                "name":       c["name"],
                "price":      c.get("current_price", 0),
                "change_24h": c.get("price_change_percentage_24h") or 0,
                "rank":       c.get("market_cap_rank", "?"),
            } for c in r.json()]
            # Cache 10 minute pentru sectoare
            _cache["sector:" + category_id] = (result, time.time() - CACHE_TTL + 600)
            return result
        elif r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 15)))
    except Exception as e:
        logger.error("get_sector_coins error: " + str(e))
    return []

# ─── STATS FORMAT ──────────────────────────────────────────────────────────────

def fng_bar(value):
    filled = value // 10
    return "█" * filled + "░" * (10 - filled)

def format_stats_full(fg, global_data, prices, lang="ro"):
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    year    = utc_now.year
    march_last = max(datetime.datetime(year, 3, day, 1, tzinfo=datetime.timezone.utc)
                     for day in range(25, 32) if datetime.datetime(year, 3, day).weekday() == 6)
    oct_last   = max(datetime.datetime(year, 10, day, 1, tzinfo=datetime.timezone.utc)
                     for day in range(25, 32) if datetime.datetime(year, 10, day).weekday() == 6)
    ro_offset  = datetime.timedelta(hours=3) if march_last <= utc_now < oct_last else datetime.timedelta(hours=2)
    ro_label   = "EEST" if march_last <= utc_now < oct_last else "EET"
    now        = (utc_now + ro_offset).strftime("%H:%M " + ro_label + " (%d.%m.%Y)")
    fng_val   = fg["value"]
    fng_trend = fng_val - fg["yesterday"]
    if fng_trend > 0:
        trend_str = ("sus +" if lang == "ro" else "up +") + str(fng_trend)
    elif fng_trend < 0:
        trend_str = ("jos " if lang == "ro" else "down ") + str(fng_trend)
    else:
        trend_str = "stabil" if lang == "ro" else "stable"
    bar = fng_bar(fng_val)
    if fng_val <= 25:   fe = "😱"
    elif fng_val <= 45: fe = "😰"
    elif fng_val <= 55: fe = "😐"
    elif fng_val <= 75: fe = "😄"
    else:               fe = "🤑"
    if lang == "ro":
        if fng_val <= 20:   interp = "Panica extrema - zona istorica de acumulare"
        elif fng_val <= 40: interp = "Frica in piata - posibila oportunitate"
        elif fng_val <= 60: interp = "Piata neutra - asteapta confirmare"
        elif fng_val <= 80: interp = "Lacomie - fii precaut"
        else:               interp = "Euforie extrema - risc de corectie"
    else:
        if fng_val <= 20:   interp = "Extreme panic - historic accumulation zone"
        elif fng_val <= 40: interp = "Fear in market - possible opportunity"
        elif fng_val <= 60: interp = "Neutral market - wait for confirmation"
        elif fng_val <= 80: interp = "Greed - be cautious"
        else:               interp = "Extreme euphoria - correction risk"
    score = 5.0
    cap_chg = global_data.get("market_cap_change_24h", 0)
    btc_chg = prices.get("btc_change", 0)
    if fng_val <= 20:   score += 1.5
    elif fng_val <= 40: score += 0.5
    elif fng_val >= 80: score -= 1.5
    elif fng_val >= 60: score -= 0.5
    if cap_chg > 3:    score += 1.0
    elif cap_chg > 1:  score += 0.5
    elif cap_chg < -3: score -= 1.0
    elif cap_chg < -1: score -= 0.5
    if btc_chg > 3:    score += 0.5
    elif btc_chg < -3: score -= 0.5
    score = max(1, min(10, round(score)))
    score_bar = "X" * score + "." * (10 - score)
    if lang == "ro":
        if score <= 3:   slabel = "Bearish"
        elif score <= 4: slabel = "Slab Bearish"
        elif score <= 6: slabel = "Neutru"
        elif score <= 8: slabel = "Bullish"
        else:            slabel = "Strong Bullish"
    else:
        if score <= 3:   slabel = "Bearish"
        elif score <= 4: slabel = "Weak Bearish"
        elif score <= 6: slabel = "Neutral"
        elif score <= 8: slabel = "Bullish"
        else:            slabel = "Strong Bullish"
    cap_a = "🟢" if cap_chg >= 0 else "🔴"
    btc_a = "🟢" if btc_chg >= 0 else "🔴"
    eth_a = "🟢" if prices.get("eth_change", 0) >= 0 else "🔴"
    if lang == "ro":
        return (
            "Market Stats - " + now + "\n\n"
            "SENTIMENT PIATA\n"
            + fe + " Fear & Greed: " + str(fng_val) + "/100 - " + fg["label"] + "\n"
            "[" + bar + "]\n"
            "Fata de ieri: " + trend_str + "\n"
            "Media 7 zile: " + str(fg.get("week_avg", "N/A")) + "/100\n"
            + interp + "\n\n"
            "OVERVIEW PIATA\n"
            "BTC:  " + fmt_price(prices.get("btc_price", 0)) + "  " + btc_a + " " + "{:.1f}%".format(abs(btc_chg)) + "\n"
            "ETH:  " + fmt_price(prices.get("eth_price", 0)) + "  " + eth_a + " " + "{:.1f}%".format(abs(prices.get("eth_change", 0))) + "\n"
            "Mkt Cap: " + fmt_large(global_data.get("total_market_cap", 0)) + "  " + cap_a + " " + "{:.1f}%".format(abs(cap_chg)) + "\n"
            "Volum 24h: " + fmt_large(global_data.get("total_volume_24h", 0)) + "\n"
            "BTC Dominance: " + str(global_data.get("btc_dominance", 0)) + "%\n"
            "ETH Dominance: " + str(global_data.get("eth_dominance", 0)) + "%\n\n"
            "MARKET SCORE: " + str(score) + "/10 - " + slabel + "\n"
            "Bazat pe: sentiment + trend + volum + dominance"
        )
    else:
        return (
            "Market Stats - " + now + "\n\n"
            "MARKET SENTIMENT\n"
            + fe + " Fear & Greed: " + str(fng_val) + "/100 - " + fg["label"] + "\n"
            "[" + bar + "]\n"
            "vs yesterday: " + trend_str + "\n"
            "7-day avg: " + str(fg.get("week_avg", "N/A")) + "/100\n"
            + interp + "\n\n"
            "MARKET OVERVIEW\n"
            "BTC:  " + fmt_price(prices.get("btc_price", 0)) + "  " + btc_a + " " + "{:.1f}%".format(abs(btc_chg)) + "\n"
            "ETH:  " + fmt_price(prices.get("eth_price", 0)) + "  " + eth_a + " " + "{:.1f}%".format(abs(prices.get("eth_change", 0))) + "\n"
            "Mkt Cap: " + fmt_large(global_data.get("total_market_cap", 0)) + "  " + cap_a + " " + "{:.1f}%".format(abs(cap_chg)) + "\n"
            "Volume 24h: " + fmt_large(global_data.get("total_volume_24h", 0)) + "\n"
            "BTC Dominance: " + str(global_data.get("btc_dominance", 0)) + "%\n"
            "ETH Dominance: " + str(global_data.get("eth_dominance", 0)) + "%\n\n"
            "MARKET SCORE: " + str(score) + "/10 - " + slabel + "\n"
            "Based on: sentiment + trend + volume + dominance"
        )

# ─── PORTFOLIO HELPERS ─────────────────────────────────────────────────────────

def calculate_portfolio(uid):
    user      = get_user(uid)
    portfolio = user.get("portfolio", {})
    if not portfolio:
        return None

    # Batch request pentru toate monedele dintr-o data
    slugs = [info.get("slug", resolve_slug(symbol)) for symbol, info in portfolio.items()]
    prices_data = {}
    try:
        r = requests.get(
            COINGECKO_BASE + "/simple/price",
            params={
                "ids": ",".join(slugs),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            prices_data = r.json()
    except Exception as e:
        logger.error("portfolio batch error: " + str(e))

    total_value = total_invested = 0
    coins_data  = []
    for symbol, info in portfolio.items():
        slug      = info.get("slug", resolve_slug(symbol))
        amount    = float(info.get("amount", 0))
        buy_price = float(info.get("buy_price", 0))
        pd        = prices_data.get(slug, {})
        if not pd:
            continue
        cur_price = pd.get("usd", 0)
        change_24h = pd.get("usd_24h_change", 0)
        cur_val   = amount * cur_price
        invested  = amount * buy_price
        pnl       = cur_val - invested
        pnl_pct   = ((cur_price - buy_price) / buy_price * 100) if buy_price > 0 else 0
        total_value    += cur_val
        total_invested += invested
        coins_data.append({
            "symbol": symbol, "amount": amount, "buy_price": buy_price,
            "current_price": cur_price, "current_value": cur_val,
            "invested": invested, "pnl": pnl, "pnl_pct": pnl_pct,
            "change_24h": change_24h,
        })
    total_pnl     = total_value - total_invested
    total_pnl_pct = ((total_pnl / total_invested) * 100) if total_invested > 0 else 0
    return {
        "coins": coins_data, "total_value": total_value,
        "total_invested": total_invested, "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct, "currency": user.get("currency", "USD"),
    }


# ─── DAILY REPORT ──────────────────────────────────────────────────────────────

async def generate_report(uid):
    user     = get_user(uid)
    lang     = user.get("lang", "ro")
    currency = user.get("currency", "USD")
    now      = datetime.datetime.now(pytz.timezone("Europe/Bucharest"))
    lines    = ["=== " + t(uid, "report_title") + " ===", now.strftime("%d.%m.%Y %H:%M"), ""]

    fg = get_fear_greed()
    if fg:
        fe = "😱" if fg["value"] <= 25 else ("😰" if fg["value"] <= 45 else ("😐" if fg["value"] <= 55 else ("😄" if fg["value"] <= 75 else "🤑")))
        trend = " (sus)" if fg["value"] > fg["yesterday"] else (" (jos)" if fg["value"] < fg["yesterday"] else "")
        lines += ["SENTIMENT PIATA" if lang == "ro" else "MARKET SENTIMENT",
                  fe + " Fear & Greed: " + str(fg["value"]) + "/100 - " + fg["label"] + trend, ""]

    pf = calculate_portfolio(uid)
    if pf and pf["coins"]:
        lines += ["PORTOFOLIU" if lang == "ro" else "PORTFOLIO",
                  ("Valoare totala: " if lang == "ro" else "Total value: ") + fmt_currency(pf["total_value"], currency),
                  "P&L: " + fmt_currency(pf["total_pnl"], currency) + " (" + fmt_pct(pf["total_pnl_pct"]) + ")", ""]
        for c in pf["coins"]:
            lines.append(c["symbol"] + ": " + fmt_currency(c["current_value"], currency) + " | 24h: " + fmt_pct(c["change_24h"]))
        lines.append("")

    watchlist = user.get("watchlist", [])
    if watchlist:
        slugs = [resolve_slug(s) for s in watchlist]
        prices = get_prices_batch(slugs)
        lines.append("WATCHLIST")
        for symbol, slug in zip(watchlist, slugs):
            pd = prices.get(slug)
            if pd:
                lines.append(symbol + ": " + fmt_price(pd["price"]) + " | " + fmt_pct(pd.get("change_24h", 0)) + " (24h)")
        lines.append("")

    lines += ["---", "/portfolio | /watchlist"]
    return "\n".join(lines)

# ─── HELP MENU ─────────────────────────────────────────────────────────────────

def help_main_keyboard(lang="ro"):
    if lang == "ro":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Portofoliu",  callback_data="help_portfolio"),
             InlineKeyboardButton("👁 Watchlist",   callback_data="help_watchlist")],
            [InlineKeyboardButton("🔔 Alerte",      callback_data="help_alerts"),
             InlineKeyboardButton("📊 Rapoarte",    callback_data="help_reports")],
            [InlineKeyboardButton("📈 Piata",       callback_data="help_market"),
             InlineKeyboardButton("⚙️ Setari",      callback_data="help_settings")],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Portfolio",   callback_data="help_portfolio"),
             InlineKeyboardButton("👁 Watchlist",   callback_data="help_watchlist")],
            [InlineKeyboardButton("🔔 Alerts",      callback_data="help_alerts"),
             InlineKeyboardButton("📊 Reports",     callback_data="help_reports")],
            [InlineKeyboardButton("📈 Market",      callback_data="help_market"),
             InlineKeyboardButton("⚙️ Settings",    callback_data="help_settings")],
        ])

def back_keyboard(lang="ro"):
    label = "⬅️ Inapoi" if lang == "ro" else "⬅️ Back"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data="help_back")]])

def get_help_keyboards(lang="ro"):
    """Returns translated help keyboards based on user language."""
    back = "⬅️ Inapoi" if lang == "ro" else "⬅️ Back"
    return {
        "help_portfolio": {
            "title": "📁 Portofoliu" if lang == "ro" else "📁 Portfolio",
            "keyboard": [
                [InlineKeyboardButton("📊 Vezi Portofoliu" if lang == "ro" else "📊 View Portfolio", callback_data="exec_portfolio")],
                [InlineKeyboardButton("📈 P&L Report",           callback_data="exec_pnl")],
                [InlineKeyboardButton("➕ Adauga Moneda" if lang == "ro" else "➕ Add Coin", callback_data="exec_pf_add_list")],
                [InlineKeyboardButton("➖ Sterge Moneda" if lang == "ro" else "➖ Remove Coin", callback_data="exec_pf_remove_list")],
                [InlineKeyboardButton(back, callback_data="help_back")],
            ]
        },
        "help_watchlist": {
            "title": "👁 Watchlist",
            "keyboard": [
                [InlineKeyboardButton("👁 Vezi Watchlist" if lang == "ro" else "👁 View Watchlist", callback_data="exec_watchlist")],
                [InlineKeyboardButton("➕ Adauga Moneda" if lang == "ro" else "➕ Add Coin", callback_data="exec_wl_add_list")],
                [InlineKeyboardButton("➖ Sterge Moneda" if lang == "ro" else "➖ Remove Coin", callback_data="exec_wl_remove_list")],
                [InlineKeyboardButton(back, callback_data="help_back")],
            ]
        },
        "help_alerts": {
            "title": "🔔 Alerte" if lang == "ro" else "🔔 Alerts",
            "keyboard": [
                [InlineKeyboardButton("🔔 Alertele Mele" if lang == "ro" else "🔔 My Alerts", callback_data="exec_alerts")],
                [InlineKeyboardButton("📈 Seteaza Alerta EMA" if lang == "ro" else "📈 Set EMA Alert", callback_data="exec_alert_ema_menu")],
                [InlineKeyboardButton("😱 Seteaza Alerta Fear" if lang == "ro" else "😱 Set Fear Alert", callback_data="exec_alert_fear_menu")],
                [InlineKeyboardButton(back, callback_data="help_back")],
            ]
        },
        "help_reports": {
            "title": "📊 Rapoarte" if lang == "ro" else "📊 Reports",
            "keyboard": [
                [InlineKeyboardButton("📊 Raport Acum" if lang == "ro" else "📊 Report Now", callback_data="exec_report")],
                [InlineKeyboardButton(back, callback_data="help_back")],
            ]
        },
        "help_market": {
            "title": "📈 Piata" if lang == "ro" else "📈 Market",
            "keyboard": [
                [InlineKeyboardButton("🔥 Trending", callback_data="exec_trending")],
                [InlineKeyboardButton("📊 Stats Piata" if lang == "ro" else "📊 Market Stats", callback_data="exec_stats")],
                [InlineKeyboardButton("🏭 Sectoare" if lang == "ro" else "🏭 Sectors", callback_data="exec_sector_list")],
                [InlineKeyboardButton(back, callback_data="help_back")],
            ]
        },
        "help_settings": {
            "title": "⚙️ Setari" if lang == "ro" else "⚙️ Settings",
            "keyboard": [
                [InlineKeyboardButton("🇷🇴 Limba Romana", callback_data="exec_lang_ro")],
                [InlineKeyboardButton("🇬🇧 English",      callback_data="exec_lang_en")],
                [InlineKeyboardButton("💵 USD", callback_data="exec_cur_USD"),
                 InlineKeyboardButton("💶 EUR", callback_data="exec_cur_EUR")],
                [InlineKeyboardButton("💷 GBP", callback_data="exec_cur_GBP"),
                 InlineKeyboardButton("🇷🇴 RON", callback_data="exec_cur_RON")],
                [InlineKeyboardButton(back, callback_data="help_back")],
            ]
        },
    }

# Keep HELP_KEYBOARDS as alias for compatibility
HELP_KEYBOARDS = get_help_keyboards("ro")

# ─── GROUP PRIVACY HELPERS ─────────────────────────────────────────────────────

async def _delete_cmd(update):
    if update.effective_chat.type in ("group", "supergroup"):
        try:
            await update.message.delete()
        except Exception:
            pass

async def _dm_or_reply(update, context, text, reply_markup=None):
    uid = update.effective_user.id
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text(text, reply_markup=reply_markup)
        return
    try:
        await context.bot.send_message(chat_id=uid, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"DM failed for uid={uid}: {e}")
        lang     = get_user(uid).get("lang", "ro")
        bot_info = await context.bot.get_me()
        name     = update.effective_user.first_name or "tu"
        btn      = "Primeste raspuns in privat" if lang == "ro" else "Get reply in private"
        notif_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(btn, url=f"https://t.me/{bot_info.username}?start=help")
        ]])
        chat_id = update.effective_chat.id
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=(f"{name}, porneste botul in privat pentru a primi raspunsuri:" if lang == "ro"
                  else f"{name}, start the bot in private to receive replies:"),
            reply_markup=notif_kb
        )
        async def _del(ctx):
            try:
                await ctx.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
            except Exception:
                pass
        context.job_queue.run_once(_del, 30)

# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────

async def cmd_start(update, context):
    uid = update.effective_user.id
    get_user(uid)
    save_data()
    lang = get_user(uid).get('lang', 'ro')
    keyboard = [
        [InlineKeyboardButton("📁 Portofoliu" if lang == 'ro' else "📁 Portfolio", callback_data="portfolio"),
         InlineKeyboardButton("👁 Watchlist",  callback_data="watchlist")],
        [InlineKeyboardButton("📊 Report",     callback_data="report"),
         InlineKeyboardButton("❓ Help",        callback_data="help_back")],
    ]
    await update.message.reply_text(t(uid, "welcome"), reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_help(update, context):
    uid     = update.effective_user.id
    lang    = get_user(uid).get("lang", "ro")
    chat_id = update.effective_chat.id

    logger.info(f"cmd_help: uid={uid}, chat_id={chat_id}, type={update.effective_chat.type}")

    if update.effective_chat.type in ("group", "supergroup"):
        # Sterge comanda /help din grup imediat
        try:
            await update.message.delete()
        except Exception:
            pass

        # Incearca sa trimita DM
        try:
            await context.bot.send_message(
                chat_id=uid,
                text="Alege o categorie:" if lang == "ro" else "Choose a category:",
                reply_markup=help_main_keyboard(lang)
            )
        except Exception as e:
            logger.warning(f"cmd_help DM failed for uid={uid}: {e}")
            # Utilizatorul nu a pornit botul in privat - trimite notificare cu deep-link
            bot_info = await context.bot.get_me()
            name = update.effective_user.first_name or "tu"
            btn  = "Primeste help in privat" if lang == "ro" else "Get help in private"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(btn, url=f"https://t.me/{bot_info.username}?start=help")
            ]])
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"{name}, apasa butonul pentru a porni botul in privat:"
                if lang == "ro" else
                f"{name}, press the button to start the bot in private:",
                reply_markup=keyboard
            )
            # Sterge notificarea din grup dupa 30 de secunde
            async def _delete_notification(ctx):
                try:
                    await ctx.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
                except Exception:
                    pass
            context.job_queue.run_once(_delete_notification, 30)
    else:
        await update.message.reply_text(
            "Alege o categorie:" if lang == "ro" else "Choose a category:",
            reply_markup=help_main_keyboard(lang)
        )

async def cmd_chatid(update, context):
    await update.message.reply_text(
        "Chat ID: " + str(update.effective_chat.id) + "\nUser ID: " + str(update.effective_user.id))

async def cmd_portfolio(update, context):
    uid  = update.effective_user.id
    user = get_user(uid)
    args = context.args
    await _delete_cmd(update)

    if args and args[0].lower() == "add":
        if len(args) < 3:
            await _dm_or_reply(update, context, "Usage: /portfolio add BTC 0.5 45000")
            return
        symbol = args[1].upper()
        try:
            amount    = float(args[2])
            buy_price = float(args[3]) if len(args) > 3 else 0
        except ValueError:
            await _dm_or_reply(update, context, "Numar invalid.")
            return
        user["portfolio"][symbol] = {"slug": resolve_slug(symbol), "amount": amount, "buy_price": buy_price}
        save_data()
        await _dm_or_reply(update, context, t(uid, "portfolio_added", symbol, amount, fmt_price(buy_price)))
        return

    if args and args[0].lower() == "remove":
        if len(args) < 2:
            await _dm_or_reply(update, context, "Usage: /portfolio remove BTC")
            return
        symbol = args[1].upper()
        if symbol in user["portfolio"]:
            del user["portfolio"][symbol]
            save_data()
            await _dm_or_reply(update, context, t(uid, "portfolio_removed", symbol))
        else:
            await _dm_or_reply(update, context, t(uid, "portfolio_not_found", symbol))
        return

    if not user.get("portfolio"):
        await _dm_or_reply(update, context, t(uid, "portfolio_empty"))
        return

    await _dm_or_reply(update, context, t(uid, "loading"))
    pf = calculate_portfolio(uid)
    if not pf:
        await _dm_or_reply(update, context, t(uid, "no_data"))
        return

    currency = user.get("currency", "USD")
    lines = ["Your Portfolio\n"]
    for c in pf["coins"]:
        lines.append(
            c["symbol"] + " x" + str(c["amount"]) + "\n"
            "  Value:  " + fmt_currency(c["current_value"], currency) + "\n"
            "  Price:  " + fmt_price(c["current_price"]) + "\n"
            "  24h:    " + fmt_pct(c["change_24h"]) + "\n"
            "  P&L:    " + fmt_currency(c["pnl"], currency) + " (" + fmt_pct(c["pnl_pct"]) + ")\n"
        )
    lines.append("\nTOTAL VALUE: " + fmt_currency(pf["total_value"], currency))
    lines.append("TOTAL P&L:   " + fmt_currency(pf["total_pnl"], currency) + " (" + fmt_pct(pf["total_pnl_pct"]) + ")")
    keyboard = [[InlineKeyboardButton("Refresh", callback_data="portfolio")]]
    await _dm_or_reply(update, context, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_pnl(update, context):
    uid = update.effective_user.id
    await _delete_cmd(update)
    if not get_user(uid).get("portfolio"):
        await _dm_or_reply(update, context, t(uid, "pnl_empty"))
        return
    await _dm_or_reply(update, context, t(uid, "loading"))
    pf = calculate_portfolio(uid)
    if not pf:
        await _dm_or_reply(update, context, t(uid, "no_data"))
        return
    currency = get_user(uid).get("currency", "USD")
    lines = ["P&L Report\n"]
    for c in sorted(pf["coins"], key=lambda x: x["pnl_pct"], reverse=True):
        emoji = "🟢" if c["pnl"] >= 0 else "🔴"
        lines.append(
            emoji + " " + c["symbol"] + "\n"
            "  Buy: " + fmt_price(c["buy_price"]) + " -> Now: " + fmt_price(c["current_price"]) + "\n"
            "  P&L: " + fmt_currency(c["pnl"], currency) + " (" + fmt_pct(c["pnl_pct"]) + ")\n"
        )
    emoji = "🟢" if pf["total_pnl"] >= 0 else "🔴"
    lines.append(emoji + " TOTAL: " + fmt_currency(pf["total_pnl"], currency) + " (" + fmt_pct(pf["total_pnl_pct"]) + ")")
    await _dm_or_reply(update, context, "\n".join(lines))

async def cmd_watchlist(update, context):
    uid  = update.effective_user.id
    user = get_user(uid)
    args = context.args
    await _delete_cmd(update)

    if args and args[0].lower() == "add":
        if len(args) < 2:
            await _dm_or_reply(update, context, "Usage: /watchlist add BTC")
            return
        symbol = args[1].upper()
        if symbol not in user["watchlist"]:
            user["watchlist"].append(symbol)
            save_data()
        await _dm_or_reply(update, context, t(uid, "watchlist_added", symbol))
        return

    if args and args[0].lower() == "remove":
        if len(args) < 2:
            await _dm_or_reply(update, context, "Usage: /watchlist remove BTC")
            return
        symbol = args[1].upper()
        if symbol in user["watchlist"]:
            user["watchlist"].remove(symbol)
            save_data()
        await _dm_or_reply(update, context, t(uid, "watchlist_removed", symbol))
        return

    if not user.get("watchlist"):
        await _dm_or_reply(update, context, t(uid, "watchlist_empty"))
        return

    await _dm_or_reply(update, context, t(uid, "loading"))
    slugs = [resolve_slug(s) for s in user["watchlist"]]
    prices_data = {}
    try:
        r = requests.get(
            COINGECKO_BASE + "/simple/price",
            params={
                "ids": ",".join(slugs),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            prices_data = r.json()
    except Exception as e:
        logger.error("watchlist batch error: " + str(e))
    lines = ["Watchlist\n"]
    for symbol in user["watchlist"]:
        slug = resolve_slug(symbol)
        pd   = prices_data.get(slug, {})
        if pd:
            price  = pd.get("usd", 0)
            change = pd.get("usd_24h_change", 0)
            lines.append(symbol + ": " + fmt_price(price) + "\n  24h: " + fmt_pct(change) + "\n")
        else:
            lines.append(symbol + ": N/A\n")
    keyboard = [[InlineKeyboardButton("Refresh", callback_data="watchlist")]]
    await _dm_or_reply(update, context, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_trending(update, context):
    await update.message.reply_text("Se incarca trending...")
    coins = get_trending_coins()
    if not coins:
        await update.message.reply_text("Nu s-au putut obtine datele.")
        return
    lines = ["Trending pe CoinGecko\n"]
    for item in coins[:7]:
        c         = item["item"]
        rank      = c.get("market_cap_rank", "?")
        chg       = c.get("change_24h", 0)
        chg_emoji = "🟢" if chg >= 0 else "🔴"
        sign      = "+" if chg >= 0 else ""
        lines.append("• " + c["name"] + " (" + c["symbol"] + ")  Rank #" + str(rank) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
    keyboard = [[InlineKeyboardButton("Refresh", callback_data="trending")]]
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_stats(update, context):
    msg = await update.message.reply_text("Se calculeaza statisticile...")
    fg = global_data = prices = None
    for attempt in range(3):
        if attempt > 0:
            await asyncio.sleep(2)
        fg          = get_fear_greed_stats()
        await asyncio.sleep(0.5)
        global_data = get_global_market()
        await asyncio.sleep(0.5)
        prices      = get_btc_eth_prices()
        if fg and global_data and prices:
            break
    if not fg or not global_data or not prices:
        await msg.edit_text("Nu s-au putut obtine datele. Incearca din nou.")
        return
    lang_s = get_user(update.effective_user.id).get("lang", "ro")
    text = format_stats_full(fg, global_data, prices, lang_s)
    keyboard = [[InlineKeyboardButton("Refresh", callback_data="stats_full")]]
    await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_sector(update, context):
    if not context.args:
        lines = ["Sectoare disponibile:\n"]
        for key, (_, label) in SECTORS.items():
            lines.append("• /sector " + key + " - " + label)
        lines.append("\nEx: /sector ai")
        await update.message.reply_text("\n".join(lines))
        return
    key = context.args[0].lower()
    if key not in SECTORS:
        await update.message.reply_text("Sector necunoscut. Scrie /sector pentru lista.")
        return
    category_id, label = SECTORS[key]
    await update.message.reply_text("Se incarca " + label + "...")
    coins = get_sector_coins(category_id)
    if not coins:
        await update.message.reply_text("Nu s-au putut obtine datele. Incearca din nou.")
        return
    lines = [label + " - Top " + str(len(coins)) + "\n"]
    for c in coins:
        chg       = c["change_24h"]
        chg_emoji = "🟢" if chg >= 0 else "🔴"
        sign      = "+" if chg >= 0 else ""
        lines.append(c["symbol"] + " #" + str(c["rank"]) + "  " + fmt_price(c["price"]) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
    keyboard = [[InlineKeyboardButton("Refresh", callback_data="sector_cb:" + key)]]
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_alert_ema(update, context):
    uid  = update.effective_user.id
    user = get_user(uid)
    await _delete_cmd(update)
    if len(context.args) < 2:
        await _dm_or_reply(update, context, "Usage: /alert_ema BTC 200\nPeriod: 20, 50, 100, 200")
        return
    symbol = context.args[0].upper()
    try:
        period = int(context.args[1])
    except ValueError:
        await _dm_or_reply(update, context, "Period trebuie sa fie un numar (ex: 200)")
        return
    if period not in [20, 50, 100, 200]:
        await _dm_or_reply(update, context, "Period trebuie sa fie: 20, 50, 100 sau 200")
        return
    slug = resolve_slug(symbol)
    await _dm_or_reply(update, context, "Se calculeaza EMA...")
    ema   = await asyncio.to_thread(get_ema, slug, period, "daily")
    price = await asyncio.to_thread(get_current_price_simple, slug)
    if ema is None:
        await _dm_or_reply(update, context, "Nu s-a putut calcula EMA pentru " + symbol + ".")
        return
    position  = "above" if (price and price > ema) else "below"
    alert_key = symbol + ":daily:" + str(period)
    user["alerts"]["ema"][alert_key] = {
        "symbol": symbol, "slug": slug, "timeframe": "daily",
        "period": period, "position": position,
    }
    save_data()
    pos_text = "DEASUPRA" if position == "above" else "SUB"
    await _dm_or_reply(update, context,
        "Alerta EMA setata!\n\n"
        + symbol + " EMA" + str(period) + " DAILY\n"
        + "EMA" + str(period) + ": " + fmt_price(ema) + "\n"
        + "Pret curent: " + (fmt_price(price) if price else "N/A") + "\n"
        + "Pozitie: " + pos_text + " EMA\n\n"
        + "Vei fi notificat cand pretul incruciseaza EMA" + str(period) + "."
    )

async def cmd_alert_fear(update, context):
    uid  = update.effective_user.id
    user = get_user(uid)
    await _delete_cmd(update)
    if not context.args:
        await _dm_or_reply(update, context, "Usage: /alert_fear 20")
        return
    try:
        threshold = float(context.args[0])
    except ValueError:
        await _dm_or_reply(update, context, "Numar invalid.")
        return
    user["alerts"]["fear"] = threshold
    save_data()
    await _dm_or_reply(update, context, t(uid, "alert_fear_set", threshold))

async def cmd_alerts(update, context):
    uid    = update.effective_user.id
    user   = get_user(uid)
    await _delete_cmd(update)
    alerts = user.get("alerts", {})
    ema_a  = alerts.get("ema", {})
    fear_a = alerts.get("fear")
    if not ema_a and not fear_a:
        await _dm_or_reply(update, context, t(uid, "alerts_empty"))
        return
    lines = ["Your Alerts\n"]
    if ema_a:
        lines.append("EMA Alerts:")
        for key, info in ema_a.items():
            lines.append("  " + info["symbol"] + " EMA" + str(info["period"]) + " DAILY (currently " + info["position"] + " EMA)")
    if fear_a:
        lines.append("Fear & Greed Alert: < " + str(fear_a))
    await _dm_or_reply(update, context, "\n".join(lines))

async def cmd_report(update, context):
    uid = update.effective_user.id
    await _delete_cmd(update)
    await _dm_or_reply(update, context, t(uid, "loading"))
    text = await generate_report(uid)
    keyboard = [[InlineKeyboardButton("Refresh", callback_data="report")]]
    await _dm_or_reply(update, context, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_set_report(update, context):
    uid  = update.effective_user.id
    user = get_user(uid)
    await _delete_cmd(update)
    if not context.args:
        await _dm_or_reply(update, context, "Usage: /set_report 08:00")
        return
    time_str = context.args[0]
    try:
        datetime.datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await _dm_or_reply(update, context, "Format invalid. Foloseste HH:MM (ex: 08:00)")
        return
    user["report_time"]    = time_str
    user["report_enabled"] = True
    save_data()
    await _dm_or_reply(update, context, t(uid, "report_set", time_str))

async def cmd_set_lang(update, context):
    uid  = update.effective_user.id
    user = get_user(uid)
    await _delete_cmd(update)
    if not context.args or context.args[0].lower() not in ["ro", "en"]:
        await _dm_or_reply(update, context, "Usage: /set_lang ro or /set_lang en")
        return
    user["lang"] = context.args[0].lower()
    save_data()
    await _dm_or_reply(update, context, t(uid, "lang_set"))

async def cmd_set_currency(update, context):
    uid   = update.effective_user.id
    user  = get_user(uid)
    await _delete_cmd(update)
    valid = ["USD", "EUR", "GBP", "RON"]
    if not context.args or context.args[0].upper() not in valid:
        await _dm_or_reply(update, context, "Usage: /set_currency USD\nOptions: " + ", ".join(valid))
        return
    user["currency"] = context.args[0].upper()
    save_data()
    await _dm_or_reply(update, context, t(uid, "currency_set", user["currency"]))


# ─── CALLBACKS ─────────────────────────────────────────────────────────────────

async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    uid  = update.effective_user.id
    data = query.data
    lang = get_user(uid).get("lang", "ro")
    back = "⬅️ Inapoi" if lang == "ro" else "⬅️ Back"

    # ── Help main menu ─────────────────────────────────────────────────────────
    if data in ("help_back", "help"):
        label = "Alege o categorie:" if lang == "ro" else "Choose a category:"
        await query.edit_message_text(label, reply_markup=help_main_keyboard(lang))

    elif data in get_help_keyboards(lang):
        cat = get_help_keyboards(lang)[data]
        await query.edit_message_text(cat["title"], reply_markup=InlineKeyboardMarkup(cat["keyboard"]))

    # ── Start menu shortcuts ───────────────────────────────────────────────────
    elif data == "portfolio":
        user = get_user(uid)
        if not user.get("portfolio"):
            await query.edit_message_text(t(uid, "portfolio_empty"), reply_markup=back_keyboard(lang))
            return
        pf = calculate_portfolio(uid)
        if not pf:
            await query.edit_message_text(t(uid, "no_data"), reply_markup=back_keyboard(lang))
            return
        currency = user.get("currency", "USD")
        lines = [("Your Portfolio" if lang == "en" else "Portofoliul Tau") + "\n"]
        for c in pf["coins"]:
            lines.append(
                c["symbol"] + " x" + str(c["amount"]) + "\n"
                "  Value:  " + fmt_currency(c["current_value"], currency) + "\n"
                "  Price:  " + fmt_price(c["current_price"]) + "\n"
                "  24h:    " + fmt_pct(c["change_24h"]) + "\n"
                "  P&L:    " + fmt_currency(c["pnl"], currency) + " (" + fmt_pct(c["pnl_pct"]) + ")\n"
            )
        lines.append("\nTOTAL VALUE: " + fmt_currency(pf["total_value"], currency))
        lines.append("TOTAL P&L:   " + fmt_currency(pf["total_pnl"], currency) + " (" + fmt_pct(pf["total_pnl_pct"]) + ")")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="portfolio")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "watchlist":
        user = get_user(uid)
        if not user.get("watchlist"):
            await query.edit_message_text(t(uid, "watchlist_empty"), reply_markup=back_keyboard(lang))
            return
        slugs = [resolve_slug(s) for s in user["watchlist"]]
        prices_data = {}
        try:
            r = requests.get(COINGECKO_BASE + "/simple/price",
                params={"ids": ",".join(slugs), "vs_currencies": "usd", "include_24hr_change": "true"},
                timeout=10, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                prices_data = r.json()
        except Exception as e:
            logger.error("watchlist batch: " + str(e))
        header = "Watchlist (24h)\n"
        lines = [header]
        for symbol in user["watchlist"]:
            pd = prices_data.get(resolve_slug(symbol), {})
            if pd:
                lines.append(symbol + ": " + fmt_price(pd.get("usd", 0)) + " | " + fmt_pct(pd.get("usd_24h_change", 0)) + " (24h)")
            else:
                lines.append(symbol + ": N/A")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="watchlist")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "report":
        text = await generate_report(uid)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="report")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # ── Exec commands from help menu ───────────────────────────────────────────
    elif data == "exec_portfolio":
        user = get_user(uid)
        if not user.get("portfolio"):
            await query.edit_message_text(t(uid, "portfolio_empty"), reply_markup=back_keyboard(lang))
            return
        pf = calculate_portfolio(uid)
        if not pf:
            await query.edit_message_text(t(uid, "no_data"), reply_markup=back_keyboard(lang))
            return
        currency = user.get("currency", "USD")
        lines = [("Your Portfolio" if lang == "en" else "Portofoliul Tau") + "\n"]
        for c in pf["coins"]:
            lines.append(
                c["symbol"] + " x" + str(c["amount"]) + "\n"
                "  Value:  " + fmt_currency(c["current_value"], currency) + "\n"
                "  Price:  " + fmt_price(c["current_price"]) + "\n"
                "  24h:    " + fmt_pct(c["change_24h"]) + "\n"
                "  P&L:    " + fmt_currency(c["pnl"], currency) + " (" + fmt_pct(c["pnl_pct"]) + ")\n"
            )
        lines.append("\nTOTAL VALUE: " + fmt_currency(pf["total_value"], currency))
        lines.append("TOTAL P&L:   " + fmt_currency(pf["total_pnl"], currency) + " (" + fmt_pct(pf["total_pnl_pct"]) + ")")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="exec_portfolio")],
                    [InlineKeyboardButton(back, callback_data="help_portfolio")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_pnl":
        user = get_user(uid)
        if not user.get("portfolio"):
            await query.edit_message_text(t(uid, "pnl_empty"), reply_markup=back_keyboard(lang))
            return
        pf = calculate_portfolio(uid)
        if not pf:
            await query.edit_message_text(t(uid, "no_data"), reply_markup=back_keyboard(lang))
            return
        currency = user.get("currency", "USD")
        lines = ["P&L Report\n"]
        for c in sorted(pf["coins"], key=lambda x: x["pnl_pct"], reverse=True):
            emoji = "🟢" if c["pnl"] >= 0 else "🔴"
            lines.append(
                emoji + " " + c["symbol"] + "\n"
                "  Buy: " + fmt_price(c["buy_price"]) + " -> Now: " + fmt_price(c["current_price"]) + "\n"
                "  P&L: " + fmt_currency(c["pnl"], currency) + " (" + fmt_pct(c["pnl_pct"]) + ")\n"
            )
        e2 = "🟢" if pf["total_pnl"] >= 0 else "🔴"
        lines.append(e2 + " TOTAL: " + fmt_currency(pf["total_pnl"], currency) + " (" + fmt_pct(pf["total_pnl_pct"]) + ")")
        keyboard = [[InlineKeyboardButton(back, callback_data="help_portfolio")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_watchlist":
        user = get_user(uid)
        if not user.get("watchlist"):
            await query.edit_message_text(t(uid, "watchlist_empty"), reply_markup=back_keyboard(lang))
            return
        slugs = [resolve_slug(s) for s in user["watchlist"]]
        prices_data = {}
        try:
            r = requests.get(COINGECKO_BASE + "/simple/price",
                params={"ids": ",".join(slugs), "vs_currencies": "usd", "include_24hr_change": "true"},
                timeout=10, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                prices_data = r.json()
        except Exception as e:
            logger.error("watchlist batch: " + str(e))
        lines = [("Watchlist (24h)" if lang == "en" else "Watchlist (24h)") + "\n"]
        for symbol in user["watchlist"]:
            pd = prices_data.get(resolve_slug(symbol), {})
            if pd:
                lines.append(symbol + ": " + fmt_price(pd.get("usd", 0)) + " | " + fmt_pct(pd.get("usd_24h_change", 0)) + " (24h)")
            else:
                lines.append(symbol + ": N/A")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="exec_watchlist")],
                    [InlineKeyboardButton(back, callback_data="help_watchlist")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_alerts":
        user   = get_user(uid)
        alerts = user.get("alerts", {})
        ema_a  = alerts.get("ema", {})
        fear_a = alerts.get("fear")
        if not ema_a and not fear_a:
            await query.edit_message_text(t(uid, "alerts_empty"), reply_markup=back_keyboard(lang))
            return
        lines = [("Your Alerts" if lang == "en" else "Alertele Tale") + "\n"]
        if ema_a:
            lines.append("EMA Alerts:" if lang == "en" else "Alerte EMA:")
            for key, info in ema_a.items():
                lines.append("  " + info["symbol"] + " EMA" + str(info["period"]) + " DAILY (" + info["position"] + " EMA)")
        if fear_a:
            lines.append(("Fear & Greed Alert: < " if lang == "en" else "Alerta Fear & Greed: < ") + str(fear_a))
        keyboard = [[InlineKeyboardButton(back, callback_data="help_alerts")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_report":
        text = await generate_report(uid)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="exec_report")],
                    [InlineKeyboardButton(back, callback_data="help_reports")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_trending":
        if "trending" in _cache:
            del _cache["trending"]
        coins = get_trending_coins()
        if not coins:
            await query.edit_message_text(t(uid, "no_data"), reply_markup=back_keyboard(lang))
            return
        header = "Trending pe CoinGecko" if lang == "ro" else "Trending on CoinGecko"
        lines = [header + "\n"]
        for item in coins[:7]:
            c         = item["item"]
            rank      = c.get("market_cap_rank", "?")
            chg       = c.get("change_24h", 0)
            chg_emoji = "🟢" if chg >= 0 else "🔴"
            sign      = "+" if chg >= 0 else ""
            lines.append("• " + c["name"] + " (" + c["symbol"] + ")  Rank #" + str(rank) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="exec_trending")],
                    [InlineKeyboardButton(back, callback_data="help_market")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_stats":
        fg = global_data = prices = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2)
            fg          = get_fear_greed_stats()
            await asyncio.sleep(0.5)
            global_data = get_global_market()
            await asyncio.sleep(0.5)
            prices      = get_btc_eth_prices()
            if fg and global_data and prices:
                break
        if not fg or not global_data or not prices:
            await query.edit_message_text(t(uid, "no_data"), reply_markup=back_keyboard(lang))
            return
        text = format_stats_full(fg, global_data, prices)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="exec_stats")],
                    [InlineKeyboardButton(back, callback_data="help_market")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_sector_list":
        rows = []
        for key, (_, label) in SECTORS.items():
            rows.append([InlineKeyboardButton(label, callback_data="exec_sector:" + key)])
        rows.append([InlineKeyboardButton(back, callback_data="help_market")])
        title = "Alege un sector:" if lang == "ro" else "Choose a sector:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("exec_sector:"):
        key = data.split(":", 1)[1]
        if key not in SECTORS:
            await query.answer("Invalid sector.")
            return
        category_id, label = SECTORS[key]
        coins = get_sector_coins(category_id)
        if not coins:
            await query.edit_message_text(t(uid, "no_data"), reply_markup=back_keyboard(lang))
            return
        lines = [label + " - Top " + str(len(coins)) + "\n"]
        for c in coins:
            chg       = c["change_24h"]
            chg_emoji = "🟢" if chg >= 0 else "🔴"
            sign      = "+" if chg >= 0 else ""
            lines.append(c["symbol"] + " #" + str(c["rank"]) + "  " + fmt_price(c["price"]) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="exec_sector:" + key)],
                    [InlineKeyboardButton(back, callback_data="exec_sector_list")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    # ── Watchlist add/remove ───────────────────────────────────────────────────
    elif data == "exec_wl_add_list":
        rows = []
        row  = []
        for i, coin in enumerate(PREDEFINED_COINS):
            row.append(InlineKeyboardButton(coin, callback_data="wl_add:" + coin))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_watchlist")])
        title = "Alege moneda de adaugat:" if lang == "ro" else "Choose coin to add:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data == "exec_wl_remove_list":
        user = get_user(uid)
        wl   = user.get("watchlist", [])
        if not wl:
            await query.edit_message_text(t(uid, "watchlist_empty"), reply_markup=back_keyboard(lang))
            return
        rows = []
        row  = []
        for coin in wl:
            row.append(InlineKeyboardButton(coin, callback_data="wl_remove:" + coin))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_watchlist")])
        title = "Alege moneda de sters:" if lang == "ro" else "Choose coin to remove:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("wl_add:"):
        coin = data.split(":", 1)[1]
        user = get_user(uid)
        if coin not in user["watchlist"]:
            user["watchlist"].append(coin)
            save_data()
        rows = []
        row  = []
        for c in PREDEFINED_COINS:
            row.append(InlineKeyboardButton(c, callback_data="wl_add:" + c))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_watchlist")])
        title = ("Adaugat! Alege alta moneda:" if lang == "ro" else "Added! Choose another:") + " (" + coin + ")"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("wl_remove:"):
        coin = data.split(":", 1)[1]
        user = get_user(uid)
        if coin in user["watchlist"]:
            user["watchlist"].remove(coin)
            save_data()
        wl = user.get("watchlist", [])
        if not wl:
            await query.edit_message_text(t(uid, "watchlist_empty"), reply_markup=back_keyboard(lang))
            return
        rows = []
        row  = []
        for c in wl:
            row.append(InlineKeyboardButton(c, callback_data="wl_remove:" + c))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_watchlist")])
        title = "Alege moneda de sters:" if lang == "ro" else "Choose coin to remove:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    # ── Portfolio add/remove ───────────────────────────────────────────────────
    elif data == "exec_pf_add_list":
        rows = []
        row  = []
        for coin in PREDEFINED_COINS:
            row.append(InlineKeyboardButton(coin, callback_data="pf_add_pick:" + coin))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_portfolio")])
        title = "Alege moneda de adaugat:" if lang == "ro" else "Choose coin to add:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data == "exec_pf_remove_list":
        user = get_user(uid)
        pf   = user.get("portfolio", {})
        if not pf:
            await query.edit_message_text(t(uid, "portfolio_empty"), reply_markup=back_keyboard(lang))
            return
        rows = []
        row  = []
        for coin in pf.keys():
            row.append(InlineKeyboardButton(coin, callback_data="pf_remove:" + coin))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_portfolio")])
        title = "Alege moneda de sters:" if lang == "ro" else "Choose coin to remove:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("pf_add_pick:"):
        coin = data.split(":", 1)[1]
        _user_state[uid] = "pf_add:" + coin
        prompt = ("Scrie cantitatea si pretul pentru " + coin + " (ex: 0.5 45000):"
                  if lang == "ro" else
                  "Enter amount and buy price for " + coin + " (e.g. 0.5 45000):")
        await query.message.reply_text(prompt,
            reply_markup=ForceReply(selective=True, input_field_placeholder="ex: 0.5 45000"))

    elif data.startswith("pf_remove:"):
        coin = data.split(":", 1)[1]
        user = get_user(uid)
        if coin in user["portfolio"]:
            del user["portfolio"][coin]
            save_data()
        pf = user.get("portfolio", {})
        if not pf:
            await query.edit_message_text(t(uid, "portfolio_empty"), reply_markup=back_keyboard(lang))
            return
        rows = []
        row  = []
        for c in pf.keys():
            row.append(InlineKeyboardButton(c, callback_data="pf_remove:" + c))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_portfolio")])
        title = "Alege moneda de sters:" if lang == "ro" else "Choose coin to remove:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    # ── Alerts setup ──────────────────────────────────────────────────────────
    elif data == "exec_alert_ema_menu":
        rows = []
        row  = []
        for coin in PREDEFINED_COINS:
            row.append(InlineKeyboardButton(coin, callback_data="alert_ema_coin:" + coin))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(back, callback_data="help_alerts")])
        title = "Alege moneda pentru alerta EMA200 Daily:" if lang == "ro" else "Choose coin for EMA200 Daily alert:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("alert_ema_coin:"):
        coin = data.split(":", 1)[1]
        user = get_user(uid)
        slug  = resolve_slug(coin)
        msg_calc = "Se calculeaza EMA200 pentru " + coin + "..." if lang == "ro" else "Calculating EMA200 for " + coin + "..."
        await query.edit_message_text(msg_calc)
        ema   = await asyncio.to_thread(get_ema, slug, 200, "daily")
        price = await asyncio.to_thread(get_current_price_simple, slug)
        if ema is None:
            keyboard = [[InlineKeyboardButton(back, callback_data="exec_alert_ema_menu")]]
            err = ("Nu s-a putut calcula EMA pentru " + coin + "." if lang == "ro"
                   else "Could not calculate EMA for " + coin + ".")
            await query.edit_message_text(err, reply_markup=InlineKeyboardMarkup(keyboard))
            return
        position  = "above" if (price and price > ema) else "below"
        alert_key = coin + ":daily:200"
        if "ema" not in user["alerts"]:
            user["alerts"]["ema"] = {}
        user["alerts"]["ema"][alert_key] = {
            "symbol": coin, "slug": slug, "timeframe": "daily",
            "period": 200, "position": position,
        }
        save_data()
        pos_text = ("DEASUPRA" if position == "above" else "SUB") if lang == "ro" else ("ABOVE" if position == "above" else "BELOW")
        keyboard = [[InlineKeyboardButton(back, callback_data="help_alerts")]]
        msg_ok = ("Alerta EMA200 setata pentru " + coin + "!\n\n"
                  + "EMA200: " + fmt_price(ema) + "\n"
                  + "Pret curent: " + (fmt_price(price) if price else "N/A") + "\n"
                  + "Pozitie: " + pos_text + " EMA\n\n"
                  + "Vei fi notificat cand pretul incruciseaza EMA200."
                  if lang == "ro" else
                  "EMA200 alert set for " + coin + "!\n\n"
                  + "EMA200: " + fmt_price(ema) + "\n"
                  + "Current price: " + (fmt_price(price) if price else "N/A") + "\n"
                  + "Position: " + pos_text + " EMA\n\n"
                  + "You will be notified when price crosses EMA200.")
        await query.edit_message_text(msg_ok, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_alert_fear_menu":
        rows = [
            [InlineKeyboardButton("10", callback_data="alert_fear_set:10"),
             InlineKeyboardButton("15", callback_data="alert_fear_set:15"),
             InlineKeyboardButton("20", callback_data="alert_fear_set:20"),
             InlineKeyboardButton("25", callback_data="alert_fear_set:25")],
            [InlineKeyboardButton("30", callback_data="alert_fear_set:30"),
             InlineKeyboardButton("35", callback_data="alert_fear_set:35"),
             InlineKeyboardButton("40", callback_data="alert_fear_set:40"),
             InlineKeyboardButton("45", callback_data="alert_fear_set:45")],
            [InlineKeyboardButton(back, callback_data="help_alerts")],
        ]
        fg = get_fear_greed()
        current = (("Fear & Greed curent: " if lang == "ro" else "Current Fear & Greed: ")
                   + str(fg["value"]) + "/100") if fg else ""
        title = ("Alege pragul pentru alerta Fear & Greed:\n(primesti alerta cand scade sub valoarea aleasa)\n\n"
                 if lang == "ro" else
                 "Choose Fear & Greed alert threshold:\n(you get alerted when it drops below)\n\n") + current
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("alert_fear_set:"):
        threshold = float(data.split(":", 1)[1])
        user = get_user(uid)
        user["alerts"]["fear"] = threshold
        save_data()
        keyboard = [[InlineKeyboardButton(back, callback_data="help_alerts")]]
        msg_fear = ("Alerta Fear & Greed setata!\n\nVei fi notificat cand Fear & Greed scade sub " + str(int(threshold)) + "."
                    if lang == "ro" else
                    "Fear & Greed alert set!\n\nYou will be notified when Fear & Greed drops below " + str(int(threshold)) + ".")
        await query.edit_message_text(msg_fear, reply_markup=InlineKeyboardMarkup(keyboard))

    # ── Settings ───────────────────────────────────────────────────────────────
    elif data.startswith("exec_lang_"):
        new_lang = data.split("_")[-1]
        user = get_user(uid)
        user["lang"] = new_lang
        save_data()
        new_back = "⬅️ Inapoi" if new_lang == "ro" else "⬅️ Back"
        msg_lang = "Limba setata: Romana" if new_lang == "ro" else "Language set: English"
        keyboard = [[InlineKeyboardButton(new_back, callback_data="help_settings")]]
        await query.edit_message_text(msg_lang, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("exec_cur_"):
        currency = data.split("_")[-1]
        user = get_user(uid)
        user["currency"] = currency
        save_data()
        for key in list(_cache.keys()):
            if key.startswith("rate:"):
                del _cache[key]
        msg_cur = ("Moneda setata: " if lang == "ro" else "Currency set: ") + currency
        keyboard = [[InlineKeyboardButton(back, callback_data="help_settings")]]
        await query.edit_message_text(msg_cur, reply_markup=InlineKeyboardMarkup(keyboard))

    # ── Stat/Sector refreshes (from /stats and /sector commands) ──────────────
    elif data == "stats_full":
        fg = global_data = prices = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2)
            fg          = get_fear_greed_stats()
            await asyncio.sleep(0.5)
            global_data = get_global_market()
            await asyncio.sleep(0.5)
            prices      = get_btc_eth_prices()
            if fg and global_data and prices:
                break
        if not fg or not global_data or not prices:
            await query.edit_message_text(t(uid, "no_data"))
            return
        text = format_stats_full(fg, global_data, prices)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats_full")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "trending":
        if "trending" in _cache:
            del _cache["trending"]
        coins = get_trending_coins()
        if not coins:
            await query.edit_message_text(t(uid, "no_data"))
            return
        lines = [("Trending pe CoinGecko" if lang == "ro" else "Trending on CoinGecko") + "\n"]
        for item in coins[:7]:
            c         = item["item"]
            rank      = c.get("market_cap_rank", "?")
            chg       = c.get("change_24h", 0)
            chg_emoji = "🟢" if chg >= 0 else "🔴"
            sign      = "+" if chg >= 0 else ""
            lines.append("• " + c["name"] + " (" + c["symbol"] + ")  Rank #" + str(rank) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("sector_cb:"):
        key = data.split(":", 1)[1]
        if key not in SECTORS:
            await query.answer("Invalid sector.")
            return
        category_id, label = SECTORS[key]
        coins = get_sector_coins(category_id)
        if not coins:
            await query.edit_message_text(t(uid, "no_data"))
            return
        lines = [label + " - Top " + str(len(coins)) + "\n"]
        for c in coins:
            chg       = c["change_24h"]
            chg_emoji = "🟢" if chg >= 0 else "🔴"
            sign      = "+" if chg >= 0 else ""
            lines.append(c["symbol"] + " #" + str(c["rank"]) + "  " + fmt_price(c["price"]) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="sector_cb:" + key)]]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))


async def check_technical_alerts(context):
    fg = get_fear_greed(fresh=True)
    if fg:
        logger.info("Fear & Greed check: " + str(fg["value"]))
    for uid, user in list(user_data.items()):
        alerts = user.get("alerts", {})

        # Fear & Greed alert - o singura data
        fear_threshold = alerts.get("fear")
        if fg and fear_threshold is not None:
            already_sent = user.get("_fear_alert_sent", False)
            if fg["value"] <= fear_threshold and not already_sent:
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            "Fear & Greed Alert!\n\n"
                            "Fear & Greed: " + str(fg["value"]) + "/100 - " + fg["label"] + "\n"
                            "Pragul tau: sub " + str(fear_threshold)
                        )
                    )
                    user["_fear_alert_sent"] = True
                    save_data()
                except Exception as e:
                    logger.error("Fear alert error: " + str(e))
            elif fg["value"] > fear_threshold and already_sent:
                user["_fear_alert_sent"] = False
                save_data()

        # EMA crossover alerts
        for alert_key, info in list(alerts.get("ema", {}).items()):
            slug      = info["slug"]
            period    = info["period"]
            timeframe = info["timeframe"]
            symbol    = info["symbol"]
            old_pos   = info.get("position", "above")
            ema       = await asyncio.to_thread(get_ema, slug, period, timeframe)
            price     = await asyncio.to_thread(get_current_price_simple, slug)
            await asyncio.sleep(0.3)
            if ema is None or price is None:
                continue
            new_pos      = "above" if price > ema else "below"
            already_sent = info.get("alert_sent", False)
            if new_pos != old_pos and not already_sent:
                direction = "CROSSED ABOVE" if new_pos == "above" else "CROSSED BELOW"
                emoji     = "🟢" if new_pos == "above" else "🔴"
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            emoji + " EMA Crossover Alert - " + symbol + "\n\n"
                            + symbol + " a " + direction + " EMA" + str(period) + " DAILY\n"
                            + "Pret: " + fmt_price(price) + "\n"
                            + "EMA" + str(period) + ": " + fmt_price(ema)
                        )
                    )
                    user["alerts"]["ema"][alert_key]["position"]   = new_pos
                    user["alerts"]["ema"][alert_key]["alert_sent"] = True
                    save_data()
                except Exception as e:
                    logger.error("EMA alert error: " + str(e))
            elif new_pos == old_pos and already_sent:
                user["alerts"]["ema"][alert_key]["alert_sent"] = False
                save_data()

async def check_daily_reports(context):
    now_ro       = datetime.datetime.now(pytz.timezone("Europe/Bucharest"))
    current_time = now_ro.strftime("%H:%M")
    for uid, user in list(user_data.items()):
        if not user.get("report_enabled", True):
            continue
        if current_time == user.get("report_time", "08:00"):
            try:
                text = await generate_report(uid)
                keyboard = [[InlineKeyboardButton("Refresh", callback_data="report")]]
                await context.bot.send_message(chat_id=uid, text=text,
                                               reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                logger.error("Daily report error for " + str(uid) + ": " + str(e))


async def handle_force_reply(update, context):
    uid   = update.effective_user.id
    state = _user_state.get(uid)
    if not state:
        return
    text = update.message.text.strip()
    user = get_user(uid)
    del _user_state[uid]

    if state == "wl_add":
        symbol = text.upper()
        if symbol not in user["watchlist"]:
            user["watchlist"].append(symbol)
            save_data()

    elif state == "wl_remove":
        symbol = text.upper()
        if symbol in user["watchlist"]:
            user["watchlist"].remove(symbol)
            save_data()

    elif state.startswith("pf_add"):
        # state = "pf_add:BTC" (from list) or "pf_add" (legacy)
        parts = text.split()
        if ":" in state:
            symbol    = state.split(":", 1)[1]
            amount    = float(parts[0]) if len(parts) > 0 else 0
            buy_price = float(parts[1]) if len(parts) > 1 else 0
        else:
            symbol    = parts[0].upper() if len(parts) > 0 else ""
            amount    = float(parts[1]) if len(parts) > 1 else 0
            buy_price = float(parts[2]) if len(parts) > 2 else 0
        if symbol:
            user["portfolio"][symbol] = {
                "slug": resolve_slug(symbol), "amount": amount, "buy_price": buy_price,
            }
            save_data()

    elif state == "pf_remove":
        symbol = text.upper()
        if symbol in user["portfolio"]:
            del user["portfolio"][symbol]
            save_data()

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("chatid",       cmd_chatid))
    app.add_handler(CommandHandler("portfolio",    cmd_portfolio))
    app.add_handler(CommandHandler("pnl",          cmd_pnl))
    app.add_handler(CommandHandler("watchlist",    cmd_watchlist))
    app.add_handler(CommandHandler("trending",     cmd_trending))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("sector",       cmd_sector))
    app.add_handler(CommandHandler("alert_ema",    cmd_alert_ema))
    app.add_handler(CommandHandler("alert_fear",   cmd_alert_fear))
    app.add_handler(CommandHandler("alerts",       cmd_alerts))
    app.add_handler(CommandHandler("report",       cmd_report))
    app.add_handler(CommandHandler("set_report",   cmd_set_report))
    app.add_handler(CommandHandler("set_lang",     cmd_set_lang))
    app.add_handler(CommandHandler("set_currency", cmd_set_currency))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_force_reply))

    app.job_queue.run_repeating(check_technical_alerts, interval=CHECK_INTERVAL, first=60)
    app.job_queue.run_repeating(check_daily_reports,    interval=60,             first=30)

    print("CryptoPersonal Bot running...")
    print("JSONBIN_API_KEY set:", bool(JSONBIN_API_KEY))
    print("JSONBIN_BIN_ID set:", bool(JSONBIN_BIN_ID))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
