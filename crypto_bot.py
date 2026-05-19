"""
Crypto Market Updates Telegram Bot
====================================
Surse: CoinGecko (toate datele) + TradingView (analiză)
Fără API key necesar! Funcționează în orice regiune.

Requirements:
    pip install python-telegram-bot[job-queue] requests tradingview-ta pytz

Setup:
    1. Creează bot via @BotFather → copiază BOT_TOKEN
    2. Setează variabilele de mediu (Railway / .env):
       BOT_TOKEN, GROUP_CHAT_ID,
       TOPIC_COMENZI, TOPIC_PIATA, TOPIC_STIRI,
       TOPIC_DATE, TOPIC_PREDICTII
    3. (Opțional) CRYPTOPANIC_TOKEN pentru știri automate

Cum obții Thread ID-urile topicurilor:
    1. Adaugă botul în grup ca Admin
    2. Scrie /chatid în fiecare topic
    3. Setează valorile în Railway env vars

Roluri topicuri:
    Comenzi bot   ← singura zonă unde funcționează comenzile user
    Piață         ← trending automat la 12h
    Știri         ← feed știri crypto (dacă CRYPTOPANIC_TOKEN setat)
    Date & Analize← stats automat la 00:00 și 12:00
    Predicții     ← alerte de preț automate

Commands:
    /start           - Bun venit
    /price BTC       - Preț live
    /top             - Top 10 după market cap
    /trending        - Trending CoinGecko
    /bubbles         - Lista CryptoBubbles (1h/24h/7d/30d/1y)
    /stats           - Statistici piață + Market Score
    /alert BTC 70000 - Alertă de preț
    /myalerts        - Alertele tale
    /removealert 1   - Șterge alertă
    /help            - Ajutor
"""

import os
import json
import asyncio
import time
import datetime
import pytz
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
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "")
COINGECKO_BASE    = "https://api.coingecko.com/api/v3"
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "")

GROUP_CHAT_ID   = int(os.environ.get("GROUP_CHAT_ID",    "0"))
TOPIC_COMENZI   = int(os.environ.get("TOPIC_COMENZI",   "0"))
TOPIC_PIATA     = int(os.environ.get("TOPIC_PIATA",     "0"))
TOPIC_STIRI     = int(os.environ.get("TOPIC_STIRI",     "0"))
TOPIC_DATE      = int(os.environ.get("TOPIC_DATE",      "0"))
TOPIC_PREDICTII = int(os.environ.get("TOPIC_PREDICTII", "0"))

CHECK_ALERTS_INTERVAL = 60
TZ_RO = pytz.timezone("Europe/Bucharest")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── TRANSLATIONS ──────────────────────────────────────────────────────────────
user_lang: dict[int, str] = {}

TEXTS: dict[str, dict] = {
    "ro": {
        "topic_redirect":     "⚠️ Comenzile se trimit în topicul *Comenzi bot*.",
        "start_msg":          "👋 *Bun venit la CryptoBot!*\n\nDate live din CoinGecko.\n\nÎncearcă:\n• /price BTC\n• /bubbles 24h\n• /top\n• /alert BTC 70000\n",
        "help_msg":           "📖 *Comenzi disponibile*\n\n/price `<coin>` — Preț live\n  ex: `/price BTC`\n\n/bubbles — CryptoBubbles 24h\n/bubbles `1h|7d|30d|1y`\n\n/top — Top 10 după market cap\n\n/trending — Trending CoinGecko\n\n/stats — Statistici piață\n\n/alert `<coin> <preț>` — Alertă de preț\n\n/myalerts — Alertele tale\n\n/removealert `<nr>` — Șterge alerta\n\n/lang — Schimbă limba\n\n━━━━━━━━━━━━━━━━━━\n*Topicuri grup:*\n📊 *Piață* — trending 12h\n📰 *Știri* — știri crypto\n📈 *Date & Analize* — stats 00:00/12:00\n🔔 *Predicții* — alerte de preț\n",
        "price_loading":      "⏳ Se încarcă datele...",
        "price_not_found":    "❌ *{coin}* nu a fost găsit.\nÎncearcă: `/price BTC`, `/price ETH`, `/price bitcoin`",
        "price_usage":        "Folosire: `/price BTC`",
        "top_loading":        "⏳ Se încarcă top 10...",
        "top_title":          "*🏆 Top 10 după Market Cap*\n",
        "top_no_data":        "❌ Nu s-au putut obține datele.",
        "trending_loading":   "⏳ Se încarcă trending...",
        "trending_title":     "*🔥 Trending pe CoinGecko*\n",
        "bubbles_loading":    "⏳ Se încarcă CryptoBubbles ({period})...",
        "bubbles_usage":      "Folosire: `/bubbles 24h`\nOpțiuni: `1h`, `24h`, `7d`, `30d`, `1y`",
        "bubbles_no_data":    "❌ Nu s-au putut obține datele.",
        "bubbles_header":     "🫧 *CryptoBubbles — {label}*\n_{n} monede sortate după performanță_\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n",
        "bubbles_cont":       "🫧 *CryptoBubbles — {label}* _(continuare)_\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n",
        "period_labels":      {"1h": "1 Oră", "24h": "24 Ore", "7d": "7 Zile", "30d": "30 Zile", "1y": "1 An"},
        "stats_loading":      "⏳ Se calculează statisticile pieței...",
        "stats_no_data":      "❌ Nu s-au putut obține datele. Încearcă din nou în 1 minut.",
        "stats_sentiment":    "🧠 *SENTIMENT PIAȚĂ*",
        "stats_vs_yesterday": "Față de ieri",
        "stats_week_avg":     "Media 7 zile",
        "stats_overview":     "💰 *OVERVIEW PIAȚĂ*",
        "stats_mktcap":       "Mkt Cap Total",
        "stats_volume":       "Volum 24h",
        "stats_insight":      "🔬 *INSIGHT AUTOMAT*",
        "stats_score_label":  "Bazat pe: sentiment + trend + volum + dominance",
        "alert_usage":        "Folosire: `/alert BTC 70000`",
        "alert_invalid":      "❌ Preț invalid.",
        "alert_loading":      "⏳ Se caută *{coin}*...",
        "alert_not_found":    "❌ *{coin}* nu a fost găsit.",
        "alert_set":          "✅ Alertă setată: *{name}* {arrow} {price}\n_(Preț curent: {current})_\n_Notificarea va apărea în topicul Predicții._",
        "alert_rise":         "📈 crește până la",
        "alert_fall":         "📉 scade până la",
        "myalerts_none":      "Nu ai alerte active. Folosește `/alert` pentru a seta una.",
        "myalerts_title":     "*Alertele tale*\n",
        "myalerts_footer":    "\nFolosește `/removealert <număr>` pentru a șterge.",
        "removealert_none":   "Nu ai alerte de șters.",
        "removealert_usage":  "Folosire: `/removealert 1`",
        "removealert_done":   "🗑 Alertă ștearsă: *{name}* @ {price}",
        "removealert_bad":    "❌ Număr invalid. Folosește /myalerts.",
        "alert_triggered":    "🔔 *Alertă de preț activată!*\n\n*{name}* ({symbol}) a {verb} {price}\nȚinta ta era: {target}",
        "alert_rose":         "crescut la",
        "alert_fell":         "scăzut la",
        "lang_prompt":        "🌐 *Selectează limba / Select language:*",
        "lang_set":           "✅ Limbă setată: *Română* 🇷🇴",
        "fng_extreme_fear":   "💡 Panică extremă → zonă istorică de acumulare",
        "fng_fear":           "💡 Frică în piață → posibilă oportunitate de cumpărare",
        "fng_neutral":        "💡 Piața este neutră → așteaptă confirmare direcție",
        "fng_greed":          "⚠️ Lăcomie crescută → fii precaut, nu urmări FOMO",
        "fng_extreme_greed":  "🚨 Euforie extremă → risc ridicat de corecție",
    },
    "en": {
        "topic_redirect":     "⚠️ Commands must be sent in the *Commands* topic.",
        "start_msg":          "👋 *Welcome to CryptoBot!*\n\nLive data from CoinGecko.\n\nTry:\n• /price BTC\n• /bubbles 24h\n• /top\n• /alert BTC 70000\n",
        "help_msg":           "📖 *Available commands*\n\n/price `<coin>` — Live price\n  ex: `/price BTC`\n\n/bubbles — CryptoBubbles 24h\n/bubbles `1h|7d|30d|1y`\n\n/top — Top 10 by market cap\n\n/trending — Trending on CoinGecko\n\n/stats — Market statistics\n\n/alert `<coin> <price>` — Price alert\n\n/myalerts — Your alerts\n\n/removealert `<nr>` — Remove alert\n\n/lang — Change language\n\n━━━━━━━━━━━━━━━━━━\n*Group topics:*\n📊 *Market* — auto trending 12h\n📰 *News* — crypto news\n📈 *Data & Analysis* — auto stats 00:00/12:00\n🔔 *Predictions* — price alerts\n",
        "price_loading":      "⏳ Loading data...",
        "price_not_found":    "❌ *{coin}* not found.\nTry: `/price BTC`, `/price ETH`, `/price bitcoin`",
        "price_usage":        "Usage: `/price BTC`",
        "top_loading":        "⏳ Loading top 10...",
        "top_title":          "*🏆 Top 10 by Market Cap*\n",
        "top_no_data":        "❌ Could not fetch data.",
        "trending_loading":   "⏳ Loading trending...",
        "trending_title":     "*🔥 Trending on CoinGecko*\n",
        "bubbles_loading":    "⏳ Loading CryptoBubbles ({period})...",
        "bubbles_usage":      "Usage: `/bubbles 24h`\nOptions: `1h`, `24h`, `7d`, `30d`, `1y`",
        "bubbles_no_data":    "❌ Could not fetch data.",
        "bubbles_header":     "🫧 *CryptoBubbles — {label}*\n_{n} coins sorted by performance_\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n",
        "bubbles_cont":       "🫧 *CryptoBubbles — {label}* _(continued)_\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n",
        "period_labels":      {"1h": "1 Hour", "24h": "24 Hours", "7d": "7 Days", "30d": "30 Days", "1y": "1 Year"},
        "stats_loading":      "⏳ Calculating market statistics...",
        "stats_no_data":      "❌ Could not fetch data. Try again in 1 minute.",
        "stats_sentiment":    "🧠 *MARKET SENTIMENT*",
        "stats_vs_yesterday": "vs. yesterday",
        "stats_week_avg":     "7 day avg",
        "stats_overview":     "💰 *MARKET OVERVIEW*",
        "stats_mktcap":       "Total Mkt Cap",
        "stats_volume":       "24h Volume",
        "stats_insight":      "🔬 *AUTO INSIGHT*",
        "stats_score_label":  "Based on: sentiment + trend + volume + dominance",
        "alert_usage":        "Usage: `/alert BTC 70000`",
        "alert_invalid":      "❌ Invalid price.",
        "alert_loading":      "⏳ Searching *{coin}*...",
        "alert_not_found":    "❌ *{coin}* not found.",
        "alert_set":          "✅ Alert set: *{name}* {arrow} {price}\n_(Current price: {current})_\n_Notification will appear in the Predictions topic._",
        "alert_rise":         "📈 rises to",
        "alert_fall":         "📉 falls to",
        "myalerts_none":      "No active alerts. Use `/alert` to set one.",
        "myalerts_title":     "*Your alerts*\n",
        "myalerts_footer":    "\nUse `/removealert <number>` to delete.",
        "removealert_none":   "No alerts to delete.",
        "removealert_usage":  "Usage: `/removealert 1`",
        "removealert_done":   "🗑 Alert deleted: *{name}* @ {price}",
        "removealert_bad":    "❌ Invalid number. Use /myalerts.",
        "alert_triggered":    "🔔 *Price alert triggered!*\n\n*{name}* ({symbol}) has {verb} {price}\nYour target was: {target}",
        "alert_rose":         "risen to",
        "alert_fell":         "fallen to",
        "lang_prompt":        "🌐 *Selectează limba / Select language:*",
        "lang_set":           "✅ Language set: *English* 🇬🇧",
        "fng_extreme_fear":   "💡 Extreme fear → historic accumulation zone",
        "fng_fear":           "💡 Fear in market → possible buying opportunity",
        "fng_neutral":        "💡 Market is neutral → wait for direction confirmation",
        "fng_greed":          "⚠️ Greed increasing → be cautious, don't chase FOMO",
        "fng_extreme_greed":  "🚨 Extreme euphoria → high risk of correction",
    },
}

def gl(uid: int) -> str:
    return user_lang.get(uid, "ro")

def t(uid: int, key: str, **kw) -> str:
    lang = gl(uid)
    val  = TEXTS.get(lang, TEXTS["ro"]).get(key) or TEXTS["ro"].get(key, key)
    return val.format(**kw) if kw else val

# ─── PERSISTENT ALERTS ─────────────────────────────────────────────────────────
ALERTS_FILE   = os.path.join("/data" if os.path.isdir("/data") else ".", "alerts.json")
JSONBIN_KEY   = os.environ.get("JSONBIN_KEY", "")
OWNER_ID      = int(os.environ.get("OWNER_ID", "0"))
JSONBIN_BIN   = os.environ.get("JSONBIN_BIN", "")
JSONBIN_BASE  = "https://api.jsonbin.io/v3/b"

def _jsonbin_headers() -> dict:
    return {"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"}

def load_alerts() -> dict[int, list[dict]]:
    if JSONBIN_KEY and JSONBIN_BIN:
        try:
            r = requests.get(f"{JSONBIN_BASE}/{JSONBIN_BIN}/latest",
                             headers=_jsonbin_headers(), timeout=10)
            if r.status_code == 200:
                raw = r.json().get("record", {})
                logger.info("Alerte încărcate din JSONBin.")
                return {int(k): v for k, v in raw.items()}
            logger.warning(f"load_alerts JSONBin HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"load_alerts JSONBin error: {e}")
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, "r") as f:
                raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
        except Exception as e:
            logger.error(f"load_alerts local error: {e}")
    return {}

def save_alerts() -> None:
    if JSONBIN_KEY and JSONBIN_BIN:
        try:
            r = requests.put(f"{JSONBIN_BASE}/{JSONBIN_BIN}",
                             headers=_jsonbin_headers(),
                             json={str(k): v for k, v in user_alerts.items()},
                             timeout=10)
            if r.status_code == 200:
                return
            logger.warning(f"save_alerts JSONBin HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"save_alerts JSONBin error: {e}")
    try:
        with open(ALERTS_FILE, "w") as f:
            json.dump(user_alerts, f, indent=2)
    except Exception as e:
        logger.error(f"save_alerts local error: {e}")


user_alerts: dict[int, list[dict]] = load_alerts()

# ─── CACHE (evită rate limiting CoinGecko) ─────────────────────────────────────
_cache: dict[str, tuple[any, float]] = {}
CACHE_TTL = 120

def cache_get(key: str):
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None

def cache_set(key: str, data):
    _cache[key] = (data, time.time())

# ─── TOPIC ROUTING ─────────────────────────────────────────────────────────────

def topic_redirect(uid: int) -> str:
    return t(uid, "topic_redirect")

def is_in_correct_topic(update: Update) -> bool:
    if update.effective_chat.type == "private":
        return True
    if not GROUP_CHAT_ID or not TOPIC_COMENZI:
        return True
    thread_id = getattr(update.message, "message_thread_id", None) or 0
    return thread_id == TOPIC_COMENZI

async def post_to_topic(bot, topic_id: int, text: str, keyboard=None):
    if not GROUP_CHAT_ID or not topic_id:
        logger.warning(f"post_to_topic: GROUP_CHAT_ID sau topic_id neconfigurat (topic={topic_id})")
        return
    try:
        await bot.send_message(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=topic_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"post_to_topic error (topic={topic_id}): {e}")

# ─── MONEDE CRYPTOBUBBLES ──────────────────────────────────────────────────────
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

# ─── MAP SLUG COINGECKO ────────────────────────────────────────────────────────

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
    "ASTR": "astar", "KAS": "kaspa", "IMX": "immutable-x",
    "MNT": "mantle", "STX": "stacks", "FLOW": "flow",
    "GALA": "gala", "OKB": "okb",
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

def resolve_slug(query: str) -> str | None:
    q    = query.strip()
    slug = COIN_SLUG_MAP.get(q.upper()) or COIN_SLUG_MAP.get(q.lower())
    if slug:
        return slug
    cache_key = f"search:{q.lower()}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{COINGECKO_BASE}/search", params={"query": q}, timeout=10)
        if r.status_code == 200:
            coins = r.json().get("coins", [])
            if coins:
                found = coins[0]["id"]
                cache_set(cache_key, found)
                return found
    except Exception as e:
        logger.error(f"resolve_slug search error: {e}")
    return None

# ─── DATE COINGECKO ────────────────────────────────────────────────────────────

def get_coin_data(slug: str) -> dict | None:
    for attempt in range(3):
        if attempt > 0:
            time.sleep(2)
        try:
            r = requests.get(
                f"{COINGECKO_BASE}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": slug,
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h,7d,30d,1y",
                },
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                if not data:
                    return None
                c = data[0]
                return {
                    "slug":       c["id"],
                    "symbol":     c["symbol"].upper(),
                    "name":       c["name"],
                    "rank":       c.get("market_cap_rank") or "N/A",
                    "price":      c.get("current_price") or 0,
                    "change_1h":  c.get("price_change_percentage_1h_in_currency") or 0,
                    "change_24h": c.get("price_change_percentage_24h_in_currency")
                                  or c.get("price_change_percentage_24h") or 0,
                    "change_7d":  c.get("price_change_percentage_7d_in_currency") or 0,
                    "change_30d": c.get("price_change_percentage_30d_in_currency") or 0,
                    "change_1y":  c.get("price_change_percentage_1y_in_currency") or 0,
                    "high_24h":   c.get("high_24h") or 0,
                    "low_24h":    c.get("low_24h") or 0,
                    "market_cap": c.get("market_cap") or 0,
                    "volume_24h": c.get("total_volume") or 0,
                }
            logger.warning(f"get_coin_data HTTP {r.status_code} pentru {slug} (attempt {attempt + 1})")
        except Exception as e:
            logger.error(f"get_coin_data error ({slug}): {e}")
    return None

def get_top_coins(limit: int = 10) -> list[dict]:
    cache_key = f"top:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    for attempt in range(3):
        if attempt > 0:
            time.sleep(2)
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
            logger.warning(f"get_top_coins HTTP {r.status_code} (attempt {attempt + 1})")
        except Exception as e:
            logger.error(f"get_top_coins error: {e}")
    return []

def get_trending_coins() -> list[dict]:
    try:
        r = requests.get(f"{COINGECKO_BASE}/search/trending", timeout=10)
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
        return coins
    except Exception as e:
        logger.error(f"get_trending_coins error: {e}")
    return []

def get_bubbles_data() -> list[dict]:
    """Fetch toate perioadele deodată, cachează sub o singură cheie."""
    cached = cache_get("bubbles_all")
    if cached is not None:
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
                    "change_24h": c.get("price_change_percentage_24h_in_currency")
                                  or c.get("price_change_percentage_24h") or 0,
                    "change_7d":  c.get("price_change_percentage_7d_in_currency") or 0,
                    "change_30d": c.get("price_change_percentage_30d_in_currency") or 0,
                    "change_1y":  c.get("price_change_percentage_1y_in_currency") or 0,
                    "market_cap": c.get("market_cap", 0),
                    "volume_24h": c.get("total_volume", 0),
                })
            cache_set("bubbles_all", result)
            return result
        logger.error(f"get_bubbles_data HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"get_bubbles_data error: {e}")
    return []

def get_crypto_news(limit: int = 5) -> list[dict]:
    if not CRYPTOPANIC_TOKEN:
        return []
    try:
        r = requests.get(
            "https://cryptopanic.com/api/v1/posts/",
            params={"auth_token": CRYPTOPANIC_TOKEN, "public": "true", "kind": "news"},
            timeout=10,
        )
        posts = r.json().get("results", [])
        return [{"title": p["title"], "url": p["url"]} for p in posts[:limit]]
    except Exception as e:
        logger.error(f"get_crypto_news error: {e}")
    return []


# ─── FORMAT BUBBLES ────────────────────────────────────────────────────────────

def format_bubbles(coins: list[dict], period: str, uid: int = 0) -> list[str]:
    period_key = {
        "1h": "change_1h", "24h": "change_24h",
        "7d": "change_7d", "30d": "change_30d", "1y": "change_1y",
    }.get(period, "change_24h")

    sorted_coins = sorted(coins, key=lambda c: c.get(period_key, 0), reverse=True)
    label        = t(uid, "period_labels").get(period, period)
    header       = t(uid, "bubbles_header", label=label, n=len(coins))
    cont         = t(uid, "bubbles_cont",   label=label)

    lines = []
    for c in sorted_coins:
        chg      = c.get(period_key, 0)
        chg_str  = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"
        rank     = c["rank"]
        rank_str = f"0{rank}" if isinstance(rank, int) and rank < 10 else str(rank)
        lines.append(f"{c['symbol']} #{rank_str}  {fmt_price(c['price'])}  {'🟢' if chg>=0 else '🔴'} {chg_str}\n")

    pages   = []
    current = header
    for line in lines:
        if len(current) + len(line) > 3800:
            pages.append(current)
            current = cont
        current += line
    if current.strip():
        pages.append(current)

    return pages

# ─── STATS DATA SOURCES ────────────────────────────────────────────────────────

def get_fear_greed() -> dict | None:
    cached = cache_get("fear_greed")
    if cached is not None:
        return cached
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=8", timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if not data:
                return None
            today     = data[0]
            yesterday = data[1] if len(data) > 1 else data[0]
            week_vals = [int(d["value"]) for d in data]
            result = {
                "value":     int(today["value"]),
                "label":     today["value_classification"],
                "yesterday": int(yesterday["value"]),
                "week_avg":  round(sum(week_vals) / len(week_vals), 1),
                "history":   week_vals,
            }
            cache_set("fear_greed", result)
            return result
    except Exception as e:
        logger.error(f"get_fear_greed error: {e}")
    return None

def get_global_market() -> dict | None:
    cached = cache_get("global_market")
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{COINGECKO_BASE}/global", timeout=10)
        if r.status_code != 200:
            return None
        d = r.json().get("data", {})
        result = {
            "total_market_cap":      d.get("total_market_cap", {}).get("usd", 0),
            "total_volume_24h":      d.get("total_volume", {}).get("usd", 0),
            "btc_dominance":         round(d.get("market_cap_percentage", {}).get("btc", 0), 2),
            "eth_dominance":         round(d.get("market_cap_percentage", {}).get("eth", 0), 2),
            "market_cap_change_24h": d.get("market_cap_change_percentage_24h_usd", 0),
        }
        cache_set("global_market", result)
        return result
    except Exception as e:
        logger.error(f"get_global_market error: {e}")
    return None

def get_btc_eth_prices() -> dict:
    cached = cache_get("btc_eth_prices")
    if cached is not None:
        return cached
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={"vs_currency": "usd", "ids": "bitcoin,ethereum",
                    "order": "market_cap_desc", "per_page": 2,
                    "page": 1, "sparkline": "false"},
            timeout=10,
        )
        if r.status_code == 200:
            result = {}
            for c in r.json():
                if c["id"] == "bitcoin":
                    result["btc_price"]  = c.get("current_price", 0)
                    result["btc_change"] = c.get("price_change_percentage_24h") or 0
                elif c["id"] == "ethereum":
                    result["eth_price"]  = c.get("current_price", 0)
                    result["eth_change"] = c.get("price_change_percentage_24h") or 0
            cache_set("btc_eth_prices", result)
            return result
    except Exception as e:
        logger.error(f"get_btc_eth_prices error: {e}")
    return {}

# ─── STATS ENGINE ──────────────────────────────────────────────────────────────

def fng_emoji(value: int) -> str:
    if value <= 25:  return "😱"
    if value <= 45:  return "😰"
    if value <= 55:  return "😐"
    if value <= 75:  return "😄"
    return "🤑"

def fng_bar(value: int) -> str:
    filled = value // 10
    return "█" * filled + "░" * (10 - filled)

def interpret_fng(value: int, uid: int = 0) -> str:
    if value <= 20:  return t(uid, "fng_extreme_fear")
    if value <= 40:  return t(uid, "fng_fear")
    if value <= 60:  return t(uid, "fng_neutral")
    if value <= 80:  return t(uid, "fng_greed")
    return t(uid, "fng_extreme_greed")

def calc_market_score(fg: dict, global_data: dict, prices: dict) -> tuple[int, str]:
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

def generate_insight(fg: dict, global_data: dict, prices: dict) -> str:
    fng_val  = fg.get("value", 50)
    btc_chg  = prices.get("btc_change", 0)
    cap_chg  = global_data.get("market_cap_change_24h", 0)
    btc_dom  = global_data.get("btc_dominance", 50)
    week_avg = fg.get("week_avg", 50)

    insights = []
    if fng_val <= 35 and btc_chg >= 0:
        insights.append("📊 Deși piața e în frică, BTC rezistă → posibilă acumulare instituțională")
    elif fng_val >= 70 and btc_chg < -1:
        insights.append("⚠️ Greed ridicat dar BTC scade → semnal de slăbiciune, fii atent")

    if fng_val > week_avg + 10:
        insights.append("📈 Sentimentul s-a îmbunătățit față de săptămâna trecută → momentum pozitiv")
    elif fng_val < week_avg - 10:
        insights.append("📉 Sentimentul s-a deteriorat față de media săptămânii → prudență")

    if cap_chg > 2:
        insights.append("💹 Market cap-ul total crește cu volum → trend bullish confirmat")
    elif cap_chg < -2:
        insights.append("📉 Scădere generalizată în piață → risc crescut pe termen scurt")

    if btc_dom > 58:
        insights.append("🔶 BTC dominance ridicat → altcoin-urile suferă, capital concentrat în BTC")
    elif btc_dom < 42:
        insights.append("🟣 BTC dominance scăzut → posibilă altseason în desfășurare")

    if fng_val <= 15:
        insights.append("🚨 Panică extremă istorică → zonele acestea au coincis cu fundul pieței în trecut")

    if not insights:
        insights.append("➡️ Piața este echilibrată momentan — niciun semnal extrem detectat")

    return "\n".join(f"  {i}" for i in insights[:3])

def format_stats(fg: dict, global_data: dict, prices: dict, uid: int = 0) -> str:
    from datetime import datetime, timezone, timedelta
    utc_now = datetime.now(timezone.utc)
    year    = utc_now.year
    march_last_sunday = max(
        datetime(year, 3, day, 1, tzinfo=timezone.utc)
        for day in range(25, 32)
        if datetime(year, 3, day).weekday() == 6
    )
    oct_last_sunday = max(
        datetime(year, 10, day, 1, tzinfo=timezone.utc)
        for day in range(25, 32)
        if datetime(year, 10, day).weekday() == 6
    )
    if march_last_sunday <= utc_now < oct_last_sunday:
        ro_offset = timedelta(hours=3)
        ro_label  = "EEST"
    else:
        ro_offset = timedelta(hours=2)
        ro_label  = "EET"
    now = (utc_now + ro_offset).strftime(f"%H:%M {ro_label} (%d.%m.%Y)")

    fng_val   = fg["value"]
    fng_trend = fng_val - fg["yesterday"]
    trend_arrow = (f"↑ +{fng_trend}" if fng_trend > 0 else
                   f"↓ {fng_trend}"  if fng_trend < 0 else "→ 0")
    bar = fng_bar(fng_val)

    score, score_label = calc_market_score(fg, global_data, prices)
    score_bar = "⭐" * score + "☆" * (10 - score)
    insight   = generate_insight(fg, global_data, prices)

    cap_chg   = global_data.get("market_cap_change_24h", 0)
    cap_arrow = "🟢 ▲" if cap_chg >= 0 else "🔴 ▼"
    btc_arrow = "🟢 ▲" if prices.get("btc_change", 0) >= 0 else "🔴 ▼"
    eth_arrow = "🟢 ▲" if prices.get("eth_change", 0) >= 0 else "🔴 ▼"

    lines = [
        f"📊 *Market Stats* — {now}",
        "━" * 20,
        "",
        t(uid, "stats_sentiment"),
        fng_emoji(fng_val) + f" Fear & Greed: *{fng_val}/100* — _{fg['label']}_",
        f"`[{bar}]`",
        f"• {t(uid, 'stats_vs_yesterday')}: `{trend_arrow}`",
        f"• {t(uid, 'stats_week_avg')}: `{fg['week_avg']}/100`",
        "• " + interpret_fng(fng_val, uid),
        "",
        t(uid, "stats_overview"),
        f"• BTC:  `{fmt_price(prices.get('btc_price', 0))}`  {btc_arrow} `{abs(prices.get('btc_change', 0)):.1f}%`",
        f"• ETH:  `{fmt_price(prices.get('eth_price', 0))}`  {eth_arrow} `{abs(prices.get('eth_change', 0)):.1f}%`",
        f"• {t(uid, 'stats_mktcap')}: `{fmt_large(global_data.get('total_market_cap', 0))}`  {cap_arrow} `{abs(cap_chg):.1f}%`",
        f"• {t(uid, 'stats_volume')}:     `{fmt_large(global_data.get('total_volume_24h', 0))}`",
        f"• BTC Dominance: `{global_data.get('btc_dominance', 0)}%`",
        f"• ETH Dominance: `{global_data.get('eth_dominance', 0)}%`",
        "",
        t(uid, "stats_insight"),
        insight,
        "",
        f"⚡ *MARKET SCORE: {score}/10 — {score_label}*",
        f"`{score_bar}`",
        f"_{t(uid, 'stats_score_label')}_",
    ]
    return "\n".join(lines)

# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id   = update.effective_chat.id
    user_id   = update.effective_user.id
    thread_id = getattr(update.message, "message_thread_id", None)
    lines = [
        f"🆔 *Chat ID:* `{chat_id}`",
        f"👤 *User ID:* `{user_id}`",
        f"🧵 *Topic Thread ID:* `{thread_id}`" if thread_id else "🧵 *Topic Thread ID:* N/A",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    keyboard = [
        [InlineKeyboardButton("📊 Top 10",      callback_data="top"),
         InlineKeyboardButton("🔥 Trending",    callback_data="trending")],
        [InlineKeyboardButton("🫧 Bubbles 24h", callback_data="bubbles:24h"),
         InlineKeyboardButton("📊 Stats",       callback_data="stats")],
        [InlineKeyboardButton("🌐 Limba/Lang",  callback_data="lang"),
         InlineKeyboardButton("❓ Help",         callback_data="help")],
    ]
    await update.message.reply_text(t(uid, "start_msg"), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    await update.message.reply_text(t(uid, "help_msg"), parse_mode="Markdown")

async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    keyboard = [[
        InlineKeyboardButton("🇷🇴 Română",  callback_data="setlang:ro"),
        InlineKeyboardButton("🇬🇧 English", callback_data="setlang:en"),
    ]]
    await update.message.reply_text(t(uid, "lang_prompt"), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    if not context.args:
        await update.message.reply_text(t(uid, "price_usage"), parse_mode="Markdown")
        return
    query = " ".join(context.args)
    msg   = await update.message.reply_text(t(uid, "price_loading"))
    slug  = resolve_slug(query)
    data  = get_coin_data(slug) if slug else None
    if not data:
        await msg.edit_text(t(uid, "price_not_found", coin=query.upper()), parse_mode="Markdown")
        return
    lbl_price = "Price" if gl(uid) == "en" else "Preț"
    lbl_7d    = "7 days" if gl(uid) == "en" else "7 zile"
    lbl_30d   = "30 days" if gl(uid) == "en" else "30 zile"
    lbl_vol   = "Vol 24h" if gl(uid) == "en" else "Volum 24h"
    text = (
        f"*{data['name']}* ({data['symbol']})  •  Rank #{data['rank']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 {lbl_price}:   {fmt_price(data['price'])}\n"
        f"📈 1h:       {fmt_change(data['change_1h'])}\n"
        f"📈 24h:      {fmt_change(data['change_24h'])}\n"
        f"📈 {lbl_7d}: {fmt_change(data['change_7d'])}\n"
        f"📈 {lbl_30d}:{fmt_change(data['change_30d'])}\n"
        f"─────────────────\n"
        f"📊 24h High: {fmt_price(data['high_24h'])}\n"
        f"📊 24h Low:  {fmt_price(data['low_24h'])}\n"
        f"🏦 Mkt Cap:  {fmt_large(data['market_cap'])}\n"
        f"💹 {lbl_vol}:{fmt_large(data['volume_24h'])}\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{slug}")]]
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_bubbles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    valid_periods = ["1h", "24h", "7d", "30d", "1y"]
    period = context.args[0].lower() if context.args else "24h"
    if period not in valid_periods:
        await update.message.reply_text(t(uid, "bubbles_usage"), parse_mode="Markdown")
        return
    msg   = await update.message.reply_text(t(uid, "bubbles_loading", period=period), parse_mode="Markdown")
    coins = get_bubbles_data()
    if not coins:
        await msg.edit_text(t(uid, "bubbles_no_data"))
        return
    pages    = format_bubbles(coins, period, uid)
    keyboard = [[
        InlineKeyboardButton("1h",  callback_data="bubbles:1h"),
        InlineKeyboardButton("24h", callback_data="bubbles:24h"),
        InlineKeyboardButton("7d",  callback_data="bubbles:7d"),
        InlineKeyboardButton("30d", callback_data="bubbles:30d"),
        InlineKeyboardButton("1y",  callback_data="bubbles:1y"),
    ]]
    await msg.edit_text(pages[0], parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    for page in pages[1:]:
        await update.message.reply_text(page, parse_mode="Markdown")

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    msg   = await update.message.reply_text(t(uid, "top_loading"))
    coins = get_top_coins(10)
    if not coins:
        await msg.edit_text(t(uid, "top_no_data"))
        return
    lines = [t(uid, "top_title")]
    for i, c in enumerate(coins, 1):
        chg   = c.get("change_24h") or 0
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(f"{i}. *{c['symbol']}* — {fmt_price(c['price'])}  {'🟢' if chg>=0 else '🔴'} {arrow}{abs(chg):.1f}%")
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    msg   = await update.message.reply_text(t(uid, "trending_loading"))
    coins = get_trending_coins()
    if not coins:
        await msg.edit_text(t(uid, "top_no_data"))
        return
    lines = [t(uid, "trending_title")]
    for item in coins[:7]:
        c    = item["item"]
        rank = c.get("market_cap_rank", "?")
        chg  = c.get("change_24h", 0)
        sign = "+" if chg >= 0 else ""
        lines.append(f"• {c['name']} ({c['symbol']})  Rank #{rank}  {'🟢' if chg>=0 else '🔴'} {sign}{chg:.1f}%")
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    msg = await update.message.reply_text(t(uid, "stats_loading"))
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
        await msg.edit_text(t(uid, "stats_no_data"))
        return
    text     = format_stats(fg, global_data, prices, uid)
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    if len(context.args) < 2:
        await update.message.reply_text(t(uid, "alert_usage"), parse_mode="Markdown")
        return
    query = context.args[0]
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text(t(uid, "alert_invalid"), parse_mode="Markdown")
        return
    msg  = await update.message.reply_text(t(uid, "alert_loading", coin=query.upper()), parse_mode="Markdown")
    slug = resolve_slug(query)
    data = get_coin_data(slug) if slug else None
    if not data:
        await msg.edit_text(t(uid, "alert_not_found", coin=query.upper()), parse_mode="Markdown")
        return
    current   = data["price"]
    direction = "above" if target > current else "below"
    if uid not in user_alerts:
        user_alerts[uid] = []
    user_alerts[uid].append({
        "slug": slug, "symbol": data["symbol"],
        "name": data["name"], "target": target, "direction": direction,
    })
    save_alerts()
    arrow = t(uid, "alert_rise") if direction == "above" else t(uid, "alert_fall")
    await msg.edit_text(
        t(uid, "alert_set", name=data["name"], arrow=arrow,
          price=fmt_price(target), current=fmt_price(current)),
        parse_mode="Markdown")

async def cmd_myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text(t(uid, "myalerts_none"), parse_mode="Markdown")
        return
    lines = [t(uid, "myalerts_title")]
    for i, a in enumerate(alerts, 1):
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(f"{i}. *{a['name']}* ({a['symbol']}) {arrow} {fmt_price(a['target'])}")
    lines.append(t(uid, "myalerts_footer"))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_removealert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text(t(uid, "removealert_none"))
        return
    if not context.args:
        await update.message.reply_text(t(uid, "removealert_usage"), parse_mode="Markdown")
        return
    try:
        removed = alerts.pop(int(context.args[0]) - 1)
        save_alerts()
        await update.message.reply_text(
            t(uid, "removealert_done", name=removed["name"], price=fmt_price(removed["target"])),
            parse_mode="Markdown")
    except (ValueError, IndexError):
        await update.message.reply_text(t(uid, "removealert_bad"))

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if OWNER_ID and uid != OWNER_ID:
        return
    if not is_in_correct_topic(update):
        await update.message.reply_text(topic_redirect(uid), parse_mode="Markdown")
        return

    msg = await update.message.reply_text("⏳ Se trimit anunțurile...", parse_mode="Markdown")

    jobs = [
        ("📈 Date & Analize", TOPIC_DATE,   auto_stats_job),
        ("📊 Piață",          TOPIC_PIATA,  auto_trending_job),
        ("📰 Știri",          TOPIC_STIRI,  auto_stiri_job),
    ]

    lines = ["*🧪 Test anunțuri automate:*\n"]
    for label, topic_id, job_fn in jobs:
        if not topic_id:
            lines.append(f"⚪ {label} — neconfigurat")
            continue
        try:
            await job_fn(context)
            lines.append(f"✅ {label} — trimis")
        except Exception as e:
            lines.append(f"❌ {label} — `{e}`")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

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
            chg  = c.get("change_24h", 0)
            sign = "+" if chg >= 0 else ""
            lines.append(f"• {c['name']} ({c['symbol']})  Rank #{rank}  {'🟢' if chg>=0 else '🔴'} {sign}{chg:.1f}%")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("bubbles:"):
        period = data.split(":", 1)[1]
        await query.edit_message_text(f"⏳ Se încarcă CryptoBubbles ({period})...", parse_mode="Markdown")
        coins = get_bubbles_data()
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        pages    = format_bubbles(coins, period)
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
            await query.edit_message_text("❌ Nu s-au putut obține datele. Încearcă în 1 minut.")
            return
        text     = format_stats(fg, global_data, prices)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "help":
        uid = query.from_user.id
        await query.edit_message_text(t(uid, "help_msg"), parse_mode="Markdown")

    elif data == "lang":
        uid      = query.from_user.id
        keyboard = [[
            InlineKeyboardButton("🇷🇴 Română",  callback_data="setlang:ro"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang:en"),
        ]]
        await query.edit_message_text(t(uid, "lang_prompt"), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("setlang:"):
        uid  = query.from_user.id
        lang = data.split(":", 1)[1]
        user_lang[uid] = lang
        await query.edit_message_text(t(uid, "lang_set"), parse_mode="Markdown")

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

# ─── AUTO JOBS ─────────────────────────────────────────────────────────────────

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
            if not hit:
                continue
            verb = t(uid, "alert_rose") if direction == "above" else t(uid, "alert_fell")
            text = t(uid, "alert_triggered",
                     name=alert["name"], symbol=alert["symbol"],
                     verb=verb, price=fmt_price(current), target=fmt_price(target))
            try:
                if TOPIC_PREDICTII and GROUP_CHAT_ID:
                    await post_to_topic(context.bot, TOPIC_PREDICTII, text)
                else:
                    await context.bot.send_message(
                        chat_id=uid, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Alert send failed: {e}")
            to_remove.append(i)
        for i in reversed(to_remove):
            alerts.pop(i)
        if to_remove:
            save_alerts()

async def auto_stats_job(context: ContextTypes.DEFAULT_TYPE):
    """Trimite stats automat în TOPIC_DATE la 00:00 și 12:00."""
    if not TOPIC_DATE:
        return
    try:
        fg          = get_fear_greed()
        time.sleep(0.5)
        global_data = get_global_market()
        time.sleep(0.5)
        prices      = get_btc_eth_prices()
        if not fg or not global_data or not prices:
            logger.error("auto_stats_job: nu s-au putut obtine datele")
            return
        text     = format_stats(fg, global_data, prices)
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="stats")]]
        await post_to_topic(context.bot, TOPIC_DATE, text, keyboard)
        logger.info("auto_stats_job: trimis cu succes")
    except Exception as e:
        logger.error(f"auto_stats_job error: {e}")

async def auto_trending_job(context: ContextTypes.DEFAULT_TYPE):
    """Trimite trending automat în TOPIC_PIATA la 00:05 și 12:05."""
    if not TOPIC_PIATA:
        return
    try:
        coins = get_trending_coins()
        if not coins:
            logger.error("auto_trending_job: nu s-au putut obtine datele")
            return
        lines = ["*🔥 Trending pe CoinGecko*\n"]
        for item in coins[:7]:
            c    = item["item"]
            rank = c.get("market_cap_rank", "?")
            chg  = c.get("change_24h", 0)
            sign = "+" if chg >= 0 else ""
            lines.append(f"• {c['name']} ({c['symbol']})  Rank #{rank}  {'🟢' if chg>=0 else '🔴'} {sign}{chg:.1f}%")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
        await post_to_topic(context.bot, TOPIC_PIATA, "\n".join(lines), keyboard)
        logger.info("auto_trending_job: trimis cu succes")
    except Exception as e:
        logger.error(f"auto_trending_job error: {e}")

async def auto_stiri_job(context: ContextTypes.DEFAULT_TYPE):
    """Trimite știri automat în TOPIC_STIRI la 6h (dacă CRYPTOPANIC_TOKEN setat)."""
    if not TOPIC_STIRI:
        return
    news = get_crypto_news(5)
    if not news:
        logger.info("auto_stiri_job: CRYPTOPANIC_TOKEN neconfigurat sau nicio știre")
        return
    now   = datetime.datetime.now(TZ_RO).strftime("%d.%m.%Y %H:%M")
    lines = [f"*📰 Știri Crypto — {now}*\n"]
    for n in news:
        lines.append(f"• [{n['title']}]({n['url']})")
    await post_to_topic(context.bot, TOPIC_STIRI, "\n".join(lines))

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("chatid",      cmd_chatid))
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("price",       cmd_price))
    app.add_handler(CommandHandler("bubbles",     cmd_bubbles))
    app.add_handler(CommandHandler("top",         cmd_top))
    app.add_handler(CommandHandler("trending",    cmd_trending))
    app.add_handler(CommandHandler("stats",       cmd_stats))

    app.add_handler(CommandHandler("lang",        cmd_lang))
    app.add_handler(CommandHandler("test",        cmd_test))
    app.add_handler(CommandHandler("alert",       cmd_alert))
    app.add_handler(CommandHandler("myalerts",    cmd_myalerts))
    app.add_handler(CommandHandler("removealert", cmd_removealert))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(check_alerts,      interval=CHECK_ALERTS_INTERVAL, first=10)
    app.job_queue.run_repeating(auto_stiri_job,    interval=6 * 3600,              first=60)
    app.job_queue.run_daily(auto_stats_job,    time=datetime.time(12, 0,  tzinfo=TZ_RO))
    app.job_queue.run_daily(auto_stats_job,    time=datetime.time(0,  0,  tzinfo=TZ_RO))
    app.job_queue.run_daily(auto_trending_job, time=datetime.time(12, 5,  tzinfo=TZ_RO))
    app.job_queue.run_daily(auto_trending_job, time=datetime.time(0,  5,  tzinfo=TZ_RO))

    print("🤖 CryptoBot rulează cu suport Forum Topics.")
    print(f"  GROUP_CHAT_ID  : {GROUP_CHAT_ID   or 'neconfigurat'}")
    print(f"  TOPIC_COMENZI  : {TOPIC_COMENZI   or 'neconfigurat'}")
    print(f"  TOPIC_PIATA    : {TOPIC_PIATA      or 'neconfigurat'}")
    print(f"  TOPIC_STIRI    : {TOPIC_STIRI      or 'neconfigurat'}")
    print(f"  TOPIC_DATE     : {TOPIC_DATE       or 'neconfigurat'}")
    print(f"  TOPIC_PREDICTII: {TOPIC_PREDICTII  or 'neconfigurat'}")
    print(f"  CRYPTOPANIC    : {'configurat' if CRYPTOPANIC_TOKEN else 'neconfigurat (stiri dezactivate)'}")
    print(f"  JSONBIN        : {'activ (' + JSONBIN_BIN + ')' if JSONBIN_BIN else 'neconfigurat (alerte nu persista)'}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
