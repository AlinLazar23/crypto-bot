"""
Crypto Market Updates Telegram Bot
====================================
Surse: CoinGecko (toate datele) + TradingView (analiză)
Fără API key necesar! Funcționează în orice regiune.

Requirements:
    pip install python-telegram-bot[job-queue] requests tradingview-ta

Commands:
    /start           - Bun venit
    /price BTC       - Preț live
    /top             - Top 10 după market cap
    /trending        - Trending CoinGecko
    /bubbles         - Lista CryptoBubbles (1h/24h/7d/30d/1y)
    /analiza BTC     - Analiză tehnică TradingView
    /alert BTC 70000 - Alertă de preț
    /myalerts        - Alertele tale
    /removealert 1   - Șterge alertă
    /help            - Ajutor
"""

import os
import time
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")  # ← Pune token-ul în Railway Variables, nu aici!
ADMIN_ID       = 5988060477  # Singurul user care poate folosi botul
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CHECK_ALERTS_INTERVAL = 60

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
user_alerts: dict[int, list[dict]] = {}

# ─── ADMIN CHECK ───────────────────────────────────────────────────────────────

def is_admin(update) -> bool:
    return update.effective_user.id == ADMIN_ID

async def deny(update) -> None:
    await update.message.reply_text("🔒 Acest bot este privat.")

# ─── CACHE (evită rate limiting CoinGecko) ─────────────────────────────────────
_cache: dict[str, tuple[any, float]] = {}  # key → (data, timestamp)
CACHE_TTL = 120  # secunde (2 minute)

def cache_get(key: str):
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None

def cache_set(key: str, data):
    _cache[key] = (data, time.time())

# ─── MONEDE CRYPTOBUBBLES ──────────────────────────────────────────────────────
# Exact monedele vizibile pe cryptobubbles.net (din screenshot-urile tale)
# Format: (slug_coingecko, simbol_afișat)

BUBBLES_COINS = [
    ("bitcoin",               "BTC"),
    ("ethereum",              "ETH"),
    ("tether",                "USDT"),
    ("usd-coin",              "USDC"),
    ("dogecoin",              "DOGE"),
    ("hyperliquid",           "HYPE"),
    ("cardano",               "ADA"),
    ("chainlink",             "LINK"),
    ("avalanche-2",           "AVAX"),
    ("sui",                   "SUI"),
    ("internet-computer",     "ICP"),
    ("polkadot",              "DOT"),
    ("astar",                 "ASTR"),
    ("cosmos",                "ATOM"),
    ("algorand",              "ALGO"),
    ("arbitrum",              "ARB"),
    ("filecoin",              "FIL"),
    ("vechain",               "VET"),
    ("virtuals-protocol",     "VIRTUAL"),
    ("sei-network",           "SEI"),
    ("injective-protocol",    "INJ"),
    ("celestia",              "TIA"),
    ("the-graph",             "GRT"),
    ("elrond-erd-2",          "EGLD"),
    ("binancecoin",           "BNB"),
    ("ripple",                "XRP"),
    ("fetch-ai",              "FET"),
    ("gala",                  "GALA"),
]

# ─── FORMATARE ─────────────────────────────────────────────────────────────────

def fmt_price(value) -> str:
    if value is None:
        return "N/A"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}"

def fmt_large(value) -> str:
    if not value:
        return "N/A"
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"

def fmt_change(pct) -> str:
    if pct is None:
        return "N/A"
    arrow = "🟢 ▲" if pct >= 0 else "🔴 ▼"
    return f"{arrow} {abs(pct):.2f}%"

def fmt_change_short(pct) -> str:
    """Versiune scurtă pentru tabel bubbles."""
    if pct is None:
        return "  N/A "
    sign  = "+" if pct >= 0 else ""
    emoji = "🟢" if pct >= 0 else "🔴"
    return f"{emoji}{sign}{pct:.1f}%"

# ─── MAP SLUG COINGECKO ────────────────────────────────────────────────────────

COIN_SLUG_MAP = {
     "BTC": "bitcoin", "ETH": "ethereum",
    "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "DOT": "polkadot", "AVAX": "avalanche-2",
    "LINK": "chainlink", "ATOM": "cosmos",
    "ALGO": "algorand", "SUI": "sui", "ARB": "arbitrum", "INJ": "injective-protocol",
    "FET": "fetch-ai", "ICP": "internet-computer", "FIL": "filecoin", "VET": "vechain", "SEI": "sei-network",
    "TIA": "celestia", "GRT": "the-graph", "EGLD": "elrond-erd-2",
    "VIRTUAL": "virtuals-protocol", "HYPE": "hyperliquid",
    "ASTR": "astar", "GALA": "gala",
    # nume comune
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

def resolve_slug(query: str) -> str:
    q    = query.strip()
    slug = COIN_SLUG_MAP.get(q.upper()) or COIN_SLUG_MAP.get(q.lower())
    return slug if slug else q.lower()

# ─── DATE COINGECKO ────────────────────────────────────────────────────────────

def get_coin_data(slug: str) -> dict | None:
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/{slug}",
            params={"localization": "false", "tickers": "false",
                    "community_data": "false", "developer_data": "false"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        m = d["market_data"]
        return {
            "slug":       slug,
            "symbol":     d["symbol"].upper(),
            "name":       d["name"],
            "rank":       d.get("market_cap_rank", "N/A"),
            "price":      m["current_price"].get("usd", 0),
            "change_1h":  m.get("price_change_percentage_1h_in_currency", {}).get("usd") or 0,
            "change_24h": m.get("price_change_percentage_24h") or 0,
            "change_7d":  m.get("price_change_percentage_7d") or 0,
            "change_30d": m.get("price_change_percentage_30d") or 0,
            "change_1y":  m.get("price_change_percentage_1y") or 0,
            "high_24h":   m["high_24h"].get("usd", 0),
            "low_24h":    m["low_24h"].get("usd", 0),
            "market_cap": m["market_cap"].get("usd", 0),
            "volume_24h": m["total_volume"].get("usd", 0),
        }
    except Exception as e:
        logger.error(f"get_coin_data error ({slug}): {e}")
    return None

def get_top_coins(limit: int = 10) -> list[dict]:
    cache_key = f"top:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": limit, "page": 1, "sparkline": "false"},
            timeout=10,
        )
        if r.status_code == 200:
            result = [{"symbol": c["symbol"].upper(), "name": c["name"],
                     "slug": c["id"], "price": c["current_price"],
                     "change_24h": c.get("price_change_percentage_24h") or 0}
                    for c in r.json()]
            cache_set(cache_key, result)
            return result
    except Exception as e:
        logger.error(f"get_top_coins error: {e}")
    return []

def get_trending_coins() -> list[dict]:
    try:
        r = requests.get(f"{COINGECKO_BASE}/search/trending", timeout=10)
        if r.status_code == 200:
            return r.json().get("coins", [])
    except Exception as e:
        logger.error(f"get_trending_coins error: {e}")
    return []

def get_bubbles_data(period: str = "24h") -> list[dict]:
    """
    Fetch toate monedele din lista CryptoBubbles cu performanța pe perioada cerută.
    Folosește cache 2 minute pentru a evita rate limiting CoinGecko.
    """
    cache_key = f"bubbles:{period}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.info(f"Cache hit pentru bubbles:{period}")
        return cached

    slugs = [slug for slug, _ in BUBBLES_COINS]

    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": ",".join(slugs),
                "order": "market_cap_desc",
                "per_page": 100,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d,30d,1y",
            },
            timeout=15,
        )
        if r.status_code == 200:
            result = []
            for c in r.json():
                result.append({
                    "slug":       c["id"],
                    "symbol":     c["symbol"].upper(),
                    "name":       c["name"],
                    "rank":       c.get("market_cap_rank", 999),
                    "price":      c.get("current_price", 0),
                    "change_1h":  c.get("price_change_percentage_1h_in_currency") or 0,
                    "change_24h": c.get("price_change_percentage_24h") or 0,
                    "change_7d":  c.get("price_change_percentage_7d_in_currency") or 0,
                    "change_30d": c.get("price_change_percentage_30d_in_currency") or 0,
                    "change_1y":  c.get("price_change_percentage_1y_in_currency") or 0,
                    "market_cap": c.get("market_cap", 0),
                    "volume_24h": c.get("total_volume", 0),
                })
            cache_set(cache_key, result)
            return result
    except Exception as e:
        logger.error(f"get_bubbles_data error: {e}")
    return []

# ─── TRADINGVIEW ───────────────────────────────────────────────────────────────

def get_tv_analysis(symbol: str) -> object | None:
    try:
        from tradingview_ta import TA_Handler, Interval
        handler = TA_Handler(
            symbol=f"{symbol}USDT",
            screener="crypto",
            exchange="BINANCE",
            interval=Interval.INTERVAL_1_DAY,
        )
        return handler.get_analysis()
    except Exception as e:
        logger.error(f"TradingView error: {e}")
    return None

# ─── FORMAT BUBBLES ────────────────────────────────────────────────────────────

def format_bubbles(coins: list[dict], period: str) -> list[str]:
    """
    Împarte lista în mesaje de max ~4000 caractere (limita Telegram).
    Returnează o listă de string-uri (pagini).
    """
    period_key = {
        "1h": "change_1h", "24h": "change_24h",
        "7d": "change_7d", "30d": "change_30d", "1y": "change_1y",
    }.get(period, "change_24h")

    # Sortează după schimbare descrescătoare
    sorted_coins = sorted(coins, key=lambda c: c.get(period_key, 0), reverse=True)

    period_label = {"1h": "1 Oră", "24h": "24 Ore", "7d": "7 Zile",
                    "30d": "30 Zile", "1y": "1 An"}.get(period, period)

    header = (
        f"🫧 *CryptoBubbles — {period_label}*\n"
        f"_{len(coins)} monede sortate după performanță_\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    lines = []
    for c in sorted_coins:
        chg   = c.get(period_key, 0)
        emoji = "🟢" if chg >= 0 else "🔴"
        sign  = "+" if chg >= 0 else ""
        line  = (
            f"{emoji} *{c['symbol']}* `#{c['rank']}`  "
            f"`{fmt_price(c['price'])}`  "
            f"`{sign}{chg:.1f}%`\n"
        )
        lines.append(line)

    # Împarte în pagini
    pages = []
    current = header
    for line in lines:
        if len(current) + len(line) > 3800:
            pages.append(current)
            current = f"🫧 *CryptoBubbles — {period_label}* _(continuare)_\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        current += line
    if current.strip():
        pages.append(current)

    return pages

# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────


# ─── STATS DATA SOURCES ────────────────────────────────────────────────────────

def get_fear_greed() -> dict | None:
    """Fear & Greed Index de pe alternative.me — gratuit, fără API key."""
    try:
        r = requests.get(
            "https://api.alternative.me/fng/?limit=8",
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", [])
            if not data:
                return None
            today     = data[0]
            yesterday = data[1] if len(data) > 1 else data[0]
            week_vals = [int(d["value"]) for d in data]
            return {
                "value":      int(today["value"]),
                "label":      today["value_classification"],
                "yesterday":  int(yesterday["value"]),
                "week_avg":   round(sum(week_vals) / len(week_vals), 1),
                "history":    week_vals,
            }
    except Exception as e:
        logger.error(f"get_fear_greed error: {e}")
    return None

def get_global_market() -> dict | None:
    """Date globale piață: market cap, volum, dominance — de pe CoinGecko."""
    try:
        r = requests.get(f"{COINGECKO_BASE}/global", timeout=10)
        if r.status_code == 200:
            d = r.json().get("data", {})
            return {
                "total_market_cap":    d.get("total_market_cap", {}).get("usd", 0),
                "total_volume_24h":    d.get("total_volume", {}).get("usd", 0),
                "btc_dominance":       round(d.get("market_cap_percentage", {}).get("btc", 0), 1),
                "eth_dominance":       round(d.get("market_cap_percentage", {}).get("eth", 0), 1),
                "market_cap_change_24h": d.get("market_cap_change_percentage_24h_usd", 0),
            }
    except Exception as e:
        logger.error(f"get_global_market error: {e}")
    return None

def get_btc_eth_prices() -> dict:
    """Prețuri BTC și ETH de pe CoinGecko."""
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd",
                    "include_24hr_change": "true"},
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            return {
                "btc_price":  d.get("bitcoin", {}).get("usd", 0),
                "btc_change": d.get("bitcoin", {}).get("usd_24h_change", 0),
                "eth_price":  d.get("ethereum", {}).get("usd", 0),
                "eth_change": d.get("ethereum", {}).get("usd_24h_change", 0),
            }
    except Exception as e:
        logger.error(f"get_btc_eth_prices error: {e}")
    return {}

# ─── STATS ENGINE ──────────────────────────────────────────────────────────────

def fng_emoji(value: int) -> str:
    if value <= 25:   return "😱"
    if value <= 45:   return "😰"
    if value <= 55:   return "😐"
    if value <= 75:   return "😄"
    return "🤑"

def fng_bar(value: int) -> str:
    filled = value // 10
    return "█" * filled + "░" * (10 - filled)

def interpret_fng(value: int) -> str:
    if value <= 20:
        return "💡 Panică extremă → zonă istorică de acumulare"
    if value <= 40:
        return "💡 Frică în piață → posibilă oportunitate de cumpărare"
    if value <= 60:
        return "💡 Piața este neutră → așteaptă confirmare direcție"
    if value <= 80:
        return "⚠️ Lăcomie crescută → fii precaut, nu urmări FOMO"
    return "🚨 Euforie extremă → risc ridicat de corecție"

def calc_market_score(fg: dict, global_data: dict, prices: dict) -> tuple[int, str]:
    """
    Calculează un scor 1-10 bazat pe sentiment, trend, volum, dominance.
    Returnează (scor, label).
    """
    score = 5.0  # neutru

    # Fear & Greed (0-100 → contribuție ±2)
    fng_val = fg.get("value", 50)
    if fng_val <= 20:   score += 1.5   # panică extremă = oportunitate
    elif fng_val <= 40: score += 0.5
    elif fng_val <= 60: score += 0.0
    elif fng_val <= 80: score -= 0.5
    else:               score -= 1.5   # euforie = risc

    # Trend F&G (față de ieri)
    trend = fng_val - fg.get("yesterday", fng_val)
    if trend > 5:    score += 0.5
    elif trend < -5: score -= 0.5

    # BTC dominance: >55% = altcoins slabe (bear for alts), <40% = altseason
    btc_dom = global_data.get("btc_dominance", 50)
    if btc_dom > 55:   score -= 0.5
    elif btc_dom < 42: score += 0.5

    # Market cap change 24h
    cap_chg = global_data.get("market_cap_change_24h", 0)
    if cap_chg > 3:    score += 1.0
    elif cap_chg > 1:  score += 0.5
    elif cap_chg < -3: score -= 1.0
    elif cap_chg < -1: score -= 0.5

    # BTC price change 24h
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

def generate_insight(fg: dict, global_data: dict, prices: dict) -> str:
    """Generează un insight automat bazat pe combinația de date."""
    fng_val = fg.get("value", 50)
    btc_chg = prices.get("btc_change", 0)
    cap_chg = global_data.get("market_cap_change_24h", 0)
    btc_dom = global_data.get("btc_dominance", 50)
    week_avg = fg.get("week_avg", 50)

    insights = []

    # Divergență F&G vs BTC price
    if fng_val <= 35 and btc_chg >= 0:
        insights.append("📊 Deși piața e în frică, BTC rezistă → posibilă acumulare instituțională")
    elif fng_val >= 70 and btc_chg < -1:
        insights.append("⚠️ Greed ridicat dar BTC scade → semnal de slăbiciune, fii atent")

    # Trend săptămânal vs azi
    if fng_val > week_avg + 10:
        insights.append("📈 Sentimentul s-a îmbunătățit față de săptămâna trecută → momentum pozitiv")
    elif fng_val < week_avg - 10:
        insights.append("📉 Sentimentul s-a deteriorat față de media săptămânii → prudență")

    # Market cap + volum
    if cap_chg > 2:
        insights.append("💹 Market cap-ul total crește cu volum → trend bullish confirmat")
    elif cap_chg < -2:
        insights.append("📉 Scădere generalizată în piață → risc crescut pe termen scurt")

    # BTC dominance
    if btc_dom > 58:
        insights.append("🔶 BTC dominance ridicat → altcoin-urile suferă, capital concentrat în BTC")
    elif btc_dom < 42:
        insights.append("🟣 BTC dominance scăzut → posibilă altseason în desfășurare")

    # Panică extremă
    if fng_val <= 15:
        insights.append("🚨 Panică extremă istorică → zonele acestea au coincis cu fundul pieței în trecut")

    if not insights:
        insights.append("➡️ Piața este echilibrată momentan — niciun semnal extrem detectat")

    return "\n".join(f"  {i}" for i in insights[:3])  # max 3 insights

def format_stats(fg: dict, global_data: dict, prices: dict) -> str:
    from datetime import datetime
    now = datetime.utcnow().strftime("%H:%M UTC")

    fng_val   = fg["value"]
    fng_label = fg["label"]
    fng_trend = fng_val - fg["yesterday"]
    if fng_trend > 0:
        trend_arrow = f"\u2191 +{fng_trend}"
    elif fng_trend < 0:
        trend_arrow = f"\u2193 {fng_trend}"
    else:
        trend_arrow = "\u2192 0"
    bar = fng_bar(fng_val)

    score, score_label = calc_market_score(fg, global_data, prices)
    score_bar = "\u2b50" * score + "\u2606" * (10 - score)
    insight   = generate_insight(fg, global_data, prices)

    cap_chg   = global_data.get("market_cap_change_24h", 0)
    cap_arrow = "\U0001f7e2 \u25b2" if cap_chg >= 0 else "\U0001f534 \u25bc"
    btc_arrow = "\U0001f7e2 \u25b2" if prices.get("btc_change", 0) >= 0 else "\U0001f534 \u25bc"
    eth_arrow = "\U0001f7e2 \u25b2" if prices.get("eth_change", 0) >= 0 else "\U0001f534 \u25bc"

    lines = [
        "\U0001f4ca *Market Stats* \u2014 " + now,
        "\u2501" * 20,
        "",
        "\U0001f9e0 *SENTIMENT PIAT\u0102*",
        fng_emoji(fng_val) + f" Fear & Greed: *{fng_val}/100* \u2014 _{fng_label}_",
        f"`[{bar}]`",
        f"\u2022 Fat\u0103 de ieri: `{trend_arrow}`",
        f"\u2022 Media 7 zile: `{fg['week_avg']}/100`",
        "\u2022 " + interpret_fng(fng_val),
        "",
        "\U0001f4b0 *OVERVIEW PIAT\u0102*",
        f"\u2022 BTC:  `{fmt_price(prices.get('btc_price', 0))}`  {btc_arrow} `{abs(prices.get('btc_change', 0)):.1f}%`",
        f"\u2022 ETH:  `{fmt_price(prices.get('eth_price', 0))}`  {eth_arrow} `{abs(prices.get('eth_change', 0)):.1f}%`",
        f"\u2022 Mkt Cap Total: `{fmt_large(global_data.get('total_market_cap', 0))}`  {cap_arrow} `{abs(cap_chg):.1f}%`",
        f"\u2022 Volum 24h:     `{fmt_large(global_data.get('total_volume_24h', 0))}`",
        f"\u2022 BTC Dominance: `{global_data.get('btc_dominance', 0)}%`",
        f"\u2022 ETH Dominance: `{global_data.get('eth_dominance', 0)}%`",
        "",
        "\U0001f9ea *INSIGHT AUTOMAT*",
        insight,
        "",
        f"\u26a1 *MARKET SCORE: {score}/10 \u2014 {score_label}*",
        f"`{score_bar}`",
        "_Bazat pe: sentiment + trend + volum + dominance_",
    ]
    return "\n".join(lines)

# ─── CMD STATS ─────────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return

    msg = await update.message.reply_text("⏳ Se calculează statisticile pieței...")

    fg          = get_fear_greed()
    global_data = get_global_market()
    prices      = get_btc_eth_prices()

    if not fg or not global_data or not prices:
        await msg.edit_text("❌ Nu s-au putut obține datele. Încearcă din nou.")
        return

    text = format_stats(fg, global_data, prices)
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
    await msg.edit_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Top 10",      callback_data="top"),
         InlineKeyboardButton("🔥 Trending",    callback_data="trending")],
        [InlineKeyboardButton("🫧 Bubbles 24h", callback_data="bubbles:24h"),
         InlineKeyboardButton("📈 Analiză BTC", callback_data="analiza:BTC")],
        [InlineKeyboardButton("📊 Stats",        callback_data="stats"),
         InlineKeyboardButton("❓ Help",          callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 *Bun venit la CryptoBot!*\n\n"
        "Date live din CoinGecko + TradingView.\n\n"
        "Încearcă:\n"
        "• /price BTC\n"
        "• /bubbles 24h\n"
        "• /bubbles 7d\n"
        "• /top\n"
        "• /analiza ETH\n"
        "• /alert BTC 70000\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    text = (
        "📖 *Comenzi disponibile*\n\n"
        "/price `<coin>` — Preț live\n"
        "  ex: `/price BTC` sau `/price bitcoin`\n\n"
        "/bubbles — Lista CryptoBubbles 24h\n"
        "/bubbles `1h` — Performanță 1 oră\n"
        "/bubbles `7d` — Performanță 7 zile\n"
        "/bubbles `30d` — Performanță 30 zile\n"
        "/bubbles `1y` — Performanță 1 an\n\n"
        "/top — Top 10 după market cap\n\n"
        "/trending — Trending pe CoinGecko\n\n"
        "/analiza `<coin>` — Analiză TradingView\n\n"
        "/stats — Statistici piață + Market Score\n\n"
        "/alert `<coin> <preț>` — Alertă de preț\n\n"
        "/myalerts — Alertele tale active\n\n"
        "/removealert `<număr>` — Șterge alerta\n\n"
        "/help — Acest mesaj\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    if not context.args:
        await update.message.reply_text("Folosire: `/price BTC`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    await update.message.reply_text("⏳ Se încarcă datele...")
    slug = resolve_slug(query)
    data = get_coin_data(slug)
    if not data:
        await update.message.reply_text(
            f"❌ *{query.upper()}* nu a fost găsit.\n"
            f"Încearcă: `/price BTC`, `/price ETH`, `/price bitcoin`",
            parse_mode="Markdown")
        return
    text = (
        f"*{data['name']}* ({data['symbol']})  •  Rank #{data['rank']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Preț:      {fmt_price(data['price'])}\n"
        f"📈 1h:        {fmt_change(data['change_1h'])}\n"
        f"📈 24h:       {fmt_change(data['change_24h'])}\n"
        f"📈 7 zile:    {fmt_change(data['change_7d'])}\n"
        f"📈 30 zile:   {fmt_change(data['change_30d'])}\n"
        f"─────────────────\n"
        f"📊 24h High:  {fmt_price(data['high_24h'])}\n"
        f"📊 24h Low:   {fmt_price(data['low_24h'])}\n"
        f"🏦 Mkt Cap:   {fmt_large(data['market_cap'])}\n"
        f"💹 Volum 24h: {fmt_large(data['volume_24h'])}\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{slug}")]]
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_bubbles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    valid_periods = ["1h", "24h", "7d", "30d", "1y"]
    period = context.args[0].lower() if context.args else "24h"
    if period not in valid_periods:
        await update.message.reply_text(
            "Folosire: `/bubbles 24h`\nOpțiuni: `1h`, `24h`, `7d`, `30d`, `1y`",
            parse_mode="Markdown")
        return

    await update.message.reply_text(
        f"⏳ Se încarcă CryptoBubbles ({period})...",
        parse_mode="Markdown")

    coins = get_bubbles_data(period)
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obține datele.")
        return

    pages = format_bubbles(coins, period)
    keyboard = [
        [
            InlineKeyboardButton("1h",  callback_data="bubbles:1h"),
            InlineKeyboardButton("24h", callback_data="bubbles:24h"),
            InlineKeyboardButton("7d",  callback_data="bubbles:7d"),
            InlineKeyboardButton("30d", callback_data="bubbles:30d"),
            InlineKeyboardButton("1y",  callback_data="bubbles:1y"),
        ]
    ]
    # Trimite prima pagină cu butoane, restul fără
    for i, page in enumerate(pages):
        if i == 0:
            await update.message.reply_text(
                page, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(page, parse_mode="Markdown")

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    await update.message.reply_text("⏳ Se încarcă top 10...")
    coins = get_top_coins(10)
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obține datele.")
        return
    lines = ["*🏆 Top 10 după Market Cap*\n"]
    for i, c in enumerate(coins, 1):
        chg   = c.get("change_24h") or 0
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(
            f"{i}. *{c['symbol']}* — {fmt_price(c['price'])}  "
            f"{'🟢' if chg>=0 else '🔴'} {arrow}{abs(chg):.1f}%"
        )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    await update.message.reply_text("⏳ Se încarcă trending...")
    coins = get_trending_coins()
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obține datele.")
        return
    lines = ["*🔥 Trending pe CoinGecko*\n"]
    for item in coins[:7]:
        c    = item["item"]
        rank = c.get("market_cap_rank", "?")
        lines.append(f"• *{c['name']}* ({c['symbol']})  •  Rank #{rank}")
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_analiza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    if not context.args:
        await update.message.reply_text("Folosire: `/analiza BTC`", parse_mode="Markdown")
        return
    query     = " ".join(context.args)
    slug      = resolve_slug(query)
    coin_info = get_coin_data(slug)
    symbol    = coin_info["symbol"] if coin_info else query.upper()

    await update.message.reply_text(f"⏳ Se analizează *{symbol}*...", parse_mode="Markdown")
    analysis = get_tv_analysis(symbol)
    if not analysis:
        await update.message.reply_text(
            f"❌ Nu s-a putut obține analiza pentru *{symbol}*.",
            parse_mode="Markdown")
        return

    s   = analysis.summary
    ind = analysis.indicators
    ma  = analysis.moving_averages
    rec = s.get("RECOMMENDATION", "N/A")
    emoji_map = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "NEUTRAL": "🟡",
                 "SELL": "🔴", "STRONG_SELL": "🔴🔴"}
    rec_emoji  = emoji_map.get(rec, "⚪")
    rsi    = ind.get("RSI") or 0
    macd   = ind.get("MACD.macd") or 0
    macd_s = ind.get("MACD.signal") or 0
    ema20  = ind.get("EMA20") or 0
    ema50  = ind.get("EMA50") or 0
    ema200 = ind.get("EMA200") or 0
    close  = ind.get("close") or 0
    rsi_txt  = "Supracumpărat ⚠️" if rsi >= 70 else ("Supravândut ⚠️" if rsi <= 30 else "Normal ✅")
    macd_txt = "🟢 Bullish" if macd > macd_s else "🔴 Bearish"
    buy_s = s.get("BUY", 0); neu_s = s.get("NEUTRAL", 0); sell_s = s.get("SELL", 0)
    buy_ma = ma.get("BUY", 0); neu_ma = ma.get("NEUTRAL", 0); sell_ma = ma.get("SELL", 0)
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT"
    text = (
        f"📊 *Analiză Tehnică — {symbol}/USDT*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{rec_emoji} *Semnal: {rec.replace('_', ' ')}*\n\n"
        f"*📈 Oscilatori* (🟢`{buy_s}` 🟡`{neu_s}` 🔴`{sell_s}`)\n"
        f"• RSI (14): `{rsi:.1f}` — {rsi_txt}\n"
        f"• MACD: {macd_txt}\n\n"
        f"*📉 Medii Mobile* (🟢`{buy_ma}` 🟡`{neu_ma}` 🔴`{sell_ma}`)\n"
        f"• EMA 20:  `{fmt_price(ema20)}`\n"
        f"• EMA 50:  `{fmt_price(ema50)}`\n"
        f"• EMA 200: `{fmt_price(ema200)}`\n"
        f"• Preț:    `{fmt_price(close)}`\n\n"
        f"[📈 Vezi graficul pe TradingView]({tv_link})"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"analiza:{symbol}")]]
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True)

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    if len(context.args) < 2:
        await update.message.reply_text("Folosire: `/alert BTC 70000`", parse_mode="Markdown")
        return
    query = context.args[0]
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Preț invalid.", parse_mode="Markdown")
        return
    slug = resolve_slug(query)
    data = get_coin_data(slug)
    if not data:
        await update.message.reply_text(
            f"❌ *{query.upper()}* nu a fost găsit.", parse_mode="Markdown")
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
    arrow = "📈 crește până la" if direction == "above" else "📉 scade până la"
    await update.message.reply_text(
        f"✅ Alertă setată: *{data['name']}* {arrow} {fmt_price(target)}\n"
        f"_(Preț curent: {fmt_price(current)})_",
        parse_mode="Markdown")

async def cmd_myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    uid    = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text("Nu ai alerte active. Folosește /alert.")
        return
    lines = ["*Alertele tale*\n"]
    for i, a in enumerate(alerts, 1):
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(f"{i}. *{a['name']}* ({a['symbol']}) {arrow} {fmt_price(a['target'])}")
    lines.append("\nFolosește `/removealert <număr>` pentru a șterge.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_removealert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await deny(update)
        return
    uid    = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text("Nu ai alerte de șters.")
        return
    if not context.args:
        await update.message.reply_text("Folosire: `/removealert 1`", parse_mode="Markdown")
        return
    try:
        n       = int(context.args[0])
        removed = alerts.pop(n - 1)
        await update.message.reply_text(
            f"🗑 Alertă ștearsă: *{removed['name']}* @ {fmt_price(removed['target'])}",
            parse_mode="Markdown")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Număr invalid. Folosește /myalerts.")

# ─── INLINE BUTTON CALLBACKS ───────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "top":
        coins = get_top_coins(10)
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        lines = ["*🏆 Top 10 după Market Cap*\n"]
        for i, c in enumerate(coins, 1):
            chg   = c.get("change_24h") or 0
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(
                f"{i}. *{c['symbol']}* — {fmt_price(c['price'])}  "
                f"{'🟢' if chg>=0 else '🔴'} {arrow}{abs(chg):.1f}%")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "trending":
        coins = get_trending_coins()
        lines = ["*🔥 Trending pe CoinGecko*\n"]
        for item in coins[:7]:
            c    = item["item"]
            rank = c.get("market_cap_rank", "?")
            lines.append(f"• *{c['name']}* ({c['symbol']})  •  Rank #{rank}")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("bubbles:"):
        period = data.split(":", 1)[1]
        await query.edit_message_text(
            f"⏳ Se încarcă CryptoBubbles ({period})...", parse_mode="Markdown")
        coins = get_bubbles_data(period)
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        pages   = format_bubbles(coins, period)
        keyboard = [[
            InlineKeyboardButton("1h",  callback_data="bubbles:1h"),
            InlineKeyboardButton("24h", callback_data="bubbles:24h"),
            InlineKeyboardButton("7d",  callback_data="bubbles:7d"),
            InlineKeyboardButton("30d", callback_data="bubbles:30d"),
            InlineKeyboardButton("1y",  callback_data="bubbles:1y"),
        ]]
        await query.edit_message_text(
            pages[0], parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))
        # Paginile extra ca mesaje noi
        for page in pages[1:]:
            await query.message.reply_text(page, parse_mode="Markdown")

    elif data == "stats":
        fg          = get_fear_greed()
        global_data = get_global_market()
        prices      = get_btc_eth_prices()
        if not fg or not global_data or not prices:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        text = format_stats(fg, global_data, prices)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "help":
        text = (
            "📖 *Comenzi disponibile*\n\n"
            "/price `<coin>` — Preț live\n"
            "/bubbles `<perioadă>` — CryptoBubbles\n"
            "/top — Top 10 monede\n"
            "/trending — Trending CoinGecko\n"
            "/analiza `<coin>` — Analiză TradingView\n"
            "/alert `<coin> <preț>` — Alertă de preț\n"
            "/myalerts — Alertele tale\n"
            "/removealert `<număr>` — Șterge alertă\n"
        )
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data.startswith("price:"):
        slug = data.split(":", 1)[1]
        info = get_coin_data(slug)
        if not info:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        text = (
            f"*{info['name']}* ({info['symbol']})  •  Rank #{info['rank']}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Preț:      {fmt_price(info['price'])}\n"
            f"📈 1h:        {fmt_change(info['change_1h'])}\n"
            f"📈 24h:       {fmt_change(info['change_24h'])}\n"
            f"📈 7 zile:    {fmt_change(info['change_7d'])}\n"
            f"📈 30 zile:   {fmt_change(info['change_30d'])}\n"
            f"─────────────────\n"
            f"📊 24h High:  {fmt_price(info['high_24h'])}\n"
            f"📊 24h Low:   {fmt_price(info['low_24h'])}\n"
            f"🏦 Mkt Cap:   {fmt_large(info['market_cap'])}\n"
            f"💹 Volum 24h: {fmt_large(info['volume_24h'])}\n"
        )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{slug}")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("analiza:"):
        symbol   = data.split(":", 1)[1]
        analysis = get_tv_analysis(symbol)
        if not analysis:
            await query.edit_message_text(
                f"❌ Nu s-a putut obține analiza pentru *{symbol}*.",
                parse_mode="Markdown")
            return
        s   = analysis.summary
        ind = analysis.indicators
        ma  = analysis.moving_averages
        rec = s.get("RECOMMENDATION", "N/A")
        emoji_map = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "NEUTRAL": "🟡",
                     "SELL": "🔴", "STRONG_SELL": "🔴🔴"}
        rec_emoji  = emoji_map.get(rec, "⚪")
        rsi    = ind.get("RSI") or 0
        macd   = ind.get("MACD.macd") or 0
        macd_s = ind.get("MACD.signal") or 0
        ema20  = ind.get("EMA20") or 0
        ema50  = ind.get("EMA50") or 0
        ema200 = ind.get("EMA200") or 0
        close  = ind.get("close") or 0
        rsi_txt  = "Supracumpărat ⚠️" if rsi >= 70 else ("Supravândut ⚠️" if rsi <= 30 else "Normal ✅")
        macd_txt = "🟢 Bullish" if macd > macd_s else "🔴 Bearish"
        buy_s = s.get("BUY", 0); neu_s = s.get("NEUTRAL", 0); sell_s = s.get("SELL", 0)
        buy_ma = ma.get("BUY", 0); neu_ma = ma.get("NEUTRAL", 0); sell_ma = ma.get("SELL", 0)
        tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT"
        text = (
            f"📊 *Analiză Tehnică — {symbol}/USDT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{rec_emoji} *Semnal: {rec.replace('_', ' ')}*\n\n"
            f"*📈 Oscilatori* (🟢`{buy_s}` 🟡`{neu_s}` 🔴`{sell_s}`)\n"
            f"• RSI (14): `{rsi:.1f}` — {rsi_txt}\n"
            f"• MACD: {macd_txt}\n\n"
            f"*📉 Medii Mobile* (🟢`{buy_ma}` 🟡`{neu_ma}` 🔴`{sell_ma}`)\n"
            f"• EMA 20:  `{fmt_price(ema20)}`\n"
            f"• EMA 50:  `{fmt_price(ema50)}`\n"
            f"• EMA 200: `{fmt_price(ema200)}`\n"
            f"• Preț:    `{fmt_price(close)}`\n\n"
            f"[📈 Vezi graficul pe TradingView]({tv_link})"
        )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"analiza:{symbol}")]]
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True)

# ─── BACKGROUND JOB: CHECK ALERTS ─────────────────────────────────────────────

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
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
                verb = "crescut la" if direction == "above" else "scăzut la"
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            f"🔔 *Alertă de preț activată!*\n\n"
                            f"*{alert['name']}* ({alert['symbol']}) a {verb} "
                            f"{fmt_price(current)}\n"
                            f"Ținta ta era: {fmt_price(target)}"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"Alert send failed: {e}")
                to_remove.append(i)
        for i in reversed(to_remove):
            alerts.pop(i)

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("price",       cmd_price))
    app.add_handler(CommandHandler("bubbles",     cmd_bubbles))
    app.add_handler(CommandHandler("top",         cmd_top))
    app.add_handler(CommandHandler("trending",    cmd_trending))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("analiza",     cmd_analiza))
    app.add_handler(CommandHandler("alert",       cmd_alert))
    app.add_handler(CommandHandler("myalerts",    cmd_myalerts))
    app.add_handler(CommandHandler("removealert", cmd_removealert))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(check_alerts, interval=CHECK_ALERTS_INTERVAL, first=10)

    print("🤖 CryptoBot rulează... Apasă Ctrl+C pentru a opri.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
