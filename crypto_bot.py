"""
Crypto Market Updates Telegram Bot
====================================
Surse: CoinGecko (preț/top/trending) + TradingView (analiză)
Fără API key necesar! Funcționează în orice regiune.

Requirements:
    pip install python-telegram-bot[job-queue] requests tradingview-ta

Commands:
    /start       - Bun venit
    /price BTC   - Preț live
    /top         - Top 10 după market cap
    /trending    - Trending CoinGecko
    /analiza BTC - Analiză tehnică TradingView
    /alert BTC 70000 - Alertă de preț
    /myalerts    - Alertele tale
    /removealert 1 - Șterge alertă
    /help        - Ajutor
"""

import os
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
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "8592401957:AAECZt1ZakLomCwztRprQ0Vmz9O3vcIrVtw")
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CHECK_ALERTS_INTERVAL = 60

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

user_alerts: dict[int, list[dict]] = {}

# ─── FORMATARE ─────────────────────────────────────────────────────────────────

def fmt_price(value: float) -> str:
    if value is None:
        return "N/A"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}"

def fmt_large(value: float) -> str:
    if not value:
        return "N/A"
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
# Mapare simbol/nume → slug CoinGecko (folosit în API)

COIN_SLUG_MAP = {
    # simbol → slug
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
    # nume → slug
    "bitcoin": "bitcoin", "ethereum": "ethereum", "solana": "solana",
    "ripple": "ripple", "cardano": "cardano", "dogecoin": "dogecoin",
    "polkadot": "polkadot", "avalanche": "avalanche-2",
    "chainlink": "chainlink", "litecoin": "litecoin",
    "stellar": "stellar", "tron": "tron", "shiba": "shiba-inu",
    "polygon": "matic-network", "near": "near", "cosmos": "cosmos",
    "fantom": "fantom", "algorand": "algorand", "monero": "monero",
    "bnb": "binancecoin", "binancecoin": "binancecoin",
    "arbitrum": "arbitrum", "optimism": "optimism",
    "injective": "injective-protocol",
}

def resolve_slug(query: str) -> str:
    """Rezolvă simbol sau nume la slug-ul CoinGecko."""
    q = query.strip()
    # Caută exact în map (simbol uppercase sau nume lowercase)
    slug = COIN_SLUG_MAP.get(q.upper()) or COIN_SLUG_MAP.get(q.lower())
    if slug:
        return slug
    # Altfel presupunem că e deja un slug (ex: "bitcoin", "ethereum")
    return q.lower()

# ─── DATE COINGECKO ────────────────────────────────────────────────────────────

def get_coin_data(slug: str) -> dict | None:
    """Preț + statistici complete de pe CoinGecko după slug."""
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/{slug}",
            params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            },
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
            "change_24h": m.get("price_change_percentage_24h") or 0,
            "change_7d":  m.get("price_change_percentage_7d") or 0,
            "high_24h":   m["high_24h"].get("usd", 0),
            "low_24h":    m["low_24h"].get("usd", 0),
            "market_cap": m["market_cap"].get("usd", 0),
            "volume_24h": m["total_volume"].get("usd", 0),
        }
    except Exception as e:
        logger.error(f"get_coin_data error ({slug}): {e}")
    return None

def get_top_coins(limit: int = 10) -> list[dict]:
    """Top coins după market cap."""
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": limit,
                "page": 1,
                "sparkline": "false",
            },
            timeout=10,
        )
        if r.status_code == 200:
            return [
                {
                    "symbol":    c["symbol"].upper(),
                    "name":      c["name"],
                    "slug":      c["id"],
                    "price":     c["current_price"],
                    "change_24h": c.get("price_change_percentage_24h") or 0,
                }
                for c in r.json()
            ]
    except Exception as e:
        logger.error(f"get_top_coins error: {e}")
    return []

def get_trending_coins() -> list[dict]:
    """Trending de pe CoinGecko."""
    try:
        r = requests.get(f"{COINGECKO_BASE}/search/trending", timeout=10)
        if r.status_code == 200:
            return r.json().get("coins", [])
    except Exception as e:
        logger.error(f"get_trending_coins error: {e}")
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

# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Top 10",      callback_data="top"),
         InlineKeyboardButton("🔥 Trending",    callback_data="trending")],
        [InlineKeyboardButton("📈 Analiză BTC", callback_data="analiza:BTC"),
         InlineKeyboardButton("❓ Help",         callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 *Bun venit la CryptoBot!*\n\n"
        "Date live din CoinGecko + TradingView.\n\n"
        "Încearcă:\n"
        "• /price BTC\n"
        "• /price bitcoin\n"
        "• /top\n"
        "• /trending\n"
        "• /analiza ETH\n"
        "• /alert BTC 70000\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Comenzi disponibile*\n\n"
        "/price `<coin>` — Preț live\n"
        "  ex: `/price BTC` sau `/price bitcoin`\n\n"
        "/top — Top 10 după market cap\n\n"
        "/trending — Trending pe CoinGecko\n\n"
        "/analiza `<coin>` — Analiză TradingView\n"
        "  ex: `/analiza BTC`\n\n"
        "/alert `<coin> <preț>` — Alertă de preț\n"
        "  ex: `/alert BTC 70000`\n\n"
        "/myalerts — Alertele tale active\n\n"
        "/removealert `<număr>` — Șterge alerta\n\n"
        "/help — Acest mesaj\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            parse_mode="Markdown"
        )
        return

    text = (
        f"*{data['name']}* ({data['symbol']})  •  Rank #{data['rank']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Preț:      {fmt_price(data['price'])}\n"
        f"📈 24h:       {fmt_change(data['change_24h'])}\n"
        f"📈 7 zile:    {fmt_change(data['change_7d'])}\n"
        f"─────────────────\n"
        f"📊 24h High:  {fmt_price(data['high_24h'])}\n"
        f"📊 24h Low:   {fmt_price(data['low_24h'])}\n"
        f"🏦 Mkt Cap:   {fmt_large(data['market_cap'])}\n"
        f"💹 Volum 24h: {fmt_large(data['volume_24h'])}\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{slug}")]]
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Se încarcă top 10...")
    coins = get_top_coins(10)
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obține datele.")
        return
    lines = ["*🏆 Top 10 după Market Cap*\n"]
    for i, c in enumerate(coins, 1):
        chg = c.get("change_24h") or 0
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(
            f"{i}. *{c['symbol']}* — {fmt_price(c['price'])}  "
            f"{'🟢' if chg>=0 else '🔴'} {arrow}{abs(chg):.1f}%"
        )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Se încarcă trending...")
    coins = get_trending_coins()
    if not coins:
        await update.message.reply_text("❌ Nu s-au putut obține datele.")
        return
    lines = ["*🔥 Trending pe CoinGecko*\n"]
    for item in coins[:7]:
        c = item["item"]
        rank = c.get("market_cap_rank", "?")
        lines.append(f"• *{c['name']}* ({c['symbol']})  •  Rank #{rank}")
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_analiza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Folosire: `/analiza BTC`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    slug  = resolve_slug(query)
    # Obține simbolul corect pentru TradingView
    coin_info = get_coin_data(slug)
    symbol = coin_info["symbol"] if coin_info else query.upper()

    await update.message.reply_text(f"⏳ Se analizează *{symbol}*...", parse_mode="Markdown")

    analysis = get_tv_analysis(symbol)
    if not analysis:
        await update.message.reply_text(
            f"❌ Nu s-a putut obține analiza pentru *{symbol}*.",
            parse_mode="Markdown"
        )
        return

    s   = analysis.summary
    ind = analysis.indicators
    ma  = analysis.moving_averages
    rec = s.get("RECOMMENDATION", "N/A")
    emoji_map = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "NEUTRAL": "🟡",
                 "SELL": "🔴", "STRONG_SELL": "🔴🔴"}
    rec_emoji = emoji_map.get(rec, "⚪")

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
        disable_web_page_preview=True
    )

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Folosire: `/alert BTC 70000`", parse_mode="Markdown")
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
            f"❌ *{query.upper()}* nu a fost găsit.\n"
            f"Încearcă: `/alert BTC 70000` sau `/alert bitcoin 70000`",
            parse_mode="Markdown"
        )
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
        parse_mode="Markdown"
    )

async def cmd_myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text(
            "Nu ai alerte active. Folosește /alert pentru a seta una.")
        return
    lines = ["*Alertele tale*\n"]
    for i, a in enumerate(alerts, 1):
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(f"{i}. *{a['name']}* ({a['symbol']}) {arrow} {fmt_price(a['target'])}")
    lines.append("\nFolosește `/removealert <număr>` pentru a șterge.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_removealert(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            parse_mode="Markdown"
        )
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
                f"{'🟢' if chg>=0 else '🔴'} {arrow}{abs(chg):.1f}%"
            )
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

    elif data == "help":
        text = (
            "📖 *Comenzi disponibile*\n\n"
            "/price `<coin>` — Preț live\n"
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
            f"📈 24h:       {fmt_change(info['change_24h'])}\n"
            f"📈 7 zile:    {fmt_change(info['change_7d'])}\n"
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
    app.add_handler(CommandHandler("top",         cmd_top))
    app.add_handler(CommandHandler("trending",    cmd_trending))
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
