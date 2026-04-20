"""
Crypto Market Updates Telegram Bot — powered by CoinMarketCap
===============================================================
Requirements:
    pip install python-telegram-bot requests

Setup:
    1. Creează bot via @BotFather pe Telegram → copiază BOT_TOKEN
    2. Obține API key gratuit de pe https://coinmarketcap.com/api/
    3. Completează BOT_TOKEN și CMC_API_KEY mai jos
    4. Rulează: python crypto_bot.py

Commands:
    /start       - Mesaj de bun venit
    /price       - Prețul unui coin (ex: /price bitcoin)
    /top         - Top 10 după market cap
    /trending    - Trending pe CoinGecko
    /analiza     - Analiză tehnică TradingView (ex: /analiza BTC)
    /alert       - Alertă de preț (ex: /alert bitcoin 60000)
    /myalerts    - Alertele tale active
    /removealert - Șterge o alertă
    /help        - Ajutor
"""

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
import os
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8592401957:AAECZt1ZakLomCwztRprQ0Vmz9O3vcIrVtw")
CMC_API_KEY = os.environ.get("CMC_API_KEY", "2d2b671d35d140a38b265193bf052464")
CMC_BASE    = "https://pro-api.coinmarketcap.com/v1"
CHECK_ALERTS_INTERVAL = 60             # secunde între verificări alerte

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

user_alerts: dict[int, list[dict]] = {}

CMC_HEADERS = {
    "Accepts": "application/json",
    "X-CMC_PRO_API_KEY": CMC_API_KEY,
}


# ─── HELPERS ───────────────────────────────────────────────────────────────────

def fmt_price(value: float) -> str:
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}"

def fmt_change(pct: float) -> str:
    if pct is None:
        return "N/A"
    arrow = "🟢 ▲" if pct >= 0 else "🔴 ▼"
    return f"{arrow} {abs(pct):.2f}%"

def search_coin(query: str) -> dict | None:
    """
    Caută coin după simbol (BTC) sau slug (bitcoin).
    Funcționează cu planul gratuit CMC.
    """
    query = query.strip()
    # Încearcă după simbol (ex: BTC, ETH) apoi după slug (ex: bitcoin)
    for param in [{"symbol": query.upper()}, {"slug": query.lower()}]:
        try:
            r = requests.get(
                f"{CMC_BASE}/cryptocurrency/quotes/latest",
                headers=CMC_HEADERS,
                params={**param, "convert": "USD"},
                timeout=10,
            )
            data = r.json()
            coins = data.get("data", {})
            if coins:
                c = list(coins.values())[0]
                return {"id": c["id"], "name": c["name"], "symbol": c["symbol"]}
        except Exception as e:
            logger.error(f"search_coin error ({param}): {e}")
    return None

def get_coin_data(coin_id: int) -> dict | None:
    try:
        r = requests.get(
            f"{CMC_BASE}/cryptocurrency/quotes/latest",
            headers=CMC_HEADERS,
            params={"id": coin_id, "convert": "USD"},
            timeout=10,
        )
        data = r.json()
        coins = data.get("data", {})
        if coins:
            return list(coins.values())[0]
    except Exception as e:
        logger.error(f"get_coin_data error: {e}")
    return None

def get_top_coins(limit: int = 10) -> list[dict]:
    try:
        r = requests.get(
            f"{CMC_BASE}/cryptocurrency/listings/latest",
            headers=CMC_HEADERS,
            params={"start": 1, "limit": limit, "convert": "USD", "sort": "market_cap"},
            timeout=10,
        )
        return r.json().get("data", [])
    except Exception as e:
        logger.error(f"get_top_coins error: {e}")
    return []

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

def get_trending_coins() -> list[dict]:
    """Trending de pe CoinGecko — fără API key necesar."""
    try:
        r = requests.get(f"{COINGECKO_BASE}/search/trending", timeout=10)
        if r.status_code == 200:
            return r.json().get("coins", [])
    except Exception as e:
        logger.error(f"get_trending_coins error: {e}")
    return []



# ─── TRADINGVIEW ANALYSIS ──────────────────────────────────────────────────────

# Map nume comune → simbol TradingView
COIN_SYMBOL_MAP = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "cardano": "ADA", "ripple": "XRP", "xrp": "XRP",
    "dogecoin": "DOGE", "polkadot": "DOT", "avalanche": "AVAX",
    "chainlink": "LINK", "litecoin": "LTC", "uniswap": "UNI",
    "stellar": "XLM", "tron": "TRX", "shiba": "SHIB",
    "bnb": "BNB", "binancecoin": "BNB", "matic": "MATIC",
    "polygon": "MATIC", "near": "NEAR", "atom": "ATOM",
    "cosmos": "ATOM", "fantom": "FTM", "algorand": "ALGO",
}

def get_tv_analysis(symbol: str) -> dict | None:
    """Obține analiza tehnică de la TradingView via tradingview-ta."""
    try:
        from tradingview_ta import TA_Handler, Interval
        handler = TA_Handler(
            symbol=f"{symbol}USDT",
            screener="crypto",
            exchange="BINANCE",
            interval=Interval.INTERVAL_1_WEEKLY,
        )
        analysis = handler.get_analysis()
        return analysis
    except Exception as e:
        logger.error(f"TradingView error: {e}")
    return None

def resolve_symbol(query: str) -> str:
    """Rezolvă numele unui coin la simbolul său (ex: bitcoin → BTC)."""
    q = query.strip().lower()
    # Dacă e deja un simbol scurt (ex: BTC, ETH)
    if len(q) <= 5:
        return q.upper()
    # Caută în mapare
    return COIN_SYMBOL_MAP.get(q, q.upper())

async def cmd_analiza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Folosire: `/analiza bitcoin` sau `/analiza BTC`",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args)
    symbol = resolve_symbol(query)
    await update.message.reply_text(f"⏳ Se analizează *{symbol}*...", parse_mode="Markdown")

    analysis = get_tv_analysis(symbol)
    if not analysis:
        await update.message.reply_text(
            f"❌ Nu s-a putut obține analiza pentru *{symbol}*\n"
            f"Încearcă cu simbolul exact, ex: `/analiza BTC`",
            parse_mode="Markdown"
        )
        return

    s = analysis.summary
    osc = analysis.oscillators
    ma  = analysis.moving_averages
    ind = analysis.indicators

    # Semnal general
    rec = s.get("RECOMMENDATION", "N/A")
    emoji = {"BUY": "🟢", "STRONG_BUY": "🟢🟢", "SELL": "🔴",
             "STRONG_SELL": "🔴🔴", "NEUTRAL": "🟡"}.get(rec, "⚪")

    # Indicatori cheie
    rsi    = ind.get("RSI", 0)
    macd   = ind.get("MACD.macd", 0)
    macd_s = ind.get("MACD.signal", 0)
    ema20  = ind.get("EMA20", 0)
    ema50  = ind.get("EMA50", 0)
    ema200 = ind.get("EMA200", 0)
    close  = ind.get("close", 0)

    # RSI interpretare
    if rsi >= 70:
        rsi_txt = "Supracumpărat ⚠️"
    elif rsi <= 30:
        rsi_txt = "Supravândut ⚠️"
    else:
        rsi_txt = "Normal ✅"

    # MACD interpretare
    macd_txt = "🟢 Bullish" if macd > macd_s else "🔴 Bearish"

    # Voturi
    buy_s  = s.get("BUY", 0)
    neu_s  = s.get("NEUTRAL", 0)
    sell_s = s.get("SELL", 0)

    buy_ma  = ma.get("BUY", 0)
    neu_ma  = ma.get("NEUTRAL", 0)
    sell_ma = ma.get("SELL", 0)

    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT"

    text = (
        f"📊 *Analiză Tehnică — {symbol}/USDT*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} *Semnal general: {rec.replace('_', ' ')}*\n"
        f"\n"
        f"*📈 Oscilatori* (Buy {buy_s} | Neu {neu_s} | Sell {sell_s})\n"
        f"• RSI (14): `{rsi:.1f}` — {rsi_txt}\n"
        f"• MACD: {macd_txt}\n"
        f"\n"
        f"*📉 Medii Mobile* (Buy {buy_ma} | Neu {neu_ma} | Sell {sell_ma})\n"
        f"• EMA 20:  `{fmt_price(ema20)}`\n"
        f"• EMA 50:  `{fmt_price(ema50)}`\n"
        f"• EMA 200: `{fmt_price(ema200)}`\n"
        f"• Preț:    `{fmt_price(close)}`\n"
        f"\n"
        f"[📈 Vezi graficul pe TradingView]({tv_link})"
    )

    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"analiza:{symbol}")]]
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )

# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Top 10", callback_data="top"),
         InlineKeyboardButton("🔥 Trending", callback_data="trending")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 *Bun venit la CryptoBot!*\n\n"
        "Date live din CoinMarketCap.\n\n"
        "Încearcă:\n"
        "• /price bitcoin\n"
        "• /top\n"
        "• /trending\n"
        "• /alert bitcoin 70000\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Comenzi disponibile*\n\n"
        "/price `<coin>` — Preț live și statistici\n"
        "  ex: `/price ethereum`\n\n"
        "/top — Top 10 monede după market cap\n\n"
        "/trending — Trending pe CoinGecko\n\n"
        "/analiza `<coin>` — Analiză tehnică TradingView\n"
        "  ex: `/analiza BTC`\n\n"
        "/alert `<coin> <preț>` — Alertă de preț\n"
        "  ex: `/alert bitcoin 70000`\n\n"
        "/myalerts — Alertele tale active\n\n"
        "/removealert `<număr>` — Șterge alerta #N\n\n"
        "/help — Acest mesaj\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Folosire: `/price bitcoin`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    await update.message.reply_text("⏳ Se încarcă datele...")
    coin = search_coin(query)
    if not coin:
        await update.message.reply_text("❌ Moneda nu a fost găsită.")
        return
    data = get_coin_data(coin["id"])
    if not data:
        await update.message.reply_text("❌ Nu s-au putut obține datele. Încearcă mai târziu.")
        return
    q = data["quote"]["USD"]
    text = (
        f"*{data['name']}* ({data['symbol']})  •  Rank #{data.get('cmc_rank','N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Preț:      {fmt_price(q['price'])}\n"
        f"📈 24h:       {fmt_change(q.get('percent_change_24h'))}\n"
        f"📈 7 zile:    {fmt_change(q.get('percent_change_7d'))}\n"
        f"📈 30 zile:   {fmt_change(q.get('percent_change_30d'))}\n"
        f"─────────────────\n"
        f"🏦 Mkt Cap:   ${q.get('market_cap',0):,.0f}\n"
        f"💹 Volum 24h: ${q.get('volume_24h',0):,.0f}\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{coin['id']}")]]
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
        chg = c["quote"]["USD"].get("percent_change_24h") or 0
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(
            f"{i}. *{c['symbol']}* — {fmt_price(c['quote']['USD']['price'])}  "
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

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Folosire: `/alert bitcoin 70000`", parse_mode="Markdown")
        return
    query = context.args[0]
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Preț invalid.", parse_mode="Markdown")
        return
    coin = search_coin(query)
    if not coin:
        await update.message.reply_text("❌ Moneda nu a fost găsită.")
        return
    data = get_coin_data(coin["id"])
    if not data:
        await update.message.reply_text("❌ Nu s-a putut obține prețul curent.")
        return
    current = data["quote"]["USD"]["price"]
    if target == current:
        await update.message.reply_text("❌ Prețul țintă este același cu cel curent.")
        return
    direction = "above" if target > current else "below"
    uid = update.effective_user.id
    if uid not in user_alerts:
        user_alerts[uid] = []
    user_alerts[uid].append({
        "coin_id": coin["id"], "symbol": coin["symbol"],
        "name": coin["name"], "target": target, "direction": direction,
    })
    arrow = "📈 crește până la" if direction == "above" else "📉 scade până la"
    await update.message.reply_text(
        f"✅ Alertă setată: *{coin['name']}* {arrow} {fmt_price(target)}\n"
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
        lines.append(f"{i}. {a['name']} ({a['symbol']}) {arrow} {fmt_price(a['target'])}")
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
            f"🗑 Alertă ștearsă: {removed['name']} @ {fmt_price(removed['target'])}")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Număr invalid. Folosește /myalerts pentru a vedea lista.")


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
            chg = c["quote"]["USD"].get("percent_change_24h") or 0
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(
                f"{i}. *{c['symbol']}* — {fmt_price(c['quote']['USD']['price'])}  "
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
            "/analiza `<coin>` — Analiză tehnică TradingView\n"
            "/alert `<coin> <preț>` — Alertă de preț\n"
            "/myalerts — Alertele tale\n"
            "/removealert `<număr>` — Șterge alertă\n"
        )
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data.startswith("analiza:"):
        symbol = data.split(":", 1)[1]
        analysis = get_tv_analysis(symbol)
        if not analysis:
            await query.edit_message_text(f"❌ Nu s-a putut obține analiza pentru *{symbol}*", parse_mode="Markdown")
            return
        s = analysis.summary
        osc = analysis.oscillators
        ma  = analysis.moving_averages
        ind = analysis.indicators
        rec = s.get("RECOMMENDATION", "N/A")
        emoji = {"BUY": "🟢", "STRONG_BUY": "🟢🟢", "SELL": "🔴", "STRONG_SELL": "🔴🔴", "NEUTRAL": "🟡"}.get(rec, "⚪")
        rsi    = ind.get("RSI", 0)
        macd   = ind.get("MACD.macd", 0)
        macd_s = ind.get("MACD.signal", 0)
        ema20  = ind.get("EMA20", 0)
        ema50  = ind.get("EMA50", 0)
        ema200 = ind.get("EMA200", 0)
        close  = ind.get("close", 0)
        rsi_txt = "Supracumpărat ⚠️" if rsi >= 70 else ("Supravândut ⚠️" if rsi <= 30 else "Normal ✅")
        macd_txt = "🟢 Bullish" if macd > macd_s else "🔴 Bearish"
        buy_s  = s.get("BUY", 0); neu_s = s.get("NEUTRAL", 0); sell_s = s.get("SELL", 0)
        buy_ma = ma.get("BUY", 0); neu_ma = ma.get("NEUTRAL", 0); sell_ma = ma.get("SELL", 0)
        tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT"
        text = (
            f"📊 *Analiză Tehnică — {symbol}/USDT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} *Semnal general: {rec.replace('_', ' ')}*\n\n"
            f"*📈 Oscilatori* (Buy {buy_s} | Neu {neu_s} | Sell {sell_s})\n"
            f"• RSI (14): `{rsi:.1f}` — {rsi_txt}\n"
            f"• MACD: {macd_txt}\n\n"
            f"*📉 Medii Mobile* (Buy {buy_ma} | Neu {neu_ma} | Sell {sell_ma})\n"
            f"• EMA 20:  `{fmt_price(ema20)}`\n"
            f"• EMA 50:  `{fmt_price(ema50)}`\n"
            f"• EMA 200: `{fmt_price(ema200)}`\n"
            f"• Preț:    `{fmt_price(close)}`\n\n"
            f"[📈 Vezi graficul pe TradingView]({tv_link})"
        )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"analiza:{symbol}")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard),
                                      disable_web_page_preview=True)

    elif data.startswith("price:"):
        coin_id = int(data.split(":", 1)[1])
        info = get_coin_data(coin_id)
        if not info:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        q = info["quote"]["USD"]
        text = (
            f"*{info['name']}* ({info['symbol']})  •  Rank #{info.get('cmc_rank','N/A')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Preț:      {fmt_price(q['price'])}\n"
            f"📈 24h:       {fmt_change(q.get('percent_change_24h'))}\n"
            f"📈 7 zile:    {fmt_change(q.get('percent_change_7d'))}\n"
            f"📈 30 zile:   {fmt_change(q.get('percent_change_30d'))}\n"
            f"─────────────────\n"
            f"🏦 Mkt Cap:   ${q.get('market_cap',0):,.0f}\n"
            f"💹 Volum 24h: ${q.get('volume_24h',0):,.0f}\n"
        )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{coin_id}")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))


# ─── BACKGROUND JOB: CHECK ALERTS ─────────────────────────────────────────────

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    if not user_alerts:
        return
    for uid, alerts in list(user_alerts.items()):
        to_remove = []
        for i, alert in enumerate(alerts):
            data = get_coin_data(alert["coin_id"])
            if not data:
                continue
            current   = data["quote"]["USD"]["price"]
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
                            f"*{alert['name']}* ({alert['symbol']}) a {verb} {fmt_price(current)}\n"
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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("trending", cmd_trending))
    app.add_handler(CommandHandler("analiza", cmd_analiza))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("myalerts", cmd_myalerts))
    app.add_handler(CommandHandler("removealert", cmd_removealert))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(check_alerts, interval=CHECK_ALERTS_INTERVAL, first=10)

    print("🤖 CryptoBot (CoinMarketCap) rulează... Apasă Ctrl+C pentru a opri.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
