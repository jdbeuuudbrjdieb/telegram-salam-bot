# ═══════════════════════════════════════════════════════════════════════
#   🤖 ULTIMATE OS BOT — v4.0
#   پیکربندی: config.py → .env → os.getenv
#   فقط python-telegram-bot + کتابخانه استاندارد
# ═══════════════════════════════════════════════════════════════════════

import os
import sys
import json
import random
import hashlib
import base64
import logging
import re
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════════════════════
# ۱. بارگذاری پیکربندی از پروژه
# ═══════════════════════════════════════════════════════════════════════
def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\" "))
    except Exception:
        pass


_load_dotenv()

# تلاش برای ایمپورت از config.py پروژه
_project_cfg = {}
try:
    import config as _proj_config  # type: ignore
    _project_cfg = {
        k: getattr(_proj_config, k)
        for k in dir(_proj_config)
        if k.isupper() and not k.startswith("_")
    }
except ImportError:
    pass


def _get(name: str, default=None, cast=str):
    """اولویت: config.py → env → default."""
    if name in _project_cfg:
        val = _project_cfg[name]
    else:
        val = os.getenv(name, default)
    if val is None or val == "":
        return default
    if cast is int:
        try:
            return int(val)
        except (ValueError, TypeError):
            return default
    return val


logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ultimate-os")
START_TIME = time.time()

BOT_TOKEN = _get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN از هیچ منبعی خوانده نشد (config.py / .env / env)")
    sys.exit(1)

OWNER_ID = _get("OWNER_ID", 0, int) or 0
LOG_CHANNEL = _get("LOG_CHANNEL") or None

# کانال‌های اجباری — می‌تواند لیست یا رشته با کاما باشد
_raw_ch = _get("FORCE_CHANNELS", "")
if isinstance(_raw_ch, list):
    _ch_list = _raw_ch
elif isinstance(_raw_ch, str):
    _ch_list = [c.strip() for c in _raw_ch.split(",") if c.strip()]
else:
    _ch_list = []

FORCE_CHANNELS = []
for ch in _ch_list:
    name = str(ch).replace("@", "").replace("https://t.me/", "")
    FORCE_CHANNELS.append({
        "id": f"@{name}",
        "link": f"https://t.me/{name}",
        "name": name,
    })

DEFAULT_LANG = _get("LANGUAGE", "fa")
logger.info(f"🔧 config loaded: owner={OWNER_ID}, channels={len(FORCE_CHANNELS)}, log={'on' if LOG_CHANNEL else 'off'}")

# ═══════════════════════════════════════════════════════════════════════
# ۲. لایه ذخیره‌سازی
# ═══════════════════════════════════════════════════════════════════════
DATA_DIR = Path(_get("DATA_DIR", "data"))
DATA_DIR.mkdir(exist_ok=True)


class Store:
    def __init__(self, name: str):
        self.path = DATA_DIR / f"{name}.json"
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"load {self.path}: {e}")
            return {}

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
        except Exception as e:
            logger.error(f"save {self.path}: {e}")

    def get(self, *keys, default=None):
        cur = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def set(self, value, *keys):
        cur = self.data
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value
        self.save()


config_store    = Store("config")
warns_store     = Store("warns")
stats_store     = Store("stats")
blacklist_store = Store("blacklist")
notes_store     = Store("notes")
filters_store   = Store("filters")
feds_store      = Store("federations")
whitelist_store = Store("whitelist")
levels_store    = Store("levels")
captcha_store   = Store("captcha")
custom_cmd_store = Store("custom_cmds")
allowdomain_store = Store("allowdomains")
scheduled_store = Store("scheduled")
goodbye_store   = Store("goodbye")
rep_store       = Store("reputation")
msg_log_store   = Store("msg_log")

# کش‌ها
flood_db = {}
admin_cache = {}
cooldowns = {}
last_msg = {}
msg_cache = {}     # msg_id -> {chat_id, user_id, text, time} برای antidelete
raid_db = {}
daily_counts = {}  # (chat, user, date) -> count

# ═══════════════════════════════════════════════════════════════════════
# ۳. تنظیمات پیش‌فرض
# ═══════════════════════════════════════════════════════════════════════
DEFAULT_CONFIG = {
    # قفل‌ها
    "lock_link": True, "lock_forward": True, "lock_media": False,
    "lock_sticker": False, "lock_gif": False, "lock_file": False,
    "lock_voice": False, "lock_video_note": False, "lock_poll": False,
    "lock_contact": False, "lock_location": False, "lock_web_page": False,
    "lock_bot": False, "lock_inline": False, "lock_game": False,
    "lock_channel": True, "lock_duplicate": False, "lock_english": False,
    "lock_emoji": False, "lock_hashtag": False, "lock_mention": False,
    # ویژگی‌ها
    "force_channel": True, "welcome": True, "antiflood": True,
    "antiflood_limit": 5, "antiflood_window": 10, "antiflood_mute": 300,
    "antiraid": True, "antiraid_limit": 10, "antiraid_window": 60,
    "captcha": True, "captcha_timeout": 180,
    "warn_limit": 3, "warn_expiry": 86400,
    "night_mode": False, "night_start": 0, "night_end": 7,
    "slow_mode": 0, "silent": False, "language": DEFAULT_LANG,
    "antiedit": True, "antidelete": True,
    "antibot": False, "antidup": False, "antichain": True,
    "nsfw": True,
    # متن‌ها
    "welcome_text": (
        "👋 سلام {mention} عزیز\n"
        "به گروه خوش آمدید 🌹\n"
        "📅 {date}\n"
        "👥 اعضا: {members}"
    ),
    "goodbye_text": "👋 {mention} از گروه خارج شد.",
    "welcome_autodelete": 0,        # 0 = خاموش، >0 = ثانیه
    "welcome_mute_seconds": 0,      # 0 = خاموش
    "rules_text": (
        "📜 قوانین:\n"
        "1️⃣ به همه احترام بگذارید\n"
        "2️⃣ تبلیغات ممنوع است\n"
        "3️⃣ محتوای نامناسب ممنوع است\n"
        "4️⃣ از دستورات ادمین‌ها پیروی کنید"
    ),
    "daily_limit": 0,   # 0 = بی‌نهایت
    "ban_reason_required": False,
}

URL_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|@[a-zA-Z][a-zA-Z0-9_]{4,})",
    re.IGNORECASE,
)
DOMAIN_PATTERN = re.compile(r"https?://([^\s/]+)", re.IGNORECASE)
ENGLISH_PATTERN = re.compile(r"[a-zA-Z]{4,}")
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF]"
)
HASHTAG_PATTERN = re.compile(r"(^|\s)#\w+")
MENTION_PATTERN = re.compile(r"(^|\s)@\w+")
NSFW_WORDS = {
    "sex", "porn", "xxx", "nude", "naked", "boobs", "dick", "pussy",
    "سکسی", "پورن", "برهنه", "لخت", "فحش",
}


def get_config(chat_id: int) -> dict:
    key = str(chat_id)
    cfg = config_store.data.get(key)
    if cfg is None:
        cfg = DEFAULT_CONFIG.copy()
        config_store.data[key] = cfg
        config_store.save()
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(chat_id: int) -> None:
    config_store.save()


# ═══════════════════════════════════════════════════════════════════════
# ۴. توابع کمکی
# ═══════════════════════════════════════════════════════════════════════
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE,
                   user_id: int = None) -> bool:
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    target_id = user_id or (update.effective_user.id if update.effective_user else None)
    if not target_id:
        return False
    if target_id == OWNER_ID:
        return True

    key = (chat.id, target_id)
    now = time.time()
    cached = admin_cache.get(key)
    if cached and cached[1] > now:
        return cached[0]
    try:
        m = await context.bot.get_chat_member(chat.id, target_id)
        ok = m.status in ("administrator", "creator")
    except TelegramError:
        ok = False
    admin_cache[key] = (ok, now + 60)
    return ok


def _admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if not await is_admin(update, context):
            return
        return await func(update, context, *a, **kw)
    return wrapper


def _owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if update.effective_user.id != OWNER_ID:
            await update.effective_message.reply_text("⛔️ فقط برای مالک ربات.")
            return
        return await func(update, context, *a, **kw)
    return wrapper


def _cooldown(seconds: int = 3):
    def deco(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
            if not update.effective_user or not update.effective_chat:
                return await func(update, context, *a, **kw)
            key = (update.effective_chat.id, update.effective_user.id, func.__name__)
            if cooldowns.get(key, 0) > time.time():
                return
            cooldowns[key] = time.time() + seconds
            return await func(update, context, *a, **kw)
        return wrapper
    return deco


async def safe_delete(msg) -> bool:
    try:
        await msg.delete(); return True
    except TelegramError:
        return False


def parse_duration(text):
    if not text:
        return None
    m = re.match(r"^\s*(\d+)\s*(s|sec|ثانیه|m|min|دقیقه|h|hour|ساعت|d|day|روز|w|week|هفته)?\s*$",
                 text, re.IGNORECASE)
    if not m:
        return None
    n = int(m.group(1))
    u = (m.group(2) or "m").lower()
    if u in ("s", "sec", "ثانیه"): return n
    if u in ("m", "min", "دقیقه"): return n * 60
    if u in ("h", "hour", "ساعت"): return n * 3600
    if u in ("d", "day", "روز"): return n * 86400
    if u in ("w", "week", "هفته"): return n * 7 * 86400
    return n * 60


def humanize_duration(seconds):
    if seconds < 60:    return f"{seconds} ثانیه"
    if seconds < 3600:  return f"{seconds//60} دقیقه"
    if seconds < 86400: return f"{seconds//3600} ساعت"
    return f"{seconds//86400} روز"


def jalali_today() -> str:
    gy, gm, gd = datetime.now().year, datetime.now().month, datetime.now().day
    gdm = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy2, gm2, gd2 = gy - 1600, gm - 1, gd - 1
    gdn = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    for i in range(gm2):
        gdn += gdm[i]
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        gdn += 1
    gdn += gd2
    jdn = gdn - 79
    jnp = jdn // 12053
    jdn %= 12053
    jy = 979 + 33 * jnp + 4 * (jdn // 1461)
    jdn %= 1461
    if jdn >= 366:
        jy += (jdn - 366) // 365 + 1
        jdn = (jdn - 366) % 365
    jdm = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    jm = 1
    for i in range(12):
        if jdn < jdm[i]:
            jm = i + 1
            break
        jdn -= jdm[i]
    jd = jdn + 1
    return f"{jy}/{jm:02d}/{jd:02d}"


def welcome_vars(member, chat) -> dict:
    return {
        "name": member.first_name,
        "mention": member.mention_html(),
        "id": str(member.id),
        "username": f"@{member.username}" if member.username else "—",
        "chat": chat.title or "—",
        "members": "؟",  # پر می‌شود در جای فراخوانی
        "date": jalali_today(),
        "time": datetime.now().strftime("%H:%M"),
    }


async def log_action(context, chat_id, action, actor, target=None, reason=""):
    if not LOG_CHANNEL:
        return
    try:
        text = (
            f"📋 <b>لاگ</b>\n"
            f"👥 گروه: <code>{chat_id}</code>\n"
            f"⚡ {action}\n"
            f"👤 {actor.mention_html()}"
        )
        if target:
            text += f"\n🎯 {target.mention_html()} (<code>{target.id}</code>)"
        if reason:
            text += f"\n📝 {reason}"
        await context.bot.send_message(LOG_CHANNEL, text, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


async def _auto_delete(msg, seconds: int):
    if msg is None:
        return
    async def _del():
        await asyncio.sleep(seconds)
        await safe_delete(msg)
    asyncio.create_task(_del())


# ═══════════════════════════════════════════════════════════════════════
# ۵. کانال اجباری + کپچا
# ═══════════════════════════════════════════════════════════════════════
async def check_membership(user_id, context):
    missing = []
    for ch in FORCE_CHANNELS:
        try:
            m = await context.bot.get_chat_member(ch["id"], user_id)
            if m.status in ("left", "kicked"):
                missing.append(ch)
        except TelegramError:
            pass
    return missing


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cfg = get_config(chat.id)

    for member in update.message.new_chat_members:
        if member.is_bot:
            continue

        # ضد ربات
        if cfg["antibot"]:
            try:
                await context.bot.ban_chat_member(chat.id, member.id)
                continue
            except TelegramError:
                pass

        if not cfg["welcome"]:
            continue

        # ضد ریید
        if cfg["antiraid"]:
            key = (chat.id, member.id)
            now = time.time()
            raid_db.setdefault(key, []).append(now)
            raid_db[key] = [t for t in raid_db[key] if now - t < cfg["antiraid_window"]]
            total = sum(
                1 for (c, _), arr in raid_db.items()
                if c == chat.id and any(now - t < cfg["antiraid_window"] for t in arr)
            )
            if total > cfg["antiraid_limit"]:
                try:
                    await chat.set_permissions(ChatPermissions(can_send_messages=False))
                    await update.message.reply_text(
                        "🚨 <b>ضد ریید فعال شد!</b>\nادمین <code>/unlock</code> بزند.",
                        parse_mode=ParseMode.HTML)
                except TelegramError:
                    pass
                return

        needs_verify = cfg["captcha"] or (cfg["force_channel"] and FORCE_CHANNELS)

        # سکوت موقت
        if needs_verify or cfg["welcome_mute_seconds"] > 0:
            mute_dur = cfg["welcome_mute_seconds"] if cfg["welcome_mute_seconds"] > 0 else cfg["captcha_timeout"]
            try:
                await context.bot.restrict_chat_member(
                    chat.id, member.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=datetime.now() + timedelta(seconds=mute_dur) if mute_dur else None)
            except TelegramError:
                pass

        if needs_verify:
            captcha_store.set(
                {"chat_id": chat.id, "user_id": member.id,
                 "expires": time.time() + cfg["captcha_timeout"]},
                str(chat.id), str(member.id))
            context.job_queue.run_once(
                _kick_unverified, cfg["captcha_timeout"],
                data={"chat_id": chat.id, "user_id": member.id},
                name=f"cap_{chat.id}_{member.id}")

        await _send_welcome(update, member, cfg, needs_verify)


async def _send_welcome(update, member, cfg, needs_verify=False):
    chat = update.effective_chat
    keyboard = []
    if needs_verify:
        for ch in FORCE_CHANNELS:
            keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch["link"])])
        keyboard.append([InlineKeyboardButton("✅ تایید عضویت",
                                             callback_data=f"verify_{member.id}")])

    try:
        members_count = await chat.get_member_count()
    except TelegramError:
        members_count = "؟"

    v = welcome_vars(member, chat)
    v["members"] = str(members_count)
    text = cfg["welcome_text"]
    for k, val in v.items():
        text = text.replace(f"{{{k}}}", str(val))

    markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    try:
        sent = await update.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML)
        if cfg["welcome_autodelete"] > 0:
            await _auto_delete(sent, cfg["welcome_autodelete"])
    except TelegramError as e:
        logger.warning(f"welcome: {e}")


async def _kick_unverified(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    key = (str(data["chat_id"]), str(data["user_id"]))
    if captcha_store.get(*key):
        try:
            await context.bot.ban_chat_member(data["chat_id"], data["user_id"])
            await context.bot.unban_chat_member(data["chat_id"], data["user_id"])
        except TelegramError:
            pass
        captcha_store.set(None, *key)
        captcha_store.save()


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = int(q.data.split("_")[1])
    if q.from_user.id != user_id:
        await q.answer("❌ این دکمه برای شما نیست!", show_alert=True)
        return
    missing = await check_membership(user_id, context)
    if missing:
        names = "، ".join(c["name"] for c in missing)
        await q.answer(f"❌ هنوز عضو نیستید: {names}", show_alert=True)
        return
    try:
        await context.bot.restrict_chat_member(
            q.message.chat.id, user_id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
                can_send_polls=True, can_invite_users=True))
    except TelegramError:
        pass
    captcha_store.set(None, str(q.message.chat.id), str(user_id))
    captcha_store.save()
    try:
        await q.message.edit_text(f"✅ تایید شد! خوش آمدید {q.from_user.first_name}.")
    except TelegramError:
        pass


# ═══════════════════════════════════════════════════════════════════════
# ۶. خداحافظی
# ═══════════════════════════════════════════════════════════════════════
async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cfg = get_config(chat.id)
    left = update.message.left_chat_member
    if not left or left.is_bot:
        return
    v = welcome_vars(left, chat)
    text = cfg["goodbye_text"]
    for k, val in v.items():
        text = text.replace(f"{{{k}}}", str(val))
    try:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


# ═══════════════════════════════════════════════════════════════════════
# ۷. دستورات فارسی
# ═══════════════════════════════════════════════════════════════════════
BAN_WORDS    = {"بن", "ban"}
KICK_WORDS   = {"اخراج", "kick"}
MUTE_WORDS   = {"سکوت", "mute"}
FREE_WORDS   = {"آزاد", "unmute"}
WARN_WORDS   = {"اخطار", "warn"}
UNWARN_WORDS = {"حذف اخطار", "unwarn"}
PIN_WORDS    = {"پین", "pin"}
UNPIN_WORDS  = {"آنپین", "unpin"}
DEL_WORDS    = {"حذف", "delete", "del"}
PURGE_WORDS  = {"پاکسازی", "purge"}


async def persian_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await is_admin(update, context):
        return

    parts = msg.text.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    chat_id = update.effective_chat.id
    cfg = get_config(chat_id)

    if cmd in PURGE_WORDS:
        await _do_purge(update, context); return

    reply_needed = (BAN_WORDS | MUTE_WORDS | FREE_WORDS | WARN_WORDS |
                    UNWARN_WORDS | PIN_WORDS | UNPIN_WORDS | DEL_WORDS | KICK_WORDS)
    if cmd not in reply_needed:
        return
    if not msg.reply_to_message:
        await _auto_delete(await msg.reply_text("⚠️ روی پیام کاربر ریپلای کنید."), 5)
        return

    target = msg.reply_to_message.from_user
    if await is_admin(update, context, target.id):
        await _auto_delete(await msg.reply_text("⚠️ روی ادمین اجرا نمی‌شود."), 5)
        return

    reason = arg or "بدون دلیل"
    if cfg["ban_reason_required"] and cmd in (BAN_WORDS | KICK_WORDS) and not arg:
        await _auto_delete(await msg.reply_text(
            "⚠️ در این گروه دلیل اجباری است:\n`بن دلیل`", parse_mode=ParseMode.MARKDOWN), 6)
        return

    try:
        if cmd in BAN_WORDS:
            dur = parse_duration(arg) if arg else None
            until = datetime.now() + timedelta(seconds=dur) if dur else None
            await context.bot.ban_chat_member(chat_id, target.id, until_date=until)
            await log_action(context, chat_id, "بن", update.effective_user, target, reason)
            await _auto_delete(await msg.reply_text(
                f"⛔️ {target.first_name} " +
                (f"برای {humanize_duration(dur)} " if dur else "") + "بن شد."), 8)
        elif cmd in KICK_WORDS:
            await context.bot.ban_chat_member(chat_id, target.id)
            await context.bot.unban_chat_member(chat_id, target.id)
            await _auto_delete(await msg.reply_text(f"👢 {target.first_name} اخراج شد."), 8)
        elif cmd in MUTE_WORDS:
            dur = parse_duration(arg) if arg else None
            until = datetime.now() + timedelta(seconds=dur) if dur else None
            await context.bot.restrict_chat_member(
                chat_id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until)
            await log_action(context, chat_id, "سکوت", update.effective_user, target, reason)
            await _auto_delete(await msg.reply_text(
                f"🔇 {target.first_name} " +
                (f"برای {humanize_duration(dur)} " if dur else "") + "سکوت شد."), 8)
        elif cmd in FREE_WORDS:
            await context.bot.restrict_chat_member(
                chat_id, target.id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_media_messages=True,
                    can_send_other_messages=True, can_add_web_page_previews=True,
                    can_send_polls=True, can_invite_users=True))
            await _auto_delete(await msg.reply_text(f"🔊 {target.first_name} آزاد شد."), 8)
        elif cmd in WARN_WORDS:
            await _add_warn(update, context, target, reason)
        elif cmd in UNWARN_WORDS:
            warns_store.set(None, str(chat_id), str(target.id))
            warns_store.save()
            await _auto_delete(await msg.reply_text(f"✅ اخطارهای {target.first_name} پاک شد."), 8)
        elif cmd in PIN_WORDS:
            await context.bot.pin_chat_message(
                chat_id, msg.reply_to_message.message_id, disable_notification=True)
            await _auto_delete(await msg.reply_text("📌 پین شد."), 5)
        elif cmd in UNPIN_WORDS:
            await context.bot.unpin_chat_message(chat_id, msg.reply_to_message.message_id)
            await _auto_delete(await msg.reply_text("📌 آنپین شد."), 5)
        elif cmd in DEL_WORDS:
            await safe_delete(msg.reply_to_message)
            await _auto_delete(await msg.reply_text("🗑 حذف شد."), 3)
    except TelegramError as e:
        await _auto_delete(await msg.reply_text(f"❌ {e}"), 8)


async def _add_warn(update, context, target, reason):
    chat_id = update.effective_chat.id
    cfg = get_config(chat_id)
    now = time.time()
    entry = warns_store.get(str(chat_id), str(target.id)) or {"history": []}
    history = [t for t in entry.get("history", []) if now - t < cfg["warn_expiry"]]
    history.append(now)

    if len(history) >= cfg["warn_limit"]:
        try:
            await context.bot.ban_chat_member(chat_id, target.id)
            warns_store.set(None, str(chat_id), str(target.id))
            warns_store.save()
            await log_action(context, chat_id, "بن خودکار", update.effective_user, target, reason)
            await _auto_delete(await update.message.reply_text(
                f"⛔️ {target.first_name} با {cfg['warn_limit']} اخطار اخراج شد."), 8)
            return
        except TelegramError as e:
            await _auto_delete(await update.message.reply_text(f"❌ {e}"), 8)
            return

    warns_store.set({"history": history}, str(chat_id), str(target.id))
    warns_store.save()
    await _auto_delete(await update.message.reply_text(
        f"⚠️ {target.first_name} اخطار گرفت ({len(history)}/{cfg['warn_limit']})\n📝 {reason}"), 8)


async def _do_purge(update, context):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    if not msg.reply_to_message:
        await _auto_delete(await msg.reply_text("⚠️ روی پیام ابتدای پاکسازی ریپلای کنید."), 5)
        return
    start_id = msg.reply_to_message.message_id
    end_id = msg.message_id - 1
    count = 0
    batch = []
    for mid in range(end_id, start_id - 1, -1):
        batch.append(mid)
        if len(batch) >= 100:
            try:
                await context.bot.delete_messages(chat_id, batch)
                count += len(batch)
            except TelegramError:
                pass
            batch = []
    if batch:
        try:
            await context.bot.delete_messages(chat_id, batch)
            count += len(batch)
        except TelegramError:
            pass
    await _auto_delete(await msg.reply_text(f"🧹 {count} پیام پاک شد."), 5)


@_admin_only
async def purge_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text("⚠️ روی پیام کاربر ریپلای کنید.")
        return
    target_id = msg.reply_to_message.from_user.id
    chat_id = update.effective_chat.id

    deleted = 0
    status = await msg.reply_text("⏳ در حال پاکسازی...")
    # جستجو در پیام‌های اخیر (max 200 پیام)
    for mid in range(msg.message_id, max(msg.message_id - 200, 1), -1):
        rec = msg_cache.get((chat_id, mid))
        if rec and rec.get("user_id") == target_id:
            try:
                await context.bot.delete_message(chat_id, mid)
                deleted += 1
            except TelegramError:
                pass
    await status.edit_text(f"🧹 {deleted} پیام از کاربر پاک شد.")


# ═══════════════════════════════════════════════════════════════════════
# ۸. فونت‌ساز (۱۵ استایل)
# ═══════════════════════════════════════════════════════════════════════
def _map_chars(text, up=None, low=None, dig=None, extra=None):
    out = []
    for c in text:
        o = ord(c)
        if "A" <= c <= "Z":
            out.append(chr(o - 65 + up) if up else (extra.get(c, c) if extra else c))
        elif "a" <= c <= "z":
            out.append(chr(o - 97 + low) if low else (extra.get(c, c) if extra else c))
        elif dig and "0" <= c <= "9":
            out.append(chr(o - 48 + dig))
        else:
            out.append(c)
    return "".join(out)


def generate_fonts(text):
    script_extra = {"B":0x212C,"E":0x2130,"F":0x2131,"H":0x210B,"I":0x2110,
                    "L":0x2112,"M":0x2133,"R":0x211B,"e":0x212F,"g":0x210A,"o":0x2134}
    fraktur_extra = {"C":0x212D,"H":0x210C,"I":0x2111,"R":0x211C,"Z":0x2128}
    small = {"a":"ᴀ","b":"ʙ","c":"ᴄ","d":"ᴅ","e":"ᴇ","f":"ꜰ","g":"ɢ","h":"ʜ",
             "i":"ɪ","j":"ᴊ","k":"ᴋ","l":"ʟ","m":"ᴍ","n":"ɴ","o":"ᴏ","p":"ᴘ",
             "q":"ǫ","r":"ʀ","s":"s","t":"ᴛ","u":"ᴜ","v":"ᴠ","w":"ᴡ","x":"x",
             "y":"ʏ","z":"ᴢ"}
    return {
        "عادی": text,
        "بولد": _map_chars(text, up=0x1D400, low=0x1D41A, dig=0x1D7CE),
        "ایتالیک": _map_chars(text, up=0x1D434, low=0x1D44E),
        "بولد ایتالیک": _map_chars(text, up=0x1D468, low=0x1D482),
        "اسکریپت": _map_chars(text, up=0x1D49C, low=0x1D4B6, extra=script_extra),
        "بولد اسکریپت": _map_chars(text, up=0x1D4D0, low=0x1D4EA),
        "فراکتور": _map_chars(text, up=0x1D504, low=0x1D51E, extra=fraktur_extra),
        "دابل": _map_chars(text, up=0x1D538, low=0x1D552, dig=0x1D7D8),
        "سنس": _map_chars(text, up=0x1D5A0, low=0x1D5BA, dig=0x1D7E2),
        "سنس بولد": _map_chars(text, up=0x1D5D4, low=0x1D5EE, dig=0x1D7EC),
        "سنس ایتالیک": _map_chars(text, up=0x1D608, low=0x1D622),
        "مونو": _map_chars(text, up=0x1D670, low=0x1D68A, dig=0x1D7F6),
        "دایره": "".join(
            chr(0x24B6 + ord(c) - 65) if "A" <= c <= "Z"
            else chr(0x24D0 + ord(c) - 97) if "a" <= c <= "z"
            else chr(0x2460 + int(c) - 1) if c.isdigit() and c != "0" else c
            for c in text),
        "مربع": "".join(
            chr(0x1F130 + ord(c) - 65) if "A" <= c <= "Z" else c for c in text),
        "کوچک": "".join(small.get(c.lower(), c) for c in text),
    }


@_cooldown(3)
async def font_maker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/font hello`", parse_mode=ParseMode.MARKDOWN)
        return
    text = " ".join(context.args)[:200]
    fonts = generate_fonts(text)
    lines = [f"🔤 **{len(fonts)} استایل:**\n"]
    for name, val in fonts.items():
        lines.append(f"🔹 {name}: `{val}`")
    await update.message.reply_text("\n".join(lines)[:4000], parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════
# ۹. ابزارهای متن
# ═══════════════════════════════════════════════════════════════════════
@_cooldown(3)
async def text_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not context.args or len(context.args) < 2:
        await msg.reply_text(
            "🔧 `/text reverse hello`\n"
            "`/text upper hello` / `lower`\n"
            "`/text length hello` / `md5` / `sha256` / `base64`\n"
            "`/text count hello l` / `replace hello l X`",
            parse_mode=ParseMode.MARKDOWN)
        return
    action = context.args[0].lower()
    args = context.args[1:]
    body = " ".join(args)
    try:
        if action == "reverse":   res = body[::-1]
        elif action == "upper":   res = body.upper()
        elif action == "lower":   res = body.lower()
        elif action == "length":  res = f"طول: {len(body)}"
        elif action == "count" and len(args) >= 2:
            res = f"تعداد '{args[-1]}': {' '.join(args[:-1]).count(args[-1])}"
        elif action == "replace" and len(args) >= 3:
            res = " ".join(args[:-2]).replace(args[-2], args[-1])
        elif action == "md5":     res = hashlib.md5(body.encode()).hexdigest()
        elif action == "sha256":  res = hashlib.sha256(body.encode()).hexdigest()
        elif action == "base64":  res = base64.b64encode(body.encode()).decode()
        else: res = "❌ ناشناخته"
    except Exception as e:
        res = f"❌ {e}"
    await msg.reply_text(f"`{res}`", parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════
# ۱۰. یادداشت‌ها
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = str(update.effective_chat.id)
    args = context.args or []
    if len(args) < 1:
        await msg.reply_text("⚠️ `/save name متن` یا ریپلای روی رسانه")
        return
    name = args[0]
    if msg.reply_to_message and len(args) == 1:
        rep = msg.reply_to_message
        content = {
            "text": rep.text or rep.caption or "",
            "type": "photo" if rep.photo else "video" if rep.video else
                    "document" if rep.document else "text",
            "file_id": (rep.photo[-1].file_id if rep.photo else
                        rep.video.file_id if rep.video else
                        rep.document.file_id if rep.document else None),
        }
    else:
        content = {"text": " ".join(args[1:]), "type": "text", "file_id": None}
    notes_store.set(content, chat, name)
    await msg.reply_text(f"✅ `{name}` ذخیره شد.", parse_mode=ParseMode.MARKDOWN)


async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/get name`")
        return
    note = notes_store.get(str(update.effective_chat.id), context.args[0])
    if not note:
        await update.message.reply_text("❌ وجود ندارد.")
        return
    if note["type"] == "text":
        await update.message.reply_text(note["text"], parse_mode=ParseMode.MARKDOWN)
    else:
        method = getattr(update.message, f"reply_{note['type']}")
        await method(note["file_id"], caption=note.get("text") or None)


async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = notes_store.data.get(str(update.effective_chat.id), {})
    if not notes:
        await update.message.reply_text("📭 خالی")
        return
    await update.message.reply_text(
        "📝 **یادداشت‌ها:**\n" + "\n".join(f"• `{n}`" for n in notes),
        parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def clear_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/clear name`")
        return
    chat = str(update.effective_chat.id)
    name = context.args[0]
    if name in notes_store.data.get(chat, {}):
        del notes_store.data[chat][name]
        notes_store.save()
        await update.message.reply_text(f"🗑 `{name}` حذف شد.")


# ═══════════════════════════════════════════════════════════════════════
# ۱۱. فیلترها + دستورات سفارشی
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 2:
        await update.message.reply_text("⚠️ `/filter کلمه پاسخ`")
        return
    chat = str(update.effective_chat.id)
    filters_store.set(" ".join(context.args[1:]),
                      chat, context.args[0].lower())
    await update.message.reply_text(f"✅ فیلتر `{context.args[0]}` اضافه شد.", parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def del_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    chat = str(update.effective_chat.id)
    data = filters_store.data.get(chat, {})
    word = context.args[0].lower()
    if word in data:
        del data[word]
        filters_store.save()
        await update.message.reply_text("🗑 حذف شد.")
    else:
        await update.message.reply_text("❌ نیست.")


async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = filters_store.data.get(str(update.effective_chat.id), {})
    if not data:
        await update.message.reply_text("📭 خالی")
        return
    await update.message.reply_text(
        "🔍 **فیلترها:**\n" + "\n".join(f"• `{k}`" for k in data),
        parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def set_custom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 2:
        await update.message.reply_text("⚠️ `/setcmd /name متن`")
        return
    chat = str(update.effective_chat.id)
    cmd = context.args[0].lstrip("/").lower()
    reply = " ".join(context.args[1:])
    custom_cmd_store.set(reply, chat, cmd)
    await update.message.reply_text(f"✅ `/{cmd}` ساخته شد.", parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def del_custom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    chat = str(update.effective_chat.id)
    cmd = context.args[0].lstrip("/").lower()
    cmds = custom_cmd_store.data.get(chat, {})
    if cmd in cmds:
        del cmds[cmd]
        custom_cmd_store.save()
        await update.message.reply_text(f"🗑 `/{cmd}` حذف شد.")


async def list_custom_cmds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmds = custom_cmd_store.data.get(str(update.effective_chat.id), {})
    if not cmds:
        await update.message.reply_text("📭 خالی")
        return
    await update.message.reply_text(
        "⚙️ **دستورات سفارشی:**\n" + "\n".join(f"• `/{k}`" for k in cmds),
        parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════
# ۱۲. آمار، لِوِل، ریپ
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    cstats = stats_store.get(chat_id) or {}
    total = sum(cstats.values())
    users = len(cstats)
    top = sorted(cstats.items(), key=lambda x: x[1], reverse=True)[:5]

    lines = []
    for i, (uid, cnt) in enumerate(top, 1):
        try:
            u = await context.bot.get_chat(int(uid))
            name = u.first_name
        except TelegramError:
            name = f"کاربر {uid}"
        lines.append(f"{i}. {name} — {cnt} پیام")

    bars = ""
    if top:
        mx = max(cnt for _, cnt in top)
        for _, cnt in top:
            bars += "█" * max(1, int(20 * cnt / mx)) + "\n"

    uptime = humanize_duration(int(time.time() - START_TIME))
    await update.message.reply_text(
        f"📊 **آمار**\n\n👥 {users}\n💬 {total}\n⏱ {uptime}\n\n"
        f"🏆 **تاپ ۵:**\n" + ("\n".join(lines) if lines else "—") +
        (f"\n\n📈 `{bars}`" if bars else ""),
        parse_mode=ParseMode.MARKDOWN)


async def mylevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    xp = (levels_store.get(chat, user) or {}).get("xp", 0)
    lv = int((xp / 10) ** 0.5)
    nx = (lv + 1) ** 2 * 10
    pv = lv ** 2 * 10
    bar = "▰" * int(15 * (xp - pv) / (nx - pv)) + "▱" * (15 - int(15 * (xp - pv) / (nx - pv)))
    rep = (rep_store.get(chat, user) or {}).get("score", 0)
    await update.message.reply_text(
        f"⭐ **سطح**\n\n🏅 لِوِل `{lv}`\n💎 XP `{xp}`\n"
        f"📊 `{bar}` {xp-pv}/{nx-pv}\n"
        f"❤️ اعتبار: `{rep}`",
        parse_mode=ParseMode.MARKDOWN)


async def top_levels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = str(update.effective_chat.id)
    data = levels_store.data.get(chat, {})
    if not data:
        await update.message.reply_text("📭")
        return
    top = sorted(data.items(), key=lambda x: x[1].get("xp", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    lines = []
    for i, (uid, info) in enumerate(top):
        try:
            u = await context.bot.get_chat(int(uid))
            name = u.first_name
        except TelegramError:
            name = f"کاربر {uid}"
        lv = int((info.get("xp", 0) / 10) ** 0.5)
        lines.append(f"{medals[i]} {name} — Lv.{lv}")
    await update.message.reply_text("🏆 **لیدربورد:**\n\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def rep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    target = msg.reply_to_message.from_user
    if target.id == update.effective_user.id:
        await msg.reply_text("⚠️ به خودت نمی‌تونی.")
        return
    chat = str(update.effective_chat.id)
    data = rep_store.get(chat, str(target.id)) or {"score": 0, "voters": []}
    if update.effective_user.id in data["voters"]:
        await msg.reply_text("⚠️ قبلاً رای دادی.")
        return
    data["score"] += 1
    data["voters"].append(update.effective_user.id)
    rep_store.set(data, chat, str(target.id))
    await msg.reply_text(f"❤️ اعتبار {target.first_name}: {data['score']}")


# ═══════════════════════════════════════════════════════════════════════
# ۱۳. فدراسیون
# ═══════════════════════════════════════════════════════════════════════
@_owner_only
async def create_fed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/newfed name`")
        return
    name = context.args[0]
    if name in feds_store.data:
        await update.message.reply_text("❌ وجود دارد.")
        return
    feds_store.set({"owner": update.effective_user.id,
                    "chats": [update.effective_chat.id], "bans": {}}, name)
    await update.message.reply_text(f"✅ فدراسیون `{name}` ساخته شد.")


@_admin_only
async def join_fed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    name = context.args[0]
    fed = feds_store.get(name)
    if not fed:
        await update.message.reply_text("❌ نیست.")
        return
    cid = update.effective_chat.id
    if cid in fed["chats"]:
        await update.message.reply_text("⚠️ قبلاً عضو هستید.")
        return
    fed["chats"].append(cid)
    feds_store.save()
    await update.message.reply_text(f"✅ پیوستید.")


@_admin_only
async def fed_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text("⚠️ ریپلای کنید.")
        return
    if not context.args:
        await msg.reply_text("⚠️ `/fban name دلیل`")
        return
    name = context.args[0]
    fed = feds_store.get(name)
    if not fed or update.effective_chat.id not in fed["chats"]:
        await msg.reply_text("❌ فدراسیون نیست یا این گروه عضو نیست.")
        return
    target = msg.reply_to_message.from_user
    reason = " ".join(context.args[1:]) or "بدون دلیل"
    fed["bans"][str(target.id)] = reason
    feds_store.save()
    results = []
    for cid in fed["chats"]:
        try:
            await context.bot.ban_chat_member(cid, target.id)
            results.append(f"✅ {cid}")
        except TelegramError:
            results.append(f"❌ {cid}")
    await msg.reply_text(
        f"🌐 **بن فدراسیونی**\n🎯 {target.first_name}\n📝 {reason}\n\n" + "\n".join(results),
        parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════
# ۱۴. برادکست
# ═══════════════════════════════════════════════════════════════════════
@_owner_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = " ".join(context.args or []) if context.args else None
    if not text and not msg.reply_to_message:
        await msg.reply_text("⚠️ `/broadcast متن` یا ریپلای")
        return
    chat_ids = list(config_store.data.keys())
    sent = failed = 0
    status = await msg.reply_text(f"📤 ارسال به {len(chat_ids)} گروه...")
    for cid in chat_ids:
        try:
            if msg.reply_to_message:
                await msg.reply_to_message.copy(int(cid))
            else:
                await context.bot.send_message(int(cid), text, parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except TelegramError:
            failed += 1
    await status.edit_text(f"✅ {sent} ❌ {failed} 👥 {len(chat_ids)}")


# ═══════════════════════════════════════════════════════════════════════
# ۱۵. یادآور + زمان‌بند
# ═══════════════════════════════════════════════════════════════════════
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("⚠️ `/remind 10m پیام`")
        return
    dur = parse_duration(args[0])
    if not dur:
        await update.message.reply_text("❌ فرمت زمان نامعتبر.")
        return
    text = " ".join(args[1:])
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    name = update.effective_user.first_name
    context.job_queue.run_once(
        _send_reminder, dur,
        data={"chat_id": chat_id, "user_id": user_id, "text": text, "name": name},
        name=f"remind_{chat_id}_{user_id}_{time.time()}")
    await update.message.reply_text(
        f"⏰ یادآور در {humanize_duration(dur)}\n📝 {text}")


async def _send_reminder(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    try:
        await context.bot.send_message(
            d["chat_id"], f"⏰ <b>{d['name']}:</b>\n{d['text']}", parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


@_admin_only
async def schedule_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("⚠️ `/schedule 2h متن`")
        return
    dur = parse_duration(args[0])
    if not dur:
        await update.message.reply_text("❌ زمان نامعتبر.")
        return
    text = " ".join(args[1:])
    chat_id = update.effective_chat.id
    context.job_queue.run_once(
        _send_scheduled, dur,
        data={"chat_id": chat_id, "text": text},
        name=f"sched_{chat_id}_{time.time()}")
    await update.message.reply_text(f"⏰ پیام در {humanize_duration(dur)} ارسال می‌شود.")


async def _send_scheduled(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    try:
        await context.bot.send_message(d["chat_id"], d["text"], parse_mode=ParseMode.MARKDOWN)
    except TelegramError:
        pass


# ═══════════════════════════════════════════════════════════════════════
# ۱۶. تنظیم متن‌ها
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ `/setwelcome متن`\nمتغیرها: {name} {mention} {id} {username} {members} {date} {time}")
        return
    chat = update.effective_chat.id
    cfg = get_config(chat)
    cfg["welcome_text"] = " ".join(context.args)
    save_config(chat)
    await update.message.reply_text("✅ متن خوش‌آمد به‌روز شد.")


@_admin_only
async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/setgoodbye متن`")
        return
    chat = update.effective_chat.id
    cfg = get_config(chat)
    cfg["goodbye_text"] = " ".join(context.args)
    save_config(chat)
    await update.message.reply_text("✅ متن خداحافظی به‌روز شد.")


@_admin_only
async def set_welcome_autodel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/autodelwelcome 30` (ثانیه، 0=خاموش)")
        return
    try:
        secs = int(context.args[0])
    except ValueError:
        return
    chat = update.effective_chat.id
    cfg = get_config(chat)
    cfg["welcome_autodelete"] = secs
    save_config(chat)
    await update.message.reply_text(
        "✅ حالت: " + ("خاموش" if secs == 0 else f"{secs} ثانیه"))


@_admin_only
async def set_welcome_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/welcomemute 60` (ثانیه، 0=خاموش)")
        return
    try:
        secs = int(context.args[0])
    except ValueError:
        return
    chat = update.effective_chat.id
    cfg = get_config(chat)
    cfg["welcome_mute_seconds"] = secs
    save_config(chat)
    await update.message.reply_text(
        "✅ سکوت اولیه: " + ("خاموش" if secs == 0 else f"{secs} ثانیه"))


# ═══════════════════════════════════════════════════════════════════════
# ۱۷. قفل‌ها و تنظیمات ویژگی‌ها
# ═══════════════════════════════════════════════════════════════════════
CONFIG_TOGGLES = {
    "antiedit": "ضد ادیت", "antidelete": "لاگ حذف",
    "antibot": "ضد ربات", "antidup": "ضد تکرار",
    "antichain": "ضد فوروارد زنجیره", "nsfw": "فیلتر NSFW",
    "force_channel": "کانال اجباری", "antiflood": "ضد اسپم",
    "antiraid": "ضد ریید", "night_mode": "حالت شب",
    "captcha": "کپچا", "welcome": "خوش‌آمد",
    "ban_reason_required": "دلیل اجباری",
}


@_admin_only
async def toggle_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ `/toggle antiedit`\nکلیدها: " + "، ".join(CONFIG_TOGGLES))
        return
    key = context.args[0].lower()
    if key not in CONFIG_TOGGLES:
        await update.message.reply_text("❌ کلید نامعتبر.")
        return
    chat = update.effective_chat.id
    cfg = get_config(chat)
    cfg[key] = not cfg[key]
    save_config(chat)
    await update.message.reply_text(
        f"✅ {CONFIG_TOGGLES[key]}: {'🟢' if cfg[key] else '🔴'}")


@_admin_only
async def toggle_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ `/lock lock_link`\nکلید: lock_link, lock_forward, lock_media, "
            "lock_sticker, lock_gif, lock_file, lock_voice, lock_video_note, "
            "lock_poll, lock_contact, lock_location, lock_web_page, lock_bot, "
            "lock_inline, lock_game, lock_channel, lock_duplicate, "
            "lock_english, lock_emoji, lock_hashtag, lock_mention")
        return
    key = context.args[0].lower()
    chat = update.effective_chat.id
    cfg = get_config(chat)
    if key not in cfg:
        await update.message.reply_text("❌ کلید نامعتبر.")
        return
    cfg[key] = not cfg[key]
    save_config(chat)
    await update.message.reply_text(f"✅ {key}: {'🟢' if cfg[key] else '🔴'}")


@_admin_only
async def reset_locks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat.id
    cfg = get_config(chat)
    for k in DEFAULT_CONFIG:
        if k.startswith("lock_"):
            cfg[k] = DEFAULT_CONFIG[k]
    save_config(chat)
    await update.message.reply_text("✅ همه قفل‌ها به حالت پیش‌فرض برگشتند.")


@_admin_only
async def set_daily_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/dailylimit 100` (0=بی‌نهایت)")
        return
    try:
        n = int(context.args[0])
    except ValueError:
        return
    chat = update.effective_chat.id
    cfg = get_config(chat)
    cfg["daily_limit"] = max(0, n)
    save_config(chat)
    await update.message.reply_text(f"✅ سقف روزانه: {n or 'بی‌نهایت'}")


# ═══════════════════════════════════════════════════════════════════════
# ۱۸. وایت‌لیست دامنه
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def allow_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/allowdomain t.me`")
        return
    chat = str(update.effective_chat.id)
    dom = context.args[0].lower().replace("https://", "").replace("http://", "").strip("/")
    lst = allowdomain_store.get(chat) or []
    if dom in lst:
        await update.message.reply_text("⚠️ قبلاً هست.")
        return
    lst.append(dom)
    allowdomain_store.set(lst, chat)
    await update.message.reply_text(f"✅ `{dom}` مجاز شد.", parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def disallow_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    chat = str(update.effective_chat.id)
    dom = context.args[0].lower()
    lst = allowdomain_store.get(chat) or []
    if dom in lst:
        lst.remove(dom)
        allowdomain_store.set(lst, chat)
        await update.message.reply_text("✅ حذف شد.")
    else:
        await update.message.reply_text("❌ نبود.")


async def list_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lst = allowdomain_store.get(str(update.effective_chat.id)) or []
    if not lst:
        await update.message.reply_text("📭")
        return
    await update.message.reply_text(
        "🌐 **دامنه‌های مجاز:**\n" + "\n".join(f"• `{d}`" for d in lst),
        parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════
# ۱۹. کلمات ممنوعه
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/addword کلمه`")
        return
    chat = str(update.effective_chat.id)
    word = " ".join(context.args).strip().lower()
    lst = blacklist_store.get(chat) or []
    if word in lst:
        await update.message.reply_text("⚠️ هست.")
        return
    lst.append(word)
    blacklist_store.set(lst, chat)
    await update.message.reply_text(f"✅ `{word}` اضافه شد.", parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def del_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    chat = str(update.effective_chat.id)
    word = " ".join(context.args).strip().lower()
    lst = blacklist_store.get(chat) or []
    if word in lst:
        lst.remove(word)
        blacklist_store.set(lst, chat)
        await update.message.reply_text("🗑 حذف شد.")
    else:
        await update.message.reply_text("❌ نبود.")


async def words_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lst = blacklist_store.get(str(update.effective_chat.id)) or []
    if not lst:
        await update.message.reply_text("📭")
        return
    await update.message.reply_text(
        "🚫 **کلمات ممنوعه:**\n" + "\n".join(f"• `{w}`" for w in lst),
        parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════
# ۲۰. وایت‌لیست کاربران
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def add_trusted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    tid = None
    if msg.reply_to_message:
        tid = msg.reply_to_message.from_user.id
    elif context.args:
        try:
            tid = int(context.args[0])
        except ValueError:
            return
    if not tid:
        await msg.reply_text("⚠️ `/trust` (ریپلای) یا `/trust 123`")
        return
    chat = str(update.effective_chat.id)
    lst = whitelist_store.get(chat) or []
    if tid in lst:
        await msg.reply_text("⚠️ هست.")
        return
    lst.append(tid)
    whitelist_store.set(lst, chat)
    await msg.reply_text(f"✅ `{tid}` معاف شد.", parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def del_trusted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = str(update.effective_chat.id)
    lst = whitelist_store.get(chat) or []
    tid = None
    if update.effective_message.reply_to_message:
        tid = update.effective_message.reply_to_message.from_user.id
    elif context.args:
        try:
            tid = int(context.args[0])
        except ValueError:
            return
    if tid in lst:
        lst.remove(tid)
        whitelist_store.set(lst, chat)
        await update.message.reply_text("✅ حذف شد.")
    else:
        await update.message.reply_text("❌ نبود.")


# ═══════════════════════════════════════════════════════════════════════
# ۲۱. قفل چت + حالت آهسته
# ═══════════════════════════════════════════════════════════════════════
@_admin_only
async def lock_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.effective_chat.set_permissions(
            ChatPermissions(can_send_messages=False))
        await update.message.reply_text("🔒 گروه قفل شد.")
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


@_admin_only
async def unlock_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.effective_chat.set_permissions(ChatPermissions(
            can_send_messages=True, can_send_media_messages=True,
            can_send_other_messages=True, can_add_web_page_previews=True,
            can_send_polls=True, can_invite_users=True))
        await update.message.reply_text("🔓 گروه باز شد.")
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


@_admin_only
async def slow_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/slow 30`")
        return
    try:
        s = int(context.args[0])
    except ValueError:
        return
    try:
        await context.bot.set_chat_slow_mode(update.effective_chat.id, s)
        await update.message.reply_text(f"🐢 حالت آهسته: {s} ثانیه")
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


# ═══════════════════════════════════════════════════════════════════════
# ۲۲. قوانین و خروجی
# ═══════════════════════════════════════════════════════════════════════
async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = get_config(update.effective_chat.id)
    await update.message.reply_text(c["rules_text"], parse_mode=ParseMode.MARKDOWN)


@_admin_only
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ `/setrules متن`")
        return
    c = get_config(update.effective_chat.id)
    c["rules_text"] = " ".join(context.args)
    save_config(update.effective_chat.id)
    await update.message.reply_text("✅ قوانین به‌روز شد.")


@_admin_only
async def export_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat.id
    cfg = get_config(chat)
    data = {
        "config": cfg,
        "blacklist": blacklist_store.get(str(chat)) or [],
        "notes": notes_store.get(str(chat)) or {},
        "filters": filters_store.get(str(chat)) or {},
        "custom_cmds": custom_cmd_store.get(str(chat)) or {},
        "allowdomains": allowdomain_store.get(str(chat)) or [],
    }
    import io
    buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode())
    buf.name = f"chat_{chat}_export.json"
    await update.message.reply_document(buf, caption="💾 خروجی تنظیمات")


# ═══════════════════════════════════════════════════════════════════════
# ۲۳. اطلاعات / آیدی / آپتایم
# ═══════════════════════════════════════════════════════════════════════
async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    t = msg.reply_to_message.from_user if msg.reply_to_message else update.effective_user
    chat = update.effective_chat
    warns = warns_store.get(str(chat.id), str(t.id)) or {"history": []}
    st = (stats_store.get(str(chat.id)) or {}).get(str(t.id), 0)
    xp = (levels_store.get(str(chat.id), str(t.id)) or {}).get("xp", 0)
    rep = (rep_store.get(str(chat.id), str(t.id)) or {}).get("score", 0)
    lv = int((xp / 10) ** 0.5)
    await msg.reply_text(
        f"👤 **اطلاعات**\n\n"
        f"📛 {t.full_name}\n"
        f"🆔 `{t.id}`\n"
        f"🔗 @{t.username or '—'}\n"
        f"🤖 {'✅' if t.is_bot else '❌'}\n"
        f"⚠️ اخطارها: {len(warns.get('history', []))}\n"
        f"💬 پیام‌ها: {st}\n"
        f"⭐ سطح: {lv} ({xp} XP)\n"
        f"❤️ اعتبار: {rep}",
        parse_mode=ParseMode.MARKDOWN)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"👥 چت: `{update.effective_chat.id}`"
    if update.effective_message.reply_to_message:
        text += f"\n👤 `{update.effective_message.reply_to_message.from_user.id}`"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def uptime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⏱ آپتایم: {humanize_duration(int(time.time() - START_TIME))}")


@_admin_only
async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admins = await update.effective_chat.get_administrators()
        lines = [f"{'👑' if a.status == 'creator' else '🛡'} {a.user.first_name} — `{a.user.id}`"
                 for a in admins]
        await update.message.reply_text(
            "👮 **ادمین‌ها:**\n\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text("⚠️ ریپلای کنید.")
        return
    try:
        admins = await update.effective_chat.get_administrators()
        mentions = " ".join(a.user.mention_html() for a in admins if not a.user.is_bot)
        await msg.reply_text(
            f"🚨 <b>گزارش</b>\n"
            f"👤 {update.effective_user.mention_html()}\n"
            f"🎯 {msg.reply_to_message.from_user.mention_html()}\n"
            f"📝 {mentions}",
            parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await msg.reply_text(f"❌ {e}")


# ═══════════════════════════════════════════════════════════════════════
# ۲۴. ابزارهای تفریحی
# ═══════════════════════════════════════════════════════════════════════
QUOTES = [
    "زندگی زیباست اگر بخواهیم 🌹",
    "هر روز یک فرصت جدید است ✨",
    "بهترین انتقام موفقیت است 💪",
    "خنده بر هر درد بی‌درمان دواست 😄",
    "دانش قدرت است 📚",
    "صبوری کلید موفقیت است 🔑",
    "به خودت ایمان داشته باش 🌟",
    "امروز بهتر از دیروز باش 🚀",
    "هرگز تسلیم نشو 🔥",
    "دوستی گنج است 💎",
]


async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💭 {random.choice(QUOTES)}")


async def date_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    await update.message.reply_text(
        f"📅 **تاریخ و ساعت**\n\n"
        f"🗓 میلادی: `{now.strftime('%Y/%m/%d')}`\n"
        f"🗓 شمسی: `{jalali_today()}`\n"
        f"🕐 {now.strftime('%H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN)


async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎲 **{random.randint(1, 6)}**", parse_mode=ParseMode.MARKDOWN)


async def pick_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ `/pick A B C`")
        return
    await update.message.reply_text(
        f"🎯 **{random.choice(context.args)}**", parse_mode=ParseMode.MARKDOWN)


async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 3:
        await update.message.reply_text("⚠️ `/poll سوال گزینه۱ گزینه۲`")
        return
    q = context.args[0]
    opts = context.args[1:]
    if len(opts) > 10:
        await update.message.reply_text("❌ حداکثر ۱۰ گزینه.")
        return
    await update.message.reply_poll(question=q, options=opts, is_anonymous=True)


# ═══════════════════════════════════════════════════════════════════════
# ۲۵. پنل چندصفحه‌ای
# ═══════════════════════════════════════════════════════════════════════
LOCK_LABELS = {
    "lock_link": "🔗 لینک", "lock_forward": "📨 فوروارد",
    "lock_media": "🖼 رسانه", "lock_sticker": "🎭 استیکر",
    "lock_gif": "🎞 گیف", "lock_file": "📁 فایل",
    "lock_voice": "🎤 ویس", "lock_video_note": "📹 ویدیو نوت",
    "lock_poll": "📊 نظرسنجی", "lock_contact": "👤 مخاطب",
    "lock_location": "📍 موقعیت", "lock_web_page": "🌐 پیش‌نمایش",
    "lock_bot": "🤖 ربات", "lock_inline": "✈️ اینلاین",
    "lock_game": "🎮 بازی", "lock_channel": "📢 کانال",
    "lock_duplicate": "🔁 تکراری", "lock_english": "🔤 انگلیسی",
    "lock_emoji": "😀 ایموجی", "lock_hashtag": "#️⃣ هشتگ",
    "lock_mention": "📣 منشن",
}


def _panel_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 قفل‌ها", callback_data="pg_locks"),
         InlineKeyboardButton("⚙️ ویژگی‌ها", callback_data="pg_feat")],
        [InlineKeyboardButton("📝 فیلترها", callback_data="pg_filters"),
         InlineKeyboardButton("📋 قوانین", callback_data="pg_rules")],
        [InlineKeyboardButton("📊 آمار", callback_data="pg_stats")],
    ])


def _panel_locks(c):
    items = list(LOCK_LABELS.items())
    rows = []
    for i in range(0, len(items), 2):
        row = []
        for key, label in items[i:i+2]:
            row.append(InlineKeyboardButton(
                f"{label}: {'🟢' if c.get(key) else '🔴'}",
                callback_data=f"t_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="pg_main")])
    return InlineKeyboardMarkup(rows)


def _panel_feat(c):
    items = list(CONFIG_TOGGLES.items())
    rows = []
    for i in range(0, len(items), 2):
        row = []
        for key, label in items[i:i+2]:
            row.append(InlineKeyboardButton(
                f"{label}: {'🟢' if c.get(key) else '🔴'}",
                callback_data=f"t_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="pg_main")])
    return InlineKeyboardMarkup(rows)


@_admin_only
async def live_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_config(update.effective_chat.id)
    await update.message.reply_text(
        f"⚙️ **پنل v4**\n🆔 `{update.effective_chat.id}`",
        reply_markup=_panel_main(), parse_mode=ParseMode.MARKDOWN)


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await is_admin(update, context):
        return
    chat_id = q.message.chat.id
    c = get_config(chat_id)
    data = q.data

    if data == "pg_main":
        await q.message.edit_text(f"⚙️ **پنل**\n🆔 `{chat_id}`",
                                  reply_markup=_panel_main(),
                                  parse_mode=ParseMode.MARKDOWN)
    elif data == "pg_locks":
        await q.message.edit_text("🔐 **قفل‌ها**", reply_markup=_panel_locks(c),
                                  parse_mode=ParseMode.MARKDOWN)
    elif data == "pg_feat":
        await q.message.edit_text("⚙️ **ویژگی‌ها**", reply_markup=_panel_feat(c))
    elif data == "pg_filters":
        fs = filters_store.data.get(str(chat_id), {})
        text = "🔍 **فیلترها:**\n" + ("\n".join(f"• `{k}`" for k in fs) if fs else "—")
        text += "\n\n`/filter کلمه پاسخ` / `/delfilter کلمه`"
        await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    elif data == "pg_rules":
        await q.message.edit_text(
            c["rules_text"] + "\n\n✏️ `/setrules متن`",
            parse_mode=ParseMode.MARKDOWN)
    elif data == "pg_stats":
        await q.message.edit_text("📊 از `/stats` استفاده کنید.")
    elif data.startswith("t_"):
        key = data[2:]
        if key in c:
            c[key] = not c[key]
            save_config(chat_id)
        markup = _panel_locks(c) if key.startswith("lock_") else _panel_feat(c)
        await q.message.edit_reply_markup(reply_markup=markup)


# ═══════════════════════════════════════════════════════════════════════
# ۲۶. مدیریت خودکار
# ═══════════════════════════════════════════════════════════════════════
async def auto_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or update.effective_chat.type not in ("group", "supergroup"):
        return
    if msg.from_user and msg.from_user.is_bot:
        return

    chat = update.effective_chat
    user = msg.from_user
    c = get_config(chat.id)

    # ذخیره پیام برای antidelete و purgeuser
    text = msg.text or msg.caption or ""
    msg_cache[(chat.id, msg.message_id)] = {
        "user_id": user.id, "text": text, "time": time.time()}
    # پاکسازی کش قدیمی
    if len(msg_cache) > 2000:
        cutoff = time.time() - 3600
        msg_cache_old = [(k, v) for k, v in msg_cache.items() if v["time"] < cutoff]
        for k, _ in msg_cache_old[:1000]:
            msg_cache.pop(k, None)

    # وایت‌لیست
    trusted = whitelist_store.get(str(chat.id)) or []
    if user.id in trusted:
        return
    if await is_admin(update, context):
        return

    # حالت شب
    if c["night_mode"]:
        h = datetime.now().hour
        s, e = c["night_start"], c["night_end"]
        in_n = (s <= h < e) if s < e else (h >= s or h < e)
        if in_n:
            await safe_delete(msg); return

    # کانال اجباری
    if c["force_channel"] and FORCE_CHANNELS:
        missing = await check_membership(user.id, context)
        if missing:
            await safe_delete(msg); return

    # آمار + لِوِل + سقف روزانه
    ck, uk = str(chat.id), str(user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    daily_key = (chat.id, user.id, today)
    daily_counts[daily_key] = daily_counts.get(daily_key, 0) + 1
    if c["daily_limit"] > 0 and daily_counts[daily_key] > c["daily_limit"]:
        await safe_delete(msg); return

    stats_store.data.setdefault(ck, {})
    stats_store.data[ck][uk] = stats_store.data[ck].get(uk, 0) + 1
    if stats_store.data[ck][uk] % 5 == 0:
        stats_store.save()

    lv_data = levels_store.data.get(ck, {})
    if uk not in lv_data:
        lv_data[uk] = {"xp": 0}; levels_store.data[ck] = lv_data
    old_lv = int((lv_data[uk]["xp"] / 10) ** 0.5)
    lv_data[uk]["xp"] += random.randint(1, 3)
    new_lv = int((lv_data[uk]["xp"] / 10) ** 0.5)
    if stats_store.data[ck][uk] % 10 == 0:
        levels_store.save()
    if new_lv > old_lv:
        try:
            await msg.reply_text(f"🎉 {user.first_name} سطح {new_lv}!", parse_mode=ParseMode.MARKDOWN)
        except TelegramError:
            pass

    # ضد اسپم
    if c["antiflood"]:
        now = time.time()
        key = (chat.id, user.id)
        times = [t for t in flood_db.get(key, []) if now - t < c["antiflood_window"]]
        times.append(now)
        flood_db[key] = times
        if len(times) > c["antiflood_limit"]:
            try:
                await context.bot.restrict_chat_member(
                    chat.id, user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=datetime.now() + timedelta(seconds=c["antiflood_mute"]))
                await safe_delete(msg)
                await _auto_delete(await msg.reply_text(
                    f"🌊 {user.first_name} برای {humanize_duration(c['antiflood_mute'])} سکوت شد."), 8)
                flood_db[key] = []
            except TelegramError:
                pass
            return

    # فیلترها (auto-reply)
    for kw, reply in (filters_store.data.get(ck, {})).items():
        if kw in text.lower():
            try:
                await msg.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
            except TelegramError:
                pass
            break

    # کلمات ممنوعه
    tl = text.lower()
    for w in (blacklist_store.get(ck) or []):
        if w.lower() in tl:
            await safe_delete(msg)
            await _auto_delete(await msg.reply_text("🚫 حاوی کلمه ممنوعه"), 4)
            return

    # NSFW
    if c["nsfw"]:
        for w in NSFW_WORDS:
            if w in tl:
                await safe_delete(msg)
                await log_action(context, chat.id, "NSFW", user, reason=w)
                return

    # قفل‌ها
    if c["lock_media"] and (msg.photo or msg.video or msg.audio): await safe_delete(msg); return
    if c["lock_sticker"] and msg.sticker: await safe_delete(msg); return
    if c["lock_gif"] and msg.animation: await safe_delete(msg); return
    if c["lock_file"] and msg.document: await safe_delete(msg); return
    if c["lock_voice"] and msg.voice: await safe_delete(msg); return
    if c["lock_video_note"] and msg.video_note: await safe_delete(msg); return
    if c["lock_poll"] and msg.poll: await safe_delete(msg); return
    if c["lock_contact"] and msg.contact: await safe_delete(msg); return
    if c["lock_location"] and msg.location: await safe_delete(msg); return
    if c["lock_web_page"] and msg.entities:
        if any(e.type in ("url", "text_link") for e in msg.entities):
            await safe_delete(msg); return
    if c["lock_bot"] and msg.via_bot: await safe_delete(msg); return
    if c["lock_inline"] and msg.via_bot: await safe_delete(msg); return
    if c["lock_game"] and msg.game: await safe_delete(msg); return
    if c["lock_forward"] and msg.forward_origin: await safe_delete(msg); return
    if c["lock_channel"] and msg.sender_chat and msg.sender_chat.type == "channel":
        await safe_delete(msg); return

    # قفل لینک با وایت‌لیست دامنه
    if c["lock_link"] and URL_PATTERN.search(text):
        domains = allowdomain_store.get(ck) or []
        found = DOMAIN_PATTERN.findall(text)
        if not found or not all(any(d in dom for dom in domains) for d in found):
            await safe_delete(msg); return

    if c["lock_english"] and ENGLISH_PATTERN.search(text): await safe_delete(msg); return
    if c["lock_emoji"] and EMOJI_PATTERN.search(text): await safe_delete(msg); return
    if c["lock_hashtag"] and HASHTAG_PATTERN.search(text): await safe_delete(msg); return
    if c["lock_mention"] and MENTION_PATTERN.search(text): await safe_delete(msg); return

    # ضد تکرار
    if c["lock_duplicate"]:
        prev = last_msg.get((chat.id, user.id))
        if prev == text and text:
            await safe_delete(msg); return
    last_msg[(chat.id, user.id)] = text


# ═══════════════════════════════════════════════════════════════════════
# ۲۷. ضد ادیت و ضد حذف
# ═══════════════════════════════════════════════════════════════════════
async def anti_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.edited_message or update.edited_channel_post
    if not msg or update.effective_chat.type not in ("group", "supergroup"):
        return
    c = get_config(update.effective_chat.id)
    if not c["antiedit"]:
        return
    if await is_admin(update, context):
        return
    # حذف پیام ادیت شده
    await safe_delete(msg)
    await log_action(context, update.effective_chat.id, "ادیت حذف شد",
                     msg.from_user, reason=f"متن جدید: {msg.text[:50] if msg.text else ''}")


async def anti_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """توسط Polling قابل تشخیص نیست؛ ولی از قبل پیام‌ها را کش می‌کنیم.
    اگر نیاز به لاگ حذف دارید، هنگام حذف توسط ربات لاگ می‌شود.
    این تابع صرفاً برای اتصال به سایر رویدادها."""
    pass


# ═══════════════════════════════════════════════════════════════════════
# ۲۸. زمان‌بند حالت شب
# ═══════════════════════════════════════════════════════════════════════
async def night_mode_tick(context: ContextTypes.DEFAULT_TYPE):
    for ck, c in list(config_store.data.items()):
        if not c.get("night_mode"):
            continue
        try:
            cid = int(ck)
        except ValueError:
            continue
        h = datetime.now().hour
        s, e = c["night_start"], c["night_end"]
        in_n = (s <= h < e) if s < e else (h >= s or h < e)
        try:
            if in_n:
                await context.bot.set_chat_permissions(cid, ChatPermissions(can_send_messages=False))
            else:
                await context.bot.set_chat_permissions(cid, ChatPermissions(
                    can_send_messages=True, can_send_media_messages=True,
                    can_send_other_messages=True, can_add_web_page_previews=True,
                    can_send_polls=True, can_invite_users=True))
        except TelegramError:
            pass


# ═══════════════════════════════════════════════════════════════════════
# ۲۹. Start / Help
# ═══════════════════════════════════════════════════════════════════════
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Ultimate OS v4**\n\n`/help` برای راهنما",
        parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 **راهنما**\n\n"
        "**👮 مدیریت:**\n"
        "`/panel` پنل | `بن` `اخراج` `سکوت` `آزاد` `اخطار`\n"
        "`/purge` `پاکسازی` | `/purgeuser` | `/lock` `/unlock`\n"
        "`/slow 30` | `/trust` (ریپلای)\n\n"
        "**📝 محتوا:**\n"
        "`/save name متن` | `/get` | `/notes` | `/clear`\n"
        "`/filter کلمه پاسخ` | `/delfilter` | `/filters`\n"
        "`/setcmd /name متن` | `/delcmd` | `/cmds`\n"
        "`/addword` | `/delword` | `/words`\n"
        "`/setwelcome متن` | `/setgoodbye`\n"
        "`/setrules` | `/rules`\n\n"
        "**⚙️ تنظیمات:**\n"
        "`/toggle KEY` — ویژگی‌ها\n"
        "`/lock KEY` — قفل‌ها\n"
        "`/resetlocks` | `/dailylimit 100`\n"
        "`/autodelwelcome 30` | `/welcomemute 60`\n"
        "`/allowdomain t.me` | `/deldomain` | `/domains`\n\n"
        "**🌐 فدراسیون:**\n"
        "`/newfed` (مالک) | `/joinfed` | `/fban`\n\n"
        "**📊 آمار:**\n"
        "`/stats` | `/mylevel` | `/toplevels` | `/rep` (ریپلای)\n"
        "`/info` | `/id` | `/adminlist` | `/uptime`\n\n"
        "**🎨 ابزار:**\n"
        "`/font hello` | `/text md5 hello` | `/date`\n"
        "`/roll` | `/pick A B C` | `/poll سوال A B`\n"
        "`/remind 10m متن` | `/schedule 2h متن` | `/quote`\n\n"
        "**👑 مالک:**\n"
        "`/broadcast` | `/export`",
        parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════
# ۳۰. راه‌اندازی
# ═══════════════════════════════════════════════════════════════════════
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("panel", "پنل مدیریت"),
        BotCommand("help", "راهنما"),
        BotCommand("font", "فونت‌ساز"),
        BotCommand("text", "ابزار متن"),
        BotCommand("stats", "آمار"),
        BotCommand("mylevel", "سطح من"),
        BotCommand("rules", "قوانین"),
        BotCommand("date", "تاریخ"),
        BotCommand("save", "ذخیره یادداشت"),
        BotCommand("notes", "یادداشت‌ها"),
        BotCommand("filter", "فیلتر"),
        BotCommand("addword", "کلمه ممنوعه"),
        BotCommand("info", "اطلاعات"),
        BotCommand("remind", "یادآور"),
    ])
    logger.info("✅ Commands set.")


def main():
    app = Application.builder() \
        .token(BOT_TOKEN) \
        .concurrent_updates(True) \
        .post_init(post_init) \
        .build()

    # Callbacks
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^verify_"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern=r"^(pg_|t_)"))

    # Welcome/Goodbye
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))

    # Anti-edit
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, anti_edit_handler))

    # General commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("panel", live_panel))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("mylevel", mylevel))
    app.add_handler(CommandHandler("toplevels", top_levels))
    app.add_handler(CommandHandler("rep", rep_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("uptime", uptime_command))
    app.add_handler(CommandHandler("adminlist", admin_list))
    app.add_handler(CommandHandler("rules", show_rules))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("slow", slow_mode))
    app.add_handler(CommandHandler("report", report_command))

    # Notes
    app.add_handler(CommandHandler("save", save_note))
    app.add_handler(CommandHandler("get", get_note))
    app.add_handler(CommandHandler("notes", list_notes))
    app.add_handler(CommandHandler("clear", clear_note))

    # Filters
    app.add_handler(CommandHandler("filter", add_filter))
    app.add_handler(CommandHandler("delfilter", del_filter))
    app.add_handler(CommandHandler("filters", list_filters))

    # Custom commands
    app.add_handler(CommandHandler("setcmd", set_custom_cmd))
    app.add_handler(CommandHandler("delcmd", del_custom_cmd))
    app.add_handler(CommandHandler("cmds", list_custom_cmds))

    # Words
    app.add_handler(CommandHandler("addword", add_word))
    app.add_handler(CommandHandler("delword", del_word))
    app.add_handler(CommandHandler("words", words_list))

    # Trust
    app.add_handler(CommandHandler("trust", add_trusted))
    app.add_handler(CommandHandler("untrust", del_trusted))

    # Locks & features
    app.add_handler(CommandHandler("lock", lock_chat))
    app.add_handler(CommandHandler("unlock", unlock_chat))
    app.add_handler(CommandHandler("toggle", toggle_config))
    app.add_handler(CommandHandler("tl", toggle_lock))
    app.add_handler(CommandHandler("resetlocks", reset_locks))
    app.add_handler(CommandHandler("dailylimit", set_daily_limit))

    # Domains
    app.add_handler(CommandHandler("allowdomain", allow_domain))
    app.add_handler(CommandHandler("deldomain", disallow_domain))
    app.add_handler(CommandHandler("domains", list_domains))

    # Welcome text
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("setgoodbye", set_goodbye))
    app.add_handler(CommandHandler("autodelwelcome", set_welcome_autodel))
    app.add_handler(CommandHandler("welcomemute", set_welcome_mute))

    # Federation
    app.add_handler(CommandHandler("newfed", create_fed))
    app.add_handler(CommandHandler("joinfed", join_fed))
    app.add_handler(CommandHandler("fban", fed_ban))

    # Owner
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("export", export_config))

    # Tools
    app.add_handler(CommandHandler("font", font_maker))
    app.add_handler(CommandHandler("text", text_tools))
    app.add_handler(CommandHandler("date", date_command))
    app.add_handler(CommandHandler("roll", roll_dice))
    app.add_handler(CommandHandler("pick", pick_random))
    app.add_handler(CommandHandler("poll", create_poll))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("schedule", schedule_msg))
    app.add_handler(CommandHandler("quote", quote_command))

    # Purge
    app.add_handler(CommandHandler("purgeuser", purge_user))

    # Persian commands
    app.add_handler(MessageHandler(
        filters.TEXT & filters.REPLY & ~filters.COMMAND, persian_commands))

    # Custom commands handler (فقط اگر پیام با / شروع شود)
    async def custom_cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        txt = update.message.text.strip()
        if not txt.startswith("/"):
            return
        cmd = txt[1:].split()[0].lower()
        cmds = custom_cmd_store.data.get(str(update.effective_chat.id), {})
        if cmd in cmds:
            try:
                await update.message.reply_text(cmds[cmd], parse_mode=ParseMode.MARKDOWN)
            except TelegramError:
                pass

    app.add_handler(MessageHandler(filters.COMMAND, custom_cmd_handler), group=99)

    # Auto moderator (last)
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION | filters.PHOTO | filters.VIDEO |
         filters.Document.ALL | filters.Sticker.ALL | filters.ANIMATION |
         filters.VOICE | filters.VIDEO_NOTE | filters.POLL |
         filters.CONTACT | filters.LOCATION) & ~filters.COMMAND,
        auto_moderator))

    # Night mode scheduler
    app.job_queue.run_repeating(night_mode_tick, interval=3600, first=15)

    logger.info("🚀 Ultimate OS v4.0 started!")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        stop_signals=None,
    )


if __name__ == "__main__":
    main()
