"""
Crypto Market Updates Telegram Bot
====================================
Surse: Binance API (preț/top) + CoinGecko (trending) + TradingView (analiză)
Fără API key necesar!

Requirements:
    pip install python-telegram-bot[job-queue] requests tradingview-ta

Setup:
    1. @BotFather → BOT_TOKEN
    2. Completează BOT_TOKEN mai jos
    3. python crypto_bot.py

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
BINANCE_BASE   = "https://api.binance.com/api/v3"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CHECK_ALERTS_INTERVAL = 60

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

user_alerts: dict[int, list[dict]] = {}

# ─── FORMATARE ─────────────────────────────────────────────────────────────────

def fmt_price(value: float) -> str:
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}"

def fmt_large(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"

def fmt_change(pct: float) -> str:
    if pct is None:
        return "N/A"
    arrow = "🟢 ▲" if pct >= 0 else "🔴 ▼"
    return f"{arrow} {abs(pct):.2f}%"

# ─── MAP NUME → SIMBOL ─────────────────────────────────────────────────────────

COIN_NAME_MAP = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "cardano": "ADA", "ripple": "XRP", "dogecoin": "DOGE",
    "polkadot": "DOT", "avalanche": "AVAX", "chainlink": "LINK",
    "litecoin": "LTC", "uniswap": "UNI", "stellar": "XLM",
    "tron": "TRX", "shiba": "SHIB", "bnb": "BNB",
    "binancecoin": "BNB", "matic": "MATIC", "polygon": "MATIC",
    "near": "NEAR", "atom": "ATOM", "cosmos": "ATOM",
    "fantom": "FTM", "algorand": "ALGO", "monero": "XMR",
    "pepe": "PEPE", "sui": "SUI", "aptos": "APT",
}

def resolve_symbol(query: str) -> str:
    q = query.strip().lower()
    return COIN_NAME_MAP.get(q, q.upper())

# ─── DATE BINANCE ──────────────────────────────────────────────────────────────

def get_coin_data(symbol: str) -> dict | None:
    """Preț + statistici 24h de pe Binance."""
    try:
        r = requests.get(
            f"{BINANCE_BASE}/ticker/24hr",
            params={"symbol": f"{symbol}USDT"},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "symbol":    symbol,
            "name":      symbol,
            "price":     float(d["lastPrice"]),
            "change_24h": float(d["priceChangePercent"]),
            "high_24h":  float(d["highPrice"]),
            "low_24h":   float(d["lowPrice"]),
            "volume_24h": float(d["quoteVolume"]),
        }
    except Exception as e:
        logger.error(f"get_coin_data error: {e}")
    return None

def search_coin(query: str) -> dict | None:
    """Caută coin pe Binance după simbol sau nume."""
    symbol = resolve_symbol(query)
    data = get_coin_data(symbol)
    if data:
        return {"symbol": symbol, "name": symbol}
    return None

def get_top_coins(limit: int = 10) -> list[dict]:
    """Top coins după market cap de pe CoinGecko (gratuit)."""
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
            result = []
            for c in r.json():
                result.append({
                    "symbol":    c["symbol"].upper(),
                    "name":      c["name"],
                    "price":     c["current_price"],
                    "change_24h": c.get("price_change_percentage_24h") or 0,
                })
            return result
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
        [InlineKeyboardButton("📊 Top 10", callback_data="top"),
         InlineKeyboardButton("🔥 Trending", callback_data="trending")],
        [InlineKeyboardButton("📈 Analiză BTC", callback_data="analiza:BTC"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 *Bun venit la CryptoBot!*\n\n"
        "Date live din Binance + CoinGecko + TradingView.\n\n"
        "Încearcă:\n"
        "• /price BTC\n"
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
        "/price `<coin>` — Preț live și statistici\n"
        "  ex: `/price BTC` sau `/price bitcoin`\n\n"
        "/top — Top 10 monede după market cap\n\n"
        "/trending — Trending pe CoinGecko\n\n"
        "/analiza `<coin>` — Analiză tehnică TradingView\n"
        "  ex: `/analiza BTC`\n\n"
        "/alert `<coin> <preț>` — Alertă de preț\n"
        "  ex: `/alert BTC 70000`\n\n"
        "/myalerts — Alertele tale active\n\n"
        "/removealert `<număr>` — Șterge alerta #N\n\n"
        "/help — Acest mesaj\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Folosire: `/price BTC`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    await update.message.reply_text("⏳ Se încarcă datele...")

    symbol = resolve_symbol(query)
    data = get_coin_data(symbol)
    if not data:
        await update.message.reply_text(
            f"❌ *{symbol}* nu a fost găsit pe Binance.\n"
            f"Încearcă simbolul exact: `/price BTC`, `/price ETH`, `/price SOL`",
            parse_mode="Markdown"
        )
        return

    chg = data["change_24h"]
    text = (
        f"*{data['symbol']}*/USDT\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Preț:      {fmt_price(data['price'])}\n"
        f"📈 24h:       {fmt_change(chg)}\n"
        f"─────────────────\n"
        f"📊 24h High:  {fmt_price(data['high_24h'])}\n"
        f"📊 24h Low:   {fmt_price(data['low_24h'])}\n"
        f"💹 Volum 24h: {fmt_large(data['volume_24h'])}\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{symbol}")]]
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
    symbol = resolve_symbol(query)
    await update.message.reply_text(f"⏳ Se analizează *{symbol}*...", parse_mode="Markdown")

    analysis = get_tv_analysis(symbol)
    if not analysis:
        await update.message.reply_text(
            f"❌ Nu s-a putut obține analiza pentru *{symbol}*.\n"
            f"Încearcă cu simbolul exact, ex: `/analiza BTC`",
            parse_mode="Markdown"
        )
        return

    s   = analysis.summary
    ind = analysis.indicators
    ma  = analysis.moving_averages

    rec = s.get("RECOMMENDATION", "N/A")
    emoji_map = {
        "STRONG_BUY": "🟢🟢", "BUY": "🟢",
        "NEUTRAL": "🟡",
        "SELL": "🔴", "STRONG_SELL": "🔴🔴"
    }
    rec_emoji = emoji_map.get(rec, "⚪")

    rsi    = ind.get("RSI", 0)
    macd   = ind.get("MACD.macd", 0)
    macd_s = ind.get("MACD.signal", 0)
    ema20  = ind.get("EMA20", 0)
    ema50  = ind.get("EMA50", 0)
    ema200 = ind.get("EMA200", 0)
    close  = ind.get("close", 0)

    rsi_txt = "Supracumpărat ⚠️" if rsi >= 70 else ("Supravândut ⚠️" if rsi <= 30 else "Normal ✅")
    macd_txt = "🟢 Bullish" if macd > macd_s else "🔴 Bearish"

    buy_s  = s.get("BUY", 0)
    neu_s  = s.get("NEUTRAL", 0)
    sell_s = s.get("SELL", 0)
    buy_ma = ma.get("BUY", 0)
    neu_ma = ma.get("NEUTRAL", 0)
    sell_ma = ma.get("SELL", 0)

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

    symbol = resolve_symbol(query)
    data = get_coin_data(symbol)
    if not data:
        await update.message.reply_text(
            f"❌ *{symbol}* nu a fost găsit.", parse_mode="Markdown")
        return

    current = data["price"]
    if target == current:
        await update.message.reply_text("❌ Prețul țintă este același cu cel curent.")
        return

    direction = "above" if target > current else "below"
    uid = update.effective_user.id
    if uid not in user_alerts:
        user_alerts[uid] = []
    user_alerts[uid].append({
        "symbol": symbol, "name": symbol,
        "target": target, "direction": direction,
    })

    arrow = "📈 crește până la" if direction == "above" else "📉 scade până la"
    await update.message.reply_text(
        f"✅ Alertă setată: *{symbol}* {arrow} {fmt_price(target)}\n"
        f"_(Preț curent: {fmt_price(current)})_",
        parse_mode="Markdown"
    )

async def cmd_myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text("Nu ai alerte active. Folosește /alert pentru a seta una.")
        return
    lines = ["*Alertele tale*\n"]
    for i, a in enumerate(alerts, 1):
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(f"{i}. *{a['name']}* {arrow} {fmt_price(a['target'])}")
    lines.append("\nFolosește `/removealert <număr>` pentru a șterge.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_removealert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text("Nu ai alerte de șters.")
        return
    if not context.args:
        await update.message.reply_text("Folosire: `/removealert 1`", parse_mode="Markdown")
        return
    try:
        n = int(context.args[0])
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
    data = query.data

    if data == "top":
        coins = get_top_coins(10)
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
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
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "trending":
        coins = get_trending_coins()
        lines = ["*🔥 Trending pe CoinGecko*\n"]
        for item in coins[:7]:
            c = item["item"]
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
        symbol = data.split(":", 1)[1]
        info = get_coin_data(symbol)
        if not info:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        chg = info["change_24h"]
        text = (
            f"*{info['symbol']}*/USDT\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Preț:      {fmt_price(info['price'])}\n"
            f"📈 24h:       {fmt_change(chg)}\n"
            f"─────────────────\n"
            f"📊 24h High:  {fmt_price(info['high_24h'])}\n"
            f"📊 24h Low:   {fmt_price(info['low_24h'])}\n"
            f"💹 Volum 24h: {fmt_large(info['volume_24h'])}\n"
        )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{symbol}")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("analiza:"):
        symbol = data.split(":", 1)[1]
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
        rec_emoji = emoji_map.get(rec, "⚪")
        rsi    = ind.get("RSI", 0)
        macd   = ind.get("MACD.macd", 0)
        macd_s = ind.get("MACD.signal", 0)
        ema20  = ind.get("EMA20", 0)
        ema50  = ind.get("EMA50", 0)
        ema200 = ind.get("EMA200", 0)
        close  = ind.get("close", 0)
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
            data = get_coin_data(alert["symbol"])
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
                            f"*{alert['name']}* a {verb} {fmt_price(current)}\n"
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
