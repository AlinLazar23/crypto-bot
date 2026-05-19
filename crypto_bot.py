"""
Crypto Market Updates Telegram Bot — powered by CoinMarketCap
===============================================================
Requirements:
    pip install python-telegram-bot[job-queue] requests pytz

Setup:
    1. Creează bot via @BotFather → copiază BOT_TOKEN
    2. Obține API key gratuit de pe https://coinmarketcap.com/api/
    3. Setează variabilele de mediu (Railway / .env):
       BOT_TOKEN, CMC_API_KEY, GROUP_CHAT_ID,
       TOPIC_COMENZI, TOPIC_PIATA, TOPIC_STIRI,
       TOPIC_DATE, TOPIC_PREDICTII, TOPIC_INFO
    4. (Opțional) CRYPTOPANIC_TOKEN pentru știri automate
       → Înregistrare gratuită la https://cryptopanic.com/developers/api/

Cum obții Thread ID-urile topicurilor:
    1. Adaugă botul în grup ca Admin (permisiuni: Post/Delete messages)
    2. Scrie /chatid în fiecare topic
    3. Botul răspunde cu Chat ID și Topic Thread ID
    4. Setează valorile în Railway env vars

Roluri topicuri:
    Comenzi bot       ← singura zonă unde funcționează comenzile user
    Piață             ← prețuri live automate la 4h
    Știri             ← feed știri crypto la 6h
    Date & Analize    ← raport zilnic 08:00 RO
    Predicții         ← alerte de preț automate
    Info              ← comenzile /info post manual
    General           ← chat liber, bot ignoră

Commands:
    /start            - Bun venit
    /help             - Comenzi disponibile
    /chatid           - Chat ID + Thread ID (pentru config topicuri)
    /price <coin>     - Preț live și statistici
    /top              - Top 10 după market cap
    /trending         - Cele mai câștigătoare 24h
    /alert <coin> <preț>  - Setează alertă de preț
    /myalerts         - Alertele tale active
    /removealert <N>  - Șterge alerta #N
"""

import logging
import datetime
import requests
import pytz
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "")
CMC_API_KEY       = os.environ.get("CMC_API_KEY", "")
CMC_BASE          = "https://pro-api.coinmarketcap.com/v1"
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "")

# Grup și topicuri — setează în Railway env vars după ce rulezi /chatid în fiecare topic
GROUP_CHAT_ID   = int(os.environ.get("GROUP_CHAT_ID",    "0"))
TOPIC_COMENZI   = int(os.environ.get("TOPIC_COMENZI",   "0"))  # Comenzi bot
TOPIC_PIATA     = int(os.environ.get("TOPIC_PIATA",     "0"))  # Piață
TOPIC_STIRI     = int(os.environ.get("TOPIC_STIRI",     "0"))  # Știri
TOPIC_DATE      = int(os.environ.get("TOPIC_DATE",      "0"))  # Date & Analize
TOPIC_PREDICTII = int(os.environ.get("TOPIC_PREDICTII", "0"))  # Predicții

CHECK_ALERTS_INTERVAL = 60
INTERVAL_PIATA        = 4 * 3600  # 4 ore
INTERVAL_STIRI        = 6 * 3600  # 6 ore
TZ_RO                 = pytz.timezone("Europe/Bucharest")

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


# ─── DATA HELPERS ──────────────────────────────────────────────────────────────

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
    query = query.strip()
    for param in [{"symbol": query.upper()}, {"slug": query.lower()}]:
        try:
            r = requests.get(
                f"{CMC_BASE}/cryptocurrency/quotes/latest",
                headers=CMC_HEADERS,
                params={**param, "convert": "USD"},
                timeout=10,
            )
            data  = r.json()
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
        coins = r.json().get("data", {})
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

def get_trending_coins(limit: int = 7) -> list[dict]:
    try:
        r = requests.get(
            f"{CMC_BASE}/cryptocurrency/listings/latest",
            headers=CMC_HEADERS,
            params={
                "start": 1, "limit": 100, "convert": "USD",
                "sort": "percent_change_24h", "sort_dir": "desc",
            },
            timeout=10,
        )
        return r.json().get("data", [])[:limit]
    except Exception as e:
        logger.error(f"get_trending_coins error: {e}")
    return []

def get_crypto_news(limit: int = 5) -> list[dict]:
    """Știri via CryptoPanic. Necesită CRYPTOPANIC_TOKEN (gratuit la cryptopanic.com)."""
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

def get_fear_greed() -> dict | None:
    """Fear & Greed index via alternative.me — gratuit, fără autentificare."""
    try:
        r    = requests.get("https://api.alternative.me/fng/", timeout=10)
        item = r.json().get("data", [{}])[0]
        return {"value": int(item.get("value", 0)), "label": item.get("value_classification", "N/A")}
    except Exception as e:
        logger.error(f"get_fear_greed error: {e}")
    return None


# ─── TOPIC ROUTING ─────────────────────────────────────────────────────────────

def is_in_correct_topic(update: Update) -> bool:
    """Returnează True dacă mesajul e din privat sau din topicul Comenzi bot."""
    if update.effective_chat.type == "private":
        return True
    if not GROUP_CHAT_ID or not TOPIC_COMENZI:
        return True  # grup neconfigurat → permite oriunde
    thread_id = getattr(update.message, "message_thread_id", None) or 0
    return thread_id == TOPIC_COMENZI

async def post_to_topic(bot, topic_id: int, text: str, keyboard=None):
    """Trimite mesaj într-un topic specific din grup."""
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

TOPIC_REDIRECT_MSG = "⚠️ Comenzile se trimit în topicul *Comenzi bot*."


# ─── COMMAND HANDLERS ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
        return
    keyboard = [
        [InlineKeyboardButton("📊 Top 10",    callback_data="top"),
         InlineKeyboardButton("🔥 Trending",  callback_data="trending")],
        [InlineKeyboardButton("❓ Help",       callback_data="help")],
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
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
        return
    await update.message.reply_text(
        "📖 *Comenzi disponibile*\n\n"
        "/price `<coin>` — Preț live și statistici\n"
        "  ex: `/price ethereum`\n\n"
        "/top — Top 10 monede după market cap\n\n"
        "/trending — Cele mai câștigătoare azi\n\n"
        "/alert `<coin> <preț>` — Alertă de preț\n"
        "  ex: `/alert bitcoin 70000`\n\n"
        "/myalerts — Alertele tale active\n\n"
        "/removealert `<număr>` — Șterge alerta #N\n\n"
        "/chatid — ID-uri pentru configurarea topicurilor\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "*Topicuri active în grup:*\n"
        "📊 *Piață* — prețuri automate la 4h\n"
        "📰 *Știri* — știri crypto la 6h\n"
        "📈 *Date & Analize* — raport zilnic 08:00\n"
        "🔔 *Predicții* — alerte de preț\n",
        parse_mode="Markdown",
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Afișează Chat ID și Thread ID — util pentru configurarea topicurilor în Railway."""
    chat_id   = update.effective_chat.id
    user_id   = update.effective_user.id
    thread_id = getattr(update.message, "message_thread_id", None)
    lines = [
        f"🆔 *Chat ID:* `{chat_id}`",
        f"👤 *User ID:* `{user_id}`",
        f"🧵 *Topic Thread ID:* `{thread_id}`" if thread_id else "🧵 *Topic Thread ID:* N/A",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
        return
    if not context.args:
        await update.message.reply_text("Folosire: `/price bitcoin`", parse_mode="Markdown")
        return
    query = " ".join(context.args)
    msg   = await update.message.reply_text("⏳ Se încarcă datele...")
    coin  = search_coin(query)
    if not coin:
        await msg.edit_text("❌ Moneda nu a fost găsită.")
        return
    data = get_coin_data(coin["id"])
    if not data:
        await msg.edit_text("❌ Nu s-au putut obține datele. Încearcă mai târziu.")
        return
    q    = data["quote"]["USD"]
    text = (
        f"*{data['name']}* ({data['symbol']})  •  Rank #{data.get('cmc_rank', 'N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Preț:      {fmt_price(q['price'])}\n"
        f"📈 24h:       {fmt_change(q.get('percent_change_24h'))}\n"
        f"📈 7 zile:    {fmt_change(q.get('percent_change_7d'))}\n"
        f"📈 30 zile:   {fmt_change(q.get('percent_change_30d'))}\n"
        f"─────────────────\n"
        f"🏦 Mkt Cap:   ${q.get('market_cap', 0):,.0f}\n"
        f"💹 Volum 24h: ${q.get('volume_24h', 0):,.0f}\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{coin['id']}")]]
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
        return
    msg   = await update.message.reply_text("⏳ Se încarcă top 10...")
    coins = get_top_coins(10)
    if not coins:
        await msg.edit_text("❌ Nu s-au putut obține datele.")
        return
    lines = ["*🏆 Top 10 după Market Cap*\n"]
    for i, c in enumerate(coins, 1):
        chg   = c["quote"]["USD"].get("percent_change_24h") or 0
        arrow = "▲" if chg >= 0 else "▼"
        lines.append(
            f"{i}. *{c['symbol']}* — {fmt_price(c['quote']['USD']['price'])}  "
            f"{'🟢' if chg >= 0 else '🔴'} {arrow}{abs(chg):.1f}%"
        )
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
        return
    msg   = await update.message.reply_text("⏳ Se încarcă trending...")
    coins = get_trending_coins(7)
    if not coins:
        await msg.edit_text("❌ Nu s-au putut obține datele.")
        return
    lines = ["*🔥 Cele mai câștigătoare azi*\n"]
    for c in coins:
        chg = c["quote"]["USD"].get("percent_change_24h") or 0
        lines.append(f"• *{c['name']}* ({c['symbol']})  🟢 ▲{chg:.1f}%")
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Folosire: `/alert bitcoin 70000`", parse_mode="Markdown")
        return
    try:
        target = float(context.args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Preț invalid.", parse_mode="Markdown")
        return
    coin = search_coin(context.args[0])
    if not coin:
        await update.message.reply_text("❌ Moneda nu a fost găsită.")
        return
    data = get_coin_data(coin["id"])
    if not data:
        await update.message.reply_text("❌ Nu s-a putut obține prețul curent.")
        return
    current   = data["quote"]["USD"]["price"]
    direction = "above" if target > current else "below"
    uid       = update.effective_user.id
    if uid not in user_alerts:
        user_alerts[uid] = []
    user_alerts[uid].append({
        "coin_id":   coin["id"],
        "symbol":    coin["symbol"],
        "name":      coin["name"],
        "target":    target,
        "direction": direction,
    })
    arrow = "📈 crește până la" if direction == "above" else "📉 scade până la"
    await update.message.reply_text(
        f"✅ Alertă setată: *{coin['name']}* {arrow} {fmt_price(target)}\n"
        f"_(Preț curent: {fmt_price(current)})_\n"
        f"_Notificarea va apărea în topicul Predicții._",
        parse_mode="Markdown",
    )

async def cmd_myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
        return
    uid    = update.effective_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await update.message.reply_text(
            "Nu ai alerte active. Folosește `/alert` pentru a seta una.",
            parse_mode="Markdown",
        )
        return
    lines = ["*Alertele tale active*\n"]
    for i, a in enumerate(alerts, 1):
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(f"{i}. {a['name']} ({a['symbol']}) {arrow} {fmt_price(a['target'])}")
    lines.append("\nFolosește `/removealert <număr>` pentru a șterge.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_removealert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_in_correct_topic(update):
        await update.message.reply_text(TOPIC_REDIRECT_MSG, parse_mode="Markdown")
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
        removed = alerts.pop(int(context.args[0]) - 1)
        await update.message.reply_text(
            f"🗑 Alertă ștearsă: {removed['name']} @ {fmt_price(removed['target'])}")
    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ Număr invalid. Folosește /myalerts pentru a vedea lista.")


# ─── INLINE CALLBACKS ──────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data in ("top", "piata_top"):
        coins = get_top_coins(10)
        if not coins:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        lines = ["*🏆 Top 10 după Market Cap*\n"]
        for i, c in enumerate(coins, 1):
            chg   = c["quote"]["USD"].get("percent_change_24h") or 0
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(
                f"{i}. *{c['symbol']}* — {fmt_price(c['quote']['USD']['price'])}  "
                f"{'🟢' if chg >= 0 else '🔴'} {arrow}{abs(chg):.1f}%"
            )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="top")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "trending":
        coins = get_trending_coins(7)
        lines = ["*🔥 Cele mai câștigătoare azi*\n"]
        for c in coins:
            chg = c["quote"]["USD"].get("percent_change_24h") or 0
            lines.append(f"• *{c['name']}* ({c['symbol']})  🟢 ▲{chg:.1f}%")
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="trending")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "help":
        await query.edit_message_text(
            "📖 *Comenzi disponibile*\n\n"
            "/price `<coin>` — Preț live\n"
            "/top — Top 10 monede\n"
            "/trending — Cele mai câștigătoare azi\n"
            "/alert `<coin> <preț>` — Alertă de preț\n"
            "/myalerts — Alertele tale\n"
            "/removealert `<număr>` — Șterge alertă\n",
            parse_mode="Markdown",
        )

    elif data.startswith("price:"):
        coin_id = int(data.split(":", 1)[1])
        info    = get_coin_data(coin_id)
        if not info:
            await query.edit_message_text("❌ Nu s-au putut obține datele.")
            return
        q    = info["quote"]["USD"]
        text = (
            f"*{info['name']}* ({info['symbol']})  •  Rank #{info.get('cmc_rank', 'N/A')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Preț:      {fmt_price(q['price'])}\n"
            f"📈 24h:       {fmt_change(q.get('percent_change_24h'))}\n"
            f"📈 7 zile:    {fmt_change(q.get('percent_change_7d'))}\n"
            f"📈 30 zile:   {fmt_change(q.get('percent_change_30d'))}\n"
            f"─────────────────\n"
            f"🏦 Mkt Cap:   ${q.get('market_cap', 0):,.0f}\n"
            f"💹 Volum 24h: ${q.get('volume_24h', 0):,.0f}\n"
        )
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"price:{coin_id}")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "piata_refresh":
        await query.answer("Se actualizează...")
        await _build_piata_message(context.bot, edit_query=query)

    elif data == "analize_refresh":
        await query.answer("Se actualizează...")
        await _build_analize_message(context.bot, edit_query=query)


# ─── AUTO JOBS ─────────────────────────────────────────────────────────────────

async def _build_piata_message(bot, edit_query=None):
    """Construiește și trimite (sau editează) mesajul pentru topicul Piață."""
    coins = get_top_coins(20)
    if not coins:
        return

    spotlight = {c["symbol"]: c for c in coins if c["symbol"] in ("BTC", "ETH", "SOL", "BNB", "XRP")}
    gainers   = sorted(coins, key=lambda c: c["quote"]["USD"].get("percent_change_24h") or 0, reverse=True)[:5]
    losers    = sorted(coins, key=lambda c: c["quote"]["USD"].get("percent_change_24h") or 0)[:3]

    now   = datetime.datetime.now(TZ_RO).strftime("%d.%m.%Y %H:%M")
    lines = [f"*📊 Update Piață — {now}*\n"]

    lines.append("*💎 Spotlight:*")
    for sym in ["BTC", "ETH", "SOL", "BNB", "XRP"]:
        c = spotlight.get(sym)
        if c:
            q   = c["quote"]["USD"]
            chg = q.get("percent_change_24h") or 0
            lines.append(
                f"• *{sym}*: {fmt_price(q['price'])}  "
                f"{'🟢' if chg >= 0 else '🔴'} {'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%"
            )

    lines.append("\n*🚀 Top 5 Gainers 24h:*")
    for c in gainers:
        chg = c["quote"]["USD"].get("percent_change_24h") or 0
        lines.append(f"• *{c['symbol']}* {fmt_price(c['quote']['USD']['price'])} 🟢 ▲{chg:.1f}%")

    lines.append("\n*📉 Top 3 Losers 24h:*")
    for c in losers:
        chg = c["quote"]["USD"].get("percent_change_24h") or 0
        lines.append(f"• *{c['symbol']}* {fmt_price(c['quote']['USD']['price'])} 🔴 ▼{abs(chg):.1f}%")

    text     = "\n".join(lines)
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="piata_refresh")]]

    if edit_query:
        await edit_query.edit_message_text(text, parse_mode="Markdown",
                                           reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await post_to_topic(bot, TOPIC_PIATA, text, keyboard)


async def _build_analize_message(bot, edit_query=None):
    """Construiește și trimite (sau editează) mesajul pentru topicul Date & Analize."""
    coins = get_top_coins(10)
    fg    = get_fear_greed()
    now   = datetime.datetime.now(TZ_RO).strftime("%d.%m.%Y %H:%M")
    lines = [f"*📈 Raport Piață — {now}*\n"]

    if fg:
        val   = fg["value"]
        emoji = "😨" if val < 25 else "😟" if val < 45 else "😐" if val < 55 else "😊" if val < 75 else "🤑"
        lines.append(f"*Fear & Greed:* {emoji} {val}/100 — _{fg['label']}_\n")

    if coins:
        lines.append("*🏆 Top 10 Market Cap:*")
        for i, c in enumerate(coins, 1):
            q   = c["quote"]["USD"]
            chg = q.get("percent_change_24h") or 0
            lines.append(
                f"{i}. *{c['symbol']}* {fmt_price(q['price'])} "
                f"{'🟢' if chg >= 0 else '🔴'} {'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%"
            )

    text     = "\n".join(lines)
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="analize_refresh")]]

    if edit_query:
        await edit_query.edit_message_text(text, parse_mode="Markdown",
                                           reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await post_to_topic(bot, TOPIC_DATE, text, keyboard)


async def job_piata(context: ContextTypes.DEFAULT_TYPE):
    """La fiecare 4h: prețuri + gainers/losers în topicul Piață."""
    if not TOPIC_PIATA:
        return
    await _build_piata_message(context.bot)


async def job_stiri(context: ContextTypes.DEFAULT_TYPE):
    """La fiecare 6h: ultimele știri crypto în topicul Știri."""
    if not TOPIC_STIRI:
        return
    news = get_crypto_news(5)
    if not news:
        logger.info("job_stiri: CRYPTOPANIC_TOKEN neconfigurat sau nicio știre disponibilă.")
        return
    now   = datetime.datetime.now(TZ_RO).strftime("%d.%m.%Y %H:%M")
    lines = [f"*📰 Știri Crypto — {now}*\n"]
    for n in news:
        lines.append(f"• [{n['title']}]({n['url']})")
    await post_to_topic(context.bot, TOPIC_STIRI, "\n".join(lines))


async def job_analize(context: ContextTypes.DEFAULT_TYPE):
    """Zilnic la 08:00 RO: raport complet în topicul Date & Analize."""
    if not TOPIC_DATE:
        return
    await _build_analize_message(context.bot)


async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    """La fiecare 60s: verifică alerte și postează în topicul Predicții (sau DM fallback)."""
    if not user_alerts:
        return
    for uid, alerts in list(user_alerts.items()):
        to_remove = []
        for i, alert in enumerate(alerts):
            data = get_coin_data(alert["coin_id"])
            if not data:
                continue
            current   = data["quote"]["USD"]["price"]
            direction = alert.get("direction", "above")
            hit       = (current >= alert["target"]) if direction == "above" else (current <= alert["target"])
            if not hit:
                continue
            verb = "crescut la" if direction == "above" else "scăzut la"
            text = (
                f"🔔 *Alertă de preț activată!*\n\n"
                f"*{alert['name']}* ({alert['symbol']}) a {verb} {fmt_price(current)}\n"
                f"Ținta era: {fmt_price(alert['target'])}"
            )
            try:
                if TOPIC_PREDICTII and GROUP_CHAT_ID:
                    await post_to_topic(context.bot, TOPIC_PREDICTII, text)
                else:
                    await context.bot.send_message(
                        chat_id=uid, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"check_alerts send error: {e}")
            to_remove.append(i)
        for i in reversed(to_remove):
            alerts.pop(i)


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("chatid",       cmd_chatid))
    app.add_handler(CommandHandler("price",        cmd_price))
    app.add_handler(CommandHandler("top",          cmd_top))
    app.add_handler(CommandHandler("trending",     cmd_trending))
    app.add_handler(CommandHandler("alert",        cmd_alert))
    app.add_handler(CommandHandler("myalerts",     cmd_myalerts))
    app.add_handler(CommandHandler("removealert",  cmd_removealert))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(check_alerts, interval=CHECK_ALERTS_INTERVAL, first=10)
    app.job_queue.run_repeating(job_piata,    interval=INTERVAL_PIATA,        first=30)
    app.job_queue.run_repeating(job_stiri,    interval=INTERVAL_STIRI,        first=60)
    app.job_queue.run_daily(
        job_analize,
        time=datetime.time(hour=8, minute=0, tzinfo=TZ_RO),
    )

    print("CryptoBot rulează cu suport Forum Topics.")
    print(f"  GROUP_CHAT_ID  : {GROUP_CHAT_ID  or 'neconfigurat'}")
    print(f"  TOPIC_COMENZI  : {TOPIC_COMENZI  or 'neconfigurat'}")
    print(f"  TOPIC_PIATA    : {TOPIC_PIATA    or 'neconfigurat'}")
    print(f"  TOPIC_STIRI    : {TOPIC_STIRI    or 'neconfigurat'}")
    print(f"  TOPIC_DATE     : {TOPIC_DATE     or 'neconfigurat'}")
    print(f"  TOPIC_PREDICTII: {TOPIC_PREDICTII or 'neconfigurat'}")
    print(f"  CRYPTOPANIC    : {'configurat' if CRYPTOPANIC_TOKEN else 'neconfigurat (stiri dezactivate)'}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
