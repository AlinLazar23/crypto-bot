"""
Crypto Market Updates Telegram Bot
====================================
Surse: CoinGecko + TradingView + alternative.me
Compatibil Python 3.8+

Requirements:
    pip install python-telegram-bot[job-queue] requests pytz

Commands:
    /start           - Bun venit
    /price BTC       - Pret live
    /top             - Top 10 dupa market cap
    /trending        - Trending CoinGecko
    /bubbles         - Lista CryptoBubbles
    /stats           - Statistici piata
    /sector          - Lista sectoare crypto
    /alert BTC 70000 - Alerta de pret
    /myalerts        - Alertele tale
    /removealert 1   - Sterge alerta
    /chatid          - Afla chat ID
    /help            - Ajutor
"""

import os
import time
import json
import asyncio
import logging
import datetime
import requests
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN             = os.environ.get("BOT_TOKEN", "")
COINGECKO_BASE        = "https://api.coingecko.com/api/v3"
CHECK_ALERTS_INTERVAL = 60
GROUP_CHAT_ID         = -1003982541636
AUTO_STATS_INTERVAL   = 43200
PUMP_THRESHOLD        = 0.1
PUMP_COOLDOWN         = 43200

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── PERSISTENT ALERTS ─────────────────────────────────────────────────────────
ALERTS_FILE = "alerts.json"

def load_alerts():
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, "r") as f:
                raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
        except Exception as e:
            logger.error("load_alerts error: " + str(e))
    return {}

def save_alerts():
    try:
        with open(ALERTS_FILE, "w") as f:
            json.dump(user_alerts, f, indent=2)
    except Exception as e:
        logger.error("save_alerts error: " + str(e))

user_alerts = load_alerts()

# ─── CACHE ─────────────────────────────────────────────────────────────────────
_cache = {}
CACHE_TTL = 300

def cache_get(key):
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None

def cache_set(key, data):
    _cache[key] = (data, time.time())

# ─── PUMP ALERTS ───────────────────────────────────────────────────────────────
_pump_alerts_sent = {}

# ─── FORMATARE ─────────────────────────────────────────────────────────────────

def fmt_price(value):
    if value is None:
        return "N/A"
    try:
        if value >= 1:
            return "$" + "{:,.2f}".format(value)
        return "$" + "{:.6f}".format(value)
    except Exception:
        return "N/A"

def fmt_large(value):
    if not value:
        return "N/A"
    try:
        if value >= 1000000000000:
            return "$" + "{:.2f}T".format(value / 1000000000000)
        if value >= 1000000000:
            return "$" + "{:.2f}B".format(value / 1000000000)
        if value >= 1000000:
            return "$" + "{:.1f}M".format(value / 1000000)
        return "$" + "{:,.0f}".format(value)
    except Exception:
        return "N/A"

def fmt_change(pct):
    if pct is None:
        return "N/A"
    arrow = "🟢 ▲" if pct >= 0 else "🔴 ▼"
    return arrow + " {:.2f}%".format(abs(pct))

# ─── COIN SLUG MAP ─────────────────────────────────────────────────────────────
COIN_SLUG_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "DOT": "polkadot", "AVAX": "avalanche-2",
    "LINK": "chainlink", "LTC": "litecoin", "UNI": "uniswap",
    "XLM": "stellar", "TRX": "tron", "SHIB": "shiba-inu",
    "MATIC": "matic-network", "NEAR": "near", "ATOM": "cosmos",
    "FTM": "fantom", "ALGO": "algorand", "XMR": "monero",
    "PEPE": "pepe", "SUI": "sui", "APT": "aptos",
    "ARB": "arbitrum", "OP": "optimism", "INJ": "injective-protocol",
    "FET": "fetch-ai", "RENDER": "render-token", "WIF": "dogwifcoin",
    "ICP": "internet-computer", "HBAR": "hedera-hashgraph",
    "FIL": "filecoin", "VET": "vechain", "SEI": "sei-network",
    "TIA": "celestia", "GRT": "the-graph", "EGLD": "elrond-erd-2",
    "VIRTUAL": "virtuals-protocol", "HYPE": "hyperliquid",
    "ASTR": "astar", "GALA": "gala", "ASTER": "aster-2",
    "bitcoin": "bitcoin", "ethereum": "ethereum", "solana": "solana",
    "ripple": "ripple", "cardano": "cardano", "dogecoin": "dogecoin",
    "polkadot": "polkadot", "avalanche": "avalanche-2",
    "chainlink": "chainlink", "litecoin": "litecoin",
    "stellar": "stellar", "tron": "tron", "shiba": "shiba-inu",
    "polygon": "matic-network", "near": "near", "cosmos": "cosmos",
    "fantom": "fantom", "algorand": "algorand", "monero": "monero",
    "bnb": "binancecoin", "binancecoin": "binancecoin",
    "arbitrum": "arbitrum", "optimism": "optimism",
    "injective": "injective-protocol", "filecoin": "filecoin",
    "vechain": "vechain", "celestia": "celestia",
    "hyperliquid": "hyperliquid", "kaspa": "kaspa",
}

def resolve_slug(query):
    q = query.strip()
    slug = COIN_SLUG_MAP.get(q.upper()) or COIN_SLUG_MAP.get(q.lower())
    return slug if slug else q.lower()

# ─── BUBBLES COINS ─────────────────────────────────────────────────────────────
BUBBLES_COINS = [
    ("bitcoin",            "BTC"),
    ("ethereum",           "ETH"),
    ("tether",             "USDT"),
    ("usd-coin",           "USDC"),
    ("dogecoin",           "DOGE"),
    ("hyperliquid",        "HYPE"),
    ("cardano",            "ADA"),
    ("chainlink",          "LINK"),
    ("avalanche-2",        "AVAX"),
    ("sui",                "SUI"),
    ("internet-computer",  "ICP"),
    ("polkadot",           "DOT"),
    ("astar",              "ASTR"),
    ("cosmos",             "ATOM"),
    ("algorand",           "ALGO"),
    ("arbitrum",           "ARB"),
    ("filecoin",           "FIL"),
    ("vechain",            "VET"),
    ("virtuals-protocol",  "VIRTUAL"),
    ("sei-network",        "SEI"),
    ("injective-protocol", "INJ"),
    ("celestia",           "TIA"),
    ("the-graph",          "GRT"),
    ("elrond-erd-2",       "EGLD"),
    ("binancecoin",        "BNB"),
    ("ripple",             "XRP"),
    ("fetch-ai",           "FET"),
    ("gala",               "GALA"),
    ("aster-2",            "ASTER"),
]

# ─── SECTOARE ──────────────────────────────────────────────────────────────────
SECTORS = {
    "ai":      ("artificial-intelligence",   "AI & Big Data"),
    "defi":    ("decentralized-finance-defi","DeFi"),
    "gaming":  ("gaming",                    "Gaming & GameFi"),
    "layer1":  ("layer-1",                   "Layer 1"),
    "layer2":  ("layer-2",                   "Layer 2"),
    "rwa":     ("real-world-assets-rwa",     "Real World Assets"),
    "privacy": ("privacy-coins",             "Privacy Coins"),
}

# ─── DATE COINGECKO ────────────────────────────────────────────────────────────

def cg_get(endpoint, params=None, timeout=20):
    """Request la CoinGecko cu retry automat si delay progresiv."""
    delays = [0, 5, 15]
    for attempt in range(3):
        if delays[attempt] > 0:
            time.sleep(delays[attempt])
        try:
            r = requests.get(
                COINGECKO_BASE + endpoint,
                params=params,
                timeout=timeout,
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 30))
                logger.warning("Rate limited attempt " + str(attempt + 1) + ", waiting " + str(retry_after) + "s")
                time.sleep(retry_after)
                continue
            if r.status_code == 200:
                return r.json()
            logger.warning("CoinGecko status " + str(r.status_code) + " for " + endpoint)
        except Exception as e:
            logger.error("cg_get error: " + str(e))
    return None

def get_coin_data(slug):
    cached = cache_get("coin:" + slug)
    if cached is not None:
        return cached
    data = cg_get("/coins/" + slug, params={
        "localization": "false", "tickers": "false",
        "community_data": "false", "developer_data": "false",
    })
    if not data:
        return None
    m = data["market_data"]
    result = {
        "slug":       slug,
        "symbol":     data["symbol"].upper(),
        "name":       data["name"],
        "rank":       data.get("market_cap_rank", "N/A"),
        "price":      m["current_price"].get("usd", 0),
        "change_1h":  m.get("price_change_percentage_1h_in_currency", {}).get("usd") or 0,
        "change_24h": m.get("price_change_percentage_24h") or 0,
        "change_7d":  m.get("price_change_percentage_7d") or 0,
        "change_30d": m.get("price_change_percentage_30d") or 0,
        "high_24h":   m["high_24h"].get("usd", 0),
        "low_24h":    m["low_24h"].get("usd", 0),
        "market_cap": m["market_cap"].get("usd", 0),
        "volume_24h": m["total_volume"].get("usd", 0),
    }
    cache_set("coin:" + slug, result)
    return result

def get_top_coins(limit=10):
    cached = cache_get("top:" + str(limit))
    if cached is not None:
        return cached
    data = cg_get("/coins/markets", params={
        "vs_currency": "usd", "order": "market_cap_desc",
        "per_page": limit, "page": 1, "sparkline": "false",
    })
    if not data:
        return []
    result = [{
        "symbol":    c["symbol"].upper(),
        "name":      c["name"],
        "slug":      c["id"],
        "price":     c["current_price"],
        "change_24h": c.get("price_change_percentage_24h") or 0,
    } for c in data]
    cache_set("top:" + str(limit), result)
    return result

def get_trending_coins():
    cached = cache_get("trending")
    if cached is not None:
        # Asigura ca change_24h exista si in cache
        for coin in cached:
            if "change_24h" not in coin["item"]:
                coin["item"]["change_24h"] = 0
        return cached
    data = cg_get("/search/trending")
    if not data:
        return []
    coins = data.get("coins", [])
    for coin in coins:
        item = coin["item"]
        try:
            chg = item["data"]["price_change_percentage_24h"]["usd"]
            item["change_24h"] = round(chg, 2)
        except Exception:
            item["change_24h"] = 0
    cache_set("trending", coins)
    return coins

def get_bubbles_data(period="24h"):
    cached = cache_get("bubbles:" + period)
    if cached is not None and len(cached) > 0:
        return cached
    time.sleep(1)
    slugs = [slug for slug, _ in BUBBLES_COINS]
    data = cg_get("/coins/markets", params={
        "vs_currency": "usd",
        "ids": ",".join(slugs),
        "order": "market_cap_desc",
        "per_page": 100,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d,30d,1y",
    }, timeout=30)
    if not data:
        return []
    result = [{
        "slug":       c["id"],
        "symbol":     c["symbol"].upper(),
        "name":       c["name"],
        "rank":       c.get("market_cap_rank", 999),
        "price":      c.get("current_price", 0),
        "change_1h":  float(c.get("price_change_percentage_1h_in_currency") or 0),
        "change_24h": float(c.get("price_change_percentage_24h") or 0),
        "change_7d":  float(c.get("price_change_percentage_7d_in_currency") or 0),
        "change_30d": float(c.get("price_change_percentage_30d_in_currency") or 0),
        "change_1y":  float(c.get("price_change_percentage_1y_in_currency") or 0),
        "market_cap": c.get("market_cap", 0),
        "volume_24h": c.get("total_volume", 0),
    } for c in data]
    cache_set("bubbles:" + period, result)
    return result

def get_global_market():
    cached = cache_get("global_market")
    if cached is not None:
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
    if cached is not None:
        return cached
    data = cg_get("/coins/markets", params={
        "vs_currency": "usd", "ids": "bitcoin,ethereum",
        "order": "market_cap_desc", "per_page": 2,
        "page": 1, "sparkline": "false",
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

def get_fear_greed():
    cached = cache_get("fear_greed")
    if cached is not None:
        return cached
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=8", timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                today     = data[0]
                yesterday = data[1] if len(data) > 1 else data[0]
                week_vals = [int(d["value"]) for d in data]
                result = {
                    "value":     int(today["value"]),
                    "label":     today["value_classification"],
                    "yesterday": int(yesterday["value"]),
                    "week_avg":  round(sum(week_vals) / len(week_vals), 1),
                }
                cache_set("fear_greed", result)
                return result
    except Exception as e:
        logger.error("get_fear_greed error: " + str(e))
    return None

def get_sector_coins(category_id, limit=15):
    cached = cache_get("sector:" + category_id)
    if cached is not None:
        return cached
    data = cg_get("/coins/markets", params={
        "vs_currency": "usd",
        "category": category_id,
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": "false",
    })
    if not data:
        return []
    result = [{
        "symbol":     c["symbol"].upper(),
        "name":       c["name"],
        "price":      c.get("current_price", 0),
        "change_24h": c.get("price_change_percentage_24h") or 0,
        "rank":       c.get("market_cap_rank", "?"),
    } for c in data]
    cache_set("sector:" + category_id, result)
    return result

# ─── STATS HELPERS ─────────────────────────────────────────────────────────────

def fng_emoji(value):
    if value <= 25:   return "😱"
    if value <= 45:   return "😰"
    if value <= 55:   return "😐"
    if value <= 75:   return "😄"
    return "🤑"

def fng_bar(value):
    filled = value // 10
    return "█" * filled + "░" * (10 - filled)

def interpret_fng(value):
    if value <= 20:  return "💡 Panica extrema -> zona istorica de acumulare"
    if value <= 40:  return "💡 Frica in piata -> posibila oportunitate de cumparare"
    if value <= 60:  return "💡 Piata este neutra -> asteapta confirmare directie"
    if value <= 80:  return "⚠️ Lacomie crescuta -> fii precaut, nu urmari FOMO"
    return "🚨 Euforie extrema -> risc ridicat de correctie"

def calc_market_score(fg, global_data, prices):
    score = 5.0
    fng_val = fg.get("value", 50)
    if fng_val <= 20:   score += 1.5
    elif fng_val <= 40: score += 0.5
    elif fng_val <= 60: score += 0.0
    elif fng_val <= 80: score -= 0.5
    else:               score -= 1.5
    trend = fng_val - fg.get("yesterday", fng_val)
    if trend > 5:    score += 0.5
    elif trend < -5: score -= 0.5
    btc_dom = global_data.get("btc_dominance", 50)
    if btc_dom > 55:   score -= 0.5
    elif btc_dom < 42: score += 0.5
    cap_chg = global_data.get("market_cap_change_24h", 0)
    if cap_chg > 3:    score += 1.0
    elif cap_chg > 1:  score += 0.5
    elif cap_chg < -3: score -= 1.0
    elif cap_chg < -1: score -= 0.5
    btc_chg = prices.get("btc_change", 0)
    if btc_chg > 3:    score += 0.5
    elif btc_chg < -3: score -= 0.5
    score = max(1, min(10, round(score)))
    if score <= 3:   label = "Bearish 🔴"
    elif score <= 4: label = "Slab Bearish 🟠"
    elif score <= 6: label = "Neutru 🟡"
    elif score <= 8: label = "Bullish 🟢"
    else:            label = "Strong Bullish 🟢🟢"
    return score, label

def generate_insight(fg, global_data, prices):
    fng_val  = fg.get("value", 50)
    btc_chg  = prices.get("btc_change", 0)
    cap_chg  = global_data.get("market_cap_change_24h", 0)
    btc_dom  = global_data.get("btc_dominance", 50)
    week_avg = fg.get("week_avg", 50)
    insights = []
    if fng_val <= 35 and btc_chg >= 0:
        insights.append("📊 Desi piata e in frica, BTC rezista -> posibila acumulare institutionala")
    elif fng_val >= 70 and btc_chg < -1:
        insights.append("⚠️ Greed ridicat dar BTC scade -> semnal de slabiciune")
    if fng_val > week_avg + 10:
        insights.append("📈 Sentimentul s-a imbunatatit fata de saptamana trecuta -> momentum pozitiv")
    elif fng_val < week_avg - 10:
        insights.append("📉 Sentimentul s-a deteriorat fata de media saptamanii -> prudenta")
    if cap_chg > 2:
        insights.append("💹 Market cap-ul total creste cu volum -> trend bullish confirmat")
    elif cap_chg < -2:
        insights.append("📉 Scadere generalizata in piata -> risc crescut pe termen scurt")
    if btc_dom > 58:
        insights.append("🔶 BTC dominance ridicat -> altcoin-urile sufera, capital concentrat in BTC")
    elif btc_dom < 42:
        insights.append("🟣 BTC dominance scazut -> posibila altseason in desfasurare")
    if fng_val <= 15:
        insights.append("🚨 Panica extrema istorica -> zonele acestea au coincis cu fundul pietei in trecut")
    if not insights:
        insights.append("➡️ Piata este echilibrata momentan - niciun semnal extrem detectat")
    return "\n".join(["  " + i for i in insights[:3]])

def format_stats(fg, global_data, prices):
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    year = utc_now.year
    march_last_sunday = max(
        datetime.datetime(year, 3, day, 1, tzinfo=datetime.timezone.utc)
        for day in range(25, 32)
        if datetime.datetime(year, 3, day).weekday() == 6
    )
    oct_last_sunday = max(
        datetime.datetime(year, 10, day, 1, tzinfo=datetime.timezone.utc)
        for day in range(25, 32)
        if datetime.datetime(year, 10, day).weekday() == 6
    )
    if march_last_sunday <= utc_now < oct_last_sunday:
        ro_offset = datetime.timedelta(hours=3)
        ro_label  = "EEST"
    else:
        ro_offset = datetime.timedelta(hours=2)
        ro_label  = "EET"
    ro_now = utc_now + ro_offset
    now = ro_now.strftime("%H:%M " + ro_label + " (%d.%m.%Y)")

    fng_val   = fg["value"]
    fng_label = fg["label"]
    fng_trend = fng_val - fg["yesterday"]
    if fng_trend > 0:
        trend_arrow = "↑ +" + str(fng_trend)
    elif fng_trend < 0:
        trend_arrow = "↓ " + str(fng_trend)
    else:
        trend_arrow = "→ 0"
    bar = fng_bar(fng_val)

    score, score_label = calc_market_score(fg, global_data, prices)
    score_bar = "⭐" * score + "☆" * (10 - score)
    insight   = generate_insight(fg, global_data, prices)

    cap_chg   = global_data.get("market_cap_change_24h", 0)
    cap_arrow = "🟢 ▲" if cap_chg >= 0 else "🔴 ▼"
    btc_arrow = "🟢 ▲" if prices.get("btc_change", 0) >= 0 else "🔴 ▼"
    eth_arrow = "🟢 ▲" if prices.get("eth_change", 0) >= 0 else "🔴 ▼"

    lines = [
        "📊 *Market Stats* — " + now,
        "━" * 22,
        "",
        "🧠 *SENTIMENT PIATA*",
        fng_emoji(fng_val) + " Fear & Greed: *" + str(fng_val) + "/100* — _" + fng_label + "_",
        "`[" + bar + "]`",
        "• Fata de ieri: `" + trend_arrow + "`",
        "• Media 7 zile: `" + str(fg["week_avg"]) + "/100`",
        "• " + interpret_fng(fng_val),
        "",
        "💰 *OVERVIEW PIATA*",
        "• BTC:  `" + fmt_price(prices.get("btc_price", 0)) + "`  " + btc_arrow + " `" + "{:.1f}%".format(abs(prices.get("btc_change", 0))) + "`",
        "• ETH:  `" + fmt_price(prices.get("eth_price", 0)) + "`  " + eth_arrow + " `" + "{:.1f}%".format(abs(prices.get("eth_change", 0))) + "`",
        "• Mkt Cap Total: `" + fmt_large(global_data.get("total_market_cap", 0)) + "`  " + cap_arrow + " `" + "{:.1f}%".format(abs(cap_chg)) + "`",
        "• Volum 24h:     `" + fmt_large(global_data.get("total_volume_24h", 0)) + "`",
        "• BTC Dominance: `" + str(global_data.get("btc_dominance", 0)) + "%`",
        "• ETH Dominance: `" + str(global_data.get("eth_dominance", 0)) + "%`",
        "",
        "🧪 *INSIGHT AUTOMAT*",
        insight,
        "",
        "⚡ *MARKET SCORE: " + str(score) + "/10 — " + score_label + "*",
        "`" + score_bar + "`",
        "_Bazat pe: sentiment + trend + volum + dominance_",
    ]
    return "\n".join(lines)

# ─── FORMAT BUBBLES ────────────────────────────────────────────────────────────

def format_bubbles(coins, period):
    period_key = {
        "1h": "change_1h", "24h": "change_24h",
        "7d": "change_7d", "30d": "change_30d", "1y": "change_1y",
    }.get(period, "change_24h")
    period_label = {
        "1h": "1 Ora", "24h": "24 Ore", "7d": "7 Zile",
        "30d": "30 Zile", "1y": "1 An",
    }.get(period, period)

    sorted_coins = sorted(coins, key=lambda c: float(c.get(period_key) or 0), reverse=True)

    header = (
        "🫧 *CryptoBubbles — " + period_label + "*\n"
        + "_" + str(len(coins)) + " monede sortate dupa performanta_\n"
        + "━" * 22 + "\n\n"
    )

    lines = []
    for c in sorted_coins:
        chg       = float(c.get(period_key) or 0)
        chg_emoji = "🟢" if chg >= 0 else "🔴"
        sign      = "+" if chg >= 0 else ""
        rank      = c["rank"]
        rank_str  = ("0" + str(rank)) if isinstance(rank, int) and rank < 10 else str(rank)
        price_str = fmt_price(c["price"])
        chg_str   = sign + "{:.1f}%".format(chg)
        line = c["symbol"] + " #" + rank_str + "  " + price_str + "  " + chg_emoji + " " + chg_str + "\n"
        lines.append(line)

    pages = []
    current = header
    for line in lines:
        if len(current) + len(line) > 3800:
            pages.append(current)
            current = "🫧 *CryptoBubbles — " + period_label + "* _(continuare)_\n\n"
        current += line
    if current.strip():
        pages.append(current)
    return pages

# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────

async def cmd_chatid(update, context):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    await update.message.reply_text("Chat ID: " + chat_id + "\nUser ID: " + user_id)

async def cmd_start(update, context):
    keyboard = [
        [InlineKeyboardButton("📊 Top 10",      callback_data="top"),
         InlineKeyboardButton("🔥 Trending",    callback_data="trending")],
        [InlineKeyboardButton("🫧 Bubbles 24h", callback_data="bubbles:24h"),
         InlineKeyboardButton("📊 Stats",       callback_data="stats")],
        [InlineKeyboardButton("❓ Help",         callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 *Bun venit la CryptoBot!*\n\n"
        "Date live din CoinGecko + TradingView.\n\n"
        "Comenzi:\n"
        "• /price BTC\n"
        "• /bubbles 24h\n"
        "• /trending\n"
        "• /stats\n"
        "• /sector ai\n"
        "• /alert BTC 70000\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def cmd_help(update, context):
    text = (
        "📖 *Comenzi disponibile*\n\n"
        "/price `<coin>` — Pret live\n"
        "  ex: `/price BTC` sau `/price bitcoin`\n\n"
        "/top — Top 10 dupa market cap\n\n"
        "/trending — Trending pe CoinGecko\n\n"
        "/bubbles — Lista CryptoBubbles 24h\n"
        "/bubbles `1h` `7d` `30d` `1y` — Alta perioada\n\n"
        "/stats — Statistici piata + Market Score\n\n"
        "/sector — Lista sectoare crypto\n"
        "/sector `<nume>` — Ex: `/sector ai`\n\n"
        "/alert `<coin> <pret>` — Alerta de pret\n"
        "  ex: `/alert BTC 70000`\n\n"
        "/myalerts — Alertele tale active\n\n"
        "/removealert `<numar>` — Sterge alerta\n\n"
        "/help — Acest mesaj\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_price(update, context):
    if not context.args:
        await update.message.reply_text("Folosire: `/price BTC`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    await update.message.reply_text("⏳ Se incarca datele...")
    slug = resolve_slug(query)
    data = get_coin_data(slug)
    if not data:
        await update.message.reply_text(
            "❌ *" + query.upper() + "* nu a fost gasit.\nIncearca: `/price BTC`, `/price ETH`",
            parse_mode="Markdown")
        return
    text = (
        data["name"] + " (" + data["symbol"] + ")  Rank #" + str(data["rank"]) + "\n\n"
        "Pret:      " + fmt_price(data["price"]) + "\n"
        "1h:        " + fmt_change(data["change_1h"]) + "\n"
        "24h:       " + fmt_change(data["change_24h"]) + "\n"
        "7 zile:    " + fmt_change(data["change_7d"]) + "\n"
        "30 zile:   " + fmt_change(data["change_30d"]) + "\n\n"
        "24h High:  " + fmt_price(data["high_24h"]) + "\n"
        "24h Low:   " + fmt_price(data["low_24h"]) + "\n"
        "Mkt Cap:   " + fmt_large(data["market_cap"]) + "\n"
        "Volum 24h: " + fmt_large(data["volume_24h"]) + "\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="price:" + slug)]]
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_top(update, context):
    await update.message.reply_text("⏳ Se incarca top 10...")
    coins = get_top_coins(10)
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obtine datele.")
        return
    lines = ["*🏆 Top 10 dupa Market Cap*\n"]
    for i, c in enumerate(coins, 1):
        chg   = c.get("change_24h") or 0
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(
            str(i) + ". *" + c["symbol"] + "* — " + fmt_price(c["price"]) + "  "
            + ("🟢" if chg >= 0 else "🔴") + " " + arrow + "{:.1f}%".format(abs(chg))
        )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_trending(update, context):
    await update.message.reply_text("⏳ Se incarca trending...")
    coins = get_trending_coins()
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obtine datele.")
        return
    lines = ["*🔥 Trending pe CoinGecko*\n"]
    for item in coins[:7]:
        c         = item["item"]
        rank      = c.get("market_cap_rank", "?")
        chg       = c.get("change_24h", 0)
        chg_emoji = "🟢" if chg >= 0 else "🔴"
        sign      = "+" if chg >= 0 else ""
        lines.append("• " + c["name"] + " (" + c["symbol"] + ")  Rank #" + str(rank) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_bubbles(update, context):
    valid = ["1h", "24h", "7d", "30d", "1y"]
    period = context.args[0].lower() if context.args else "24h"
    if period not in valid:
        await update.message.reply_text(
            "Folosire: `/bubbles 24h`\nOptiuni: `1h`, `24h`, `7d`, `30d`, `1y`",
            parse_mode="Markdown")
        return
    await update.message.reply_text("⏳ Se incarca CryptoBubbles (" + period + ")...")
    coins = get_bubbles_data(period)
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obtine datele.")
        return
    pages = format_bubbles(coins, period)
    keyboard = [[
        InlineKeyboardButton("1h",  callback_data="bubbles:1h"),
        InlineKeyboardButton("24h", callback_data="bubbles:24h"),
        InlineKeyboardButton("7d",  callback_data="bubbles:7d"),
        InlineKeyboardButton("30d", callback_data="bubbles:30d"),
        InlineKeyboardButton("1y",  callback_data="bubbles:1y"),
    ]]
    for i, page in enumerate(pages):
        if i == 0:
            await update.message.reply_text(page, parse_mode="Markdown",
                                            reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(page, parse_mode="Markdown")

async def cmd_stats(update, context):
    msg = await update.message.reply_text("⏳ Se calculeaza statisticile pietei...")
    fg = global_data = prices = None
    for attempt in range(3):
        if attempt > 0:
            await asyncio.sleep(2)
        fg          = get_fear_greed()
        time.sleep(0.5)
        global_data = get_global_market()
        time.sleep(0.5)
        prices      = get_btc_eth_prices()
        if fg and global_data and prices:
            break
    if not fg or not global_data or not prices:
        await msg.edit_text("❌ Nu s-au putut obtine datele. Incearca din nou in 1 minut.")
        return
    text = format_stats(fg, global_data, prices)
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_sector(update, context):
    if not context.args:
        lines = ["Sectoare disponibile:\n"]
        for key, (_, label) in SECTORS.items():
            lines.append("• /sector " + key + " — " + label)
        lines.append("\nEx: /sector ai")
        await update.message.reply_text("\n".join(lines))
        return
    key = context.args[0].lower()
    if key not in SECTORS:
        keys = ", ".join(["`" + k + "`" for k in SECTORS.keys()])
        await update.message.reply_text("❌ Sector necunoscut. Disponibile:\n" + keys, parse_mode="Markdown")
        return
    category_id, label = SECTORS[key]
    await update.message.reply_text("⏳ Se incarca sectorul " + label + "...")
    coins = get_sector_coins(category_id)
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obtine datele. Incearca din nou.")
        return
    lines = [label + " - Top " + str(len(coins)) + " dupa market cap\n"]
    for c in coins:
        chg       = c["change_24h"]
        chg_emoji = "🟢" if chg >= 0 else "🔴"
        sign      = "+" if chg >= 0 else ""
        lines.append(c["symbol"] + " #" + str(c["rank"]) + "  " + fmt_price(c["price"]) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="sector:" + key)]]
    await update.message.reply_text("\n".join(lines),
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_alert(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Folosire: `/alert BTC 70000`", parse_mode="Markdown")
        return
    query = context.args[0]
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Pret invalid.", parse_mode="Markdown")
        return
    slug = resolve_slug(query)
    data = get_coin_data(slug)
    if not data:
        await update.message.reply_text("❌ *" + query.upper() + "* nu a fost gasit.", parse_mode="Markdown")
        return
    current   = data["price"]
    direction = "above" if target > current else "below"
    uid = update.effective_user.id
    if uid not in user_alerts:
        user_alerts[uid] = []
    user_alerts[uid].append({
        "slug": slug, "symbol": data["symbol"],
        "name": data["name"], "target": target, "direction": direction,
    })
    save_alerts()
    arrow = "📈 creste pana la" if direction == "above" else "📉 scade pana la"
    await update.message.reply_text(
        "✅ Alerta setata: *" + data["name"] + "* " + arrow + " " + fmt_price(target) + "\n"
        "_(Pret curent: " + fmt_price(current) + ")_",
        parse_mode="Markdown")

async def cmd_myalerts(update, context):
    uid    = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text("Nu ai alerte active. Foloseste /alert.")
        return
    lines = ["*Alertele tale*\n"]
    for i, a in enumerate(alerts, 1):
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(str(i) + ". *" + a["name"] + "* (" + a["symbol"] + ") " + arrow + " " + fmt_price(a["target"]))
    lines.append("\nFoloseste `/removealert <numar>` pentru a sterge.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_removealert(update, context):
    uid    = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text("Nu ai alerte de sters.")
        return
    if not context.args:
        await update.message.reply_text("Folosire: `/removealert 1`", parse_mode="Markdown")
        return
    try:
        n       = int(context.args[0])
        removed = alerts.pop(n - 1)
        save_alerts()
        await update.message.reply_text(
            "🗑 Alerta stearsa: *" + removed["name"] + "* @ " + fmt_price(removed["target"]),
            parse_mode="Markdown")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Numar invalid. Foloseste /myalerts.")

# ─── INLINE BUTTON CALLBACKS ───────────────────────────────────────────────────

async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "top":
        coins = get_top_coins(10)
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obtine datele.")
            return
        lines = ["*🏆 Top 10 dupa Market Cap*\n"]
        for i, c in enumerate(coins, 1):
            chg   = c.get("change_24h") or 0
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(str(i) + ". *" + c["symbol"] + "* — " + fmt_price(c["price"]) + "  " + ("🟢" if chg >= 0 else "🔴") + " " + arrow + "{:.1f}%".format(abs(chg)))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "trending":
        # Sterge cache pentru a obtine date proaspete cu procente
        if "trending" in _cache:
            del _cache["trending"]
        coins = get_trending_coins()
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obtine datele.")
            return
        lines = ["*🔥 Trending pe CoinGecko*\n"]
        for item in coins[:7]:
            c         = item["item"]
            rank      = c.get("market_cap_rank", "?")
            chg       = c.get("change_24h", 0)
            chg_emoji = "🟢" if chg >= 0 else "🔴"
            sign      = "+" if chg >= 0 else ""
            lines.append("• " + c["name"] + " (" + c["symbol"] + ")  Rank #" + str(rank) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("bubbles:"):
        period = data.split(":", 1)[1]
        await query.edit_message_text("⏳ Se incarca CryptoBubbles (" + period + ")...", parse_mode="Markdown")
        coins = get_bubbles_data(period)
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obtine datele.")
            return
        pages = format_bubbles(coins, period)
        keyboard = [[
            InlineKeyboardButton("1h",  callback_data="bubbles:1h"),
            InlineKeyboardButton("24h", callback_data="bubbles:24h"),
            InlineKeyboardButton("7d",  callback_data="bubbles:7d"),
            InlineKeyboardButton("30d", callback_data="bubbles:30d"),
            InlineKeyboardButton("1y",  callback_data="bubbles:1y"),
        ]]
        await query.edit_message_text(pages[0], parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        for page in pages[1:]:
            await query.message.reply_text(page, parse_mode="Markdown")

    elif data == "stats":
        fg = global_data = prices = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2)
            fg          = get_fear_greed()
            time.sleep(0.5)
            global_data = get_global_market()
            time.sleep(0.5)
            prices      = get_btc_eth_prices()
            if fg and global_data and prices:
                break
        if not fg or not global_data or not prices:
            await query.edit_message_text("❌ Nu s-au putut obtine datele. Incearca in 1 minut.")
            return
        text = format_stats(fg, global_data, prices)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("sector:"):
        key = data.split(":", 1)[1]
        if key not in SECTORS:
            await query.answer("Sector invalid.")
            return
        category_id, label = SECTORS[key]
        coins = get_sector_coins(category_id)
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obtine datele.")
            return
        lines = [label + " - Top " + str(len(coins)) + " dupa market cap\n"]
        for c in coins:
            chg       = c["change_24h"]
            chg_emoji = "🟢" if chg >= 0 else "🔴"
            sign      = "+" if chg >= 0 else ""
            lines.append(c["symbol"] + " #" + str(c["rank"]) + "  " + fmt_price(c["price"]) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="sector:" + key)]]
        await query.edit_message_text("\n".join(lines),
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("price:"):
        slug = data.split(":", 1)[1]
        info = get_coin_data(slug)
        if not info:
            await query.edit_message_text("❌ Nu s-au putut obtine datele.")
            return
        text = (
            info["name"] + " (" + info["symbol"] + ")  Rank #" + str(info["rank"]) + "\n\n"
            "Pret:      " + fmt_price(info["price"]) + "\n"
            "1h:        " + fmt_change(info["change_1h"]) + "\n"
            "24h:       " + fmt_change(info["change_24h"]) + "\n"
            "7 zile:    " + fmt_change(info["change_7d"]) + "\n"
            "30 zile:   " + fmt_change(info["change_30d"]) + "\n\n"
            "24h High:  " + fmt_price(info["high_24h"]) + "\n"
            "24h Low:   " + fmt_price(info["low_24h"]) + "\n"
            "Mkt Cap:   " + fmt_large(info["market_cap"]) + "\n"
            "Volum 24h: " + fmt_large(info["volume_24h"]) + "\n"
        )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="price:" + slug)]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "help":
        text = (
            "📖 *Comenzi disponibile*\n\n"
            "/price `<coin>` — Pret live\n"
            "/top — Top 10 monede\n"
            "/trending — Trending CoinGecko\n"
            "/bubbles `<perioada>` — CryptoBubbles\n"
            "/stats — Statistici piata\n"
            "/sector `<nume>` — Monede sector\n"
            "/alert `<coin> <pret>` — Alerta pret\n"
            "/myalerts — Alertele tale\n"
            "/removealert `<numar>` — Sterge alerta\n"
        )
        await query.edit_message_text(text, parse_mode="Markdown")

# ─── BACKGROUND JOBS ───────────────────────────────────────────────────────────

async def check_alerts(context):
    if not user_alerts:
        return
    for uid, alerts in list(user_alerts.items()):
        to_remove = []
        for i, alert in enumerate(alerts):
            data = get_coin_data(alert["slug"])
            if not data:
                continue
            current   = data["price"]
            target    = alert["target"]
            direction = alert.get("direction", "above")
            hit = (current >= target) if direction == "above" else (current <= target)
            if hit:
                verb = "crescut la" if direction == "above" else "scazut la"
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            "🔔 *Alerta de pret activata!*\n\n"
                            "*" + alert["name"] + "* (" + alert["symbol"] + ") a " + verb + " " + fmt_price(current) + "\n"
                            "Tinta ta era: " + fmt_price(target)
                        ),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error("Alert send failed: " + str(e))
                to_remove.append(i)
        for i in reversed(to_remove):
            alerts.pop(i)
        if to_remove:
            save_alerts()

async def auto_stats_job(context):
    try:
        fg = global_data = prices = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2)
            fg          = get_fear_greed()
            time.sleep(0.5)
            global_data = get_global_market()
            time.sleep(0.5)
            prices      = get_btc_eth_prices()
            if fg and global_data and prices:
                break
        if not fg or not global_data or not prices:
            return
        text = format_stats(fg, global_data, prices)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID, text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error("auto_stats_job error: " + str(e))

async def auto_trending_job(context):
    try:
        coins = get_trending_coins()
        if not coins:
            return
        lines = ["*🔥 Trending pe CoinGecko*\n"]
        for item in coins[:7]:
            c         = item["item"]
            rank      = c.get("market_cap_rank", "?")
            chg       = c.get("change_24h", 0)
            chg_emoji = "🟢" if chg >= 0 else "🔴"
            sign      = "+" if chg >= 0 else ""
            lines.append("• " + c["name"] + " (" + c["symbol"] + ")  Rank #" + str(rank) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text="\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error("auto_trending_job error: " + str(e))

async def pump_alert_job(context):
    try:
        slugs = [slug for slug, _ in BUBBLES_COINS]
        data = cg_get("/coins/markets", params={
            "vs_currency": "usd",
            "ids": ",".join(slugs),
            "order": "market_cap_desc",
            "per_page": 100,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h,7d,30d",
        }, timeout=30)
        if not data:
            return
        now = time.time()
        for c in data:
            symbol = c.get("symbol", "").upper()
            price  = c.get("current_price", 0)
            periods = {
                "24h": c.get("price_change_percentage_24h") or 0,
                "7D":  c.get("price_change_percentage_7d_in_currency") or 0,
                "30D": c.get("price_change_percentage_30d_in_currency") or 0,
            }
            for period_label, chg in periods.items():
                if chg < PUMP_THRESHOLD:
                    continue
                alert_key = symbol + ":" + period_label
                last_sent = _pump_alerts_sent.get(alert_key, 0)
                if now - last_sent < PUMP_COOLDOWN:
                    continue
                _pump_alerts_sent[alert_key] = now
                text = (
                    "🚀 *PUMP ALERT — " + symbol + "*\n"
                    "━" * 18 + "\n"
                    "💰 Pret curent: `" + fmt_price(price) + "`\n"
                    "📈 Crestere " + period_label + ": *+" + "{:.1f}%".format(chg) + "* 🟢\n\n"
                    "⚠️ _Acesta nu este sfat financiar._"
                )
                try:
                    await context.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=text,
                        parse_mode="Markdown")
                except Exception as e:
                    logger.error("pump_alert send error: " + str(e))
    except Exception as e:
        logger.error("pump_alert_job error: " + str(e))


async def cmd_test_auto(update, context):
    """Trimite imediat stats si trending in chat-ul curent pentru testare."""
    chat_id = update.effective_chat.id
    await update.message.reply_text("⏳ Se trimit mesajele de test...")

    # Stats
    try:
        fg = global_data = prices = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2)
            fg          = get_fear_greed()
            time.sleep(0.5)
            global_data = get_global_market()
            time.sleep(0.5)
            prices      = get_btc_eth_prices()
            if fg and global_data and prices:
                break
        if fg and global_data and prices:
            text = format_stats(fg, global_data, prices)
            keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
            await context.bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text("Eroare stats: " + str(e))

    # Trending
    try:
        coins = get_trending_coins()
        if coins:
            lines = ["*Trending pe CoinGecko*\n"]
            for item in coins[:7]:
                c         = item["item"]
                rank      = c.get("market_cap_rank", "?")
                chg       = c.get("change_24h", 0)
                chg_emoji = "🟢" if chg >= 0 else "🔴"
                sign      = "+" if chg >= 0 else ""
                lines.append("• " + c["name"] + " (" + c["symbol"] + ")  Rank #" + str(rank) + "  " + chg_emoji + " " + sign + "{:.1f}%".format(chg))
            keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
            await context.bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text("Eroare trending: " + str(e))

    await update.message.reply_text("✅ Test finalizat!")

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("chatid",      cmd_chatid))
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("price",       cmd_price))
    app.add_handler(CommandHandler("top",         cmd_top))
    app.add_handler(CommandHandler("trending",    cmd_trending))
    app.add_handler(CommandHandler("bubbles",     cmd_bubbles))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("sector",      cmd_sector))
    app.add_handler(CommandHandler("alert",       cmd_alert))
    app.add_handler(CommandHandler("myalerts",    cmd_myalerts))
    app.add_handler(CommandHandler("removealert", cmd_removealert))
    #app.add_handler(CommandHandler("test_auto",   cmd_test_auto))  # Dezactiveaza dupa testare
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(check_alerts,   interval=CHECK_ALERTS_INTERVAL, first=10)
    app.job_queue.run_repeating(pump_alert_job, interval=1800, first=120)

    ro_tz = pytz.timezone("Europe/Bucharest")
    app.job_queue.run_daily(auto_stats_job,    time=datetime.time(12, 0, tzinfo=ro_tz))
    app.job_queue.run_daily(auto_stats_job,    time=datetime.time(0,  0, tzinfo=ro_tz))
    app.job_queue.run_daily(auto_trending_job, time=datetime.time(12, 5, tzinfo=ro_tz))
    app.job_queue.run_daily(auto_trending_job, time=datetime.time(0,  5, tzinfo=ro_tz))

    print("CryptoBot ruleaza... Apasa Ctrl+C pentru a opri.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
