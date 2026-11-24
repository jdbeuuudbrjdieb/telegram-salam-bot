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
import requests
from datetime import datetime, timedelta
from functools import wraps
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from telegram.error import TelegramError

# =========================================================================================
# ۱. تنظیمات اولیه و دیتابیس ابری گیت‌هاب
# =========================================================================================
logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(message)s", level=logging.INFO)
logger = logging.getLogger("Ultimate-OS-v6")
START_TIME = time.time()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GH_PAT = os.getenv("GH_PAT", "")
GH_REPO = os.getenv("GITHUB_REPOSITORY", "") # دریافت خودکار نام مخزن از گیت‌هاب

if not BOT_TOKEN: sys.exit("BOT_TOKEN missing")

class GitHubDB:
    def __init__(self, token, repo):
        self.token, self.repo = token, repo
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        self.sha = None
        self.data = self._load()
        self.lock = asyncio.Lock()

    def _load(self):
        if not self.token or not self.repo: return {}
        try:
            url = f"https://api.github.com/repos/{self.repo}/contents/db.json"
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                self.sha = res.json()["sha"]
                return json.loads(base64.b64decode(res.json()["content"]).decode("utf-8"))
            return {}
        except Exception: return {}

    async def save(self):
        if not self.token or not self.repo: return
        async with self.lock:
            try:
                url = f"https://api.github.com/repos/{self.repo}/contents/db.json"
                content = base64.b64encode(json.dumps(self.data, ensure_ascii=False, indent=2).encode()).decode()
                payload = {"message": "Auto-update DB", "content": content}
                if self.sha: payload["sha"] = self.sha
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, lambda: requests.put(url, headers=self.headers, json=payload, timeout=10))
                if res.status_code in (200, 201): self.sha = res.json()["content"]["sha"]
            except Exception as e: logger.error(f"DB Save Error: {e}")

db = GitHubDB(GH_PAT, GH_REPO)

# =========================================================================================
# ۲. توابع دیتابیس و تنظیمات پیش‌فرض
# =========================================================================================
def get_chat(chat_id):
    cid = str(chat_id)
    if "chats" not in db.data: db.data["chats"] = {}
    if cid not in db.data["chats"]: db.data["chats"][cid] = {"config": {}, "users": {}, "notes": {}, "filters": {}}
    return db.data["chats"][cid]

def get_user(chat_id, user_id):
    uid = str(user_id)
    cdata = get_chat(chat_id)
    if uid not in cdata["users"]: cdata["users"][uid] = {"warns": 0, "msgs": 0, "xp": 0}
    return cdata["users"][uid]

def get_config(chat_id):
    cdata = get_chat(chat_id)
    if not cdata["config"]:
        cdata["config"] = {
            "lock_link": True, "lock_forward": True, "lock_media": False, "lock_sticker": False,
            "lock_bot": False, "lock_english": False, "lock_emoji": False, "force_channel": False,
            "welcome": True, "antiflood": True, "antiedit": True
        }
    return cdata["config"]

# =========================================================================================
# ۳. توابع کمکی
# =========================================================================================
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None) -> bool:
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"): return False
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, user_id or update.effective_user.id)
        return m.status in ("administrator", "creator")
    except: return False

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if not await is_admin(update, context): return
        return await func(update, context, *a, **kw)
    return wrapper

async def auto_del(msg, sec=5):
    if not msg: return
    async def _del():
        await asyncio.sleep(sec)
        try: await msg.delete()
        except: pass
    asyncio.create_task(_del())

def parse_time(t):
    if not t: return 0
    m = re.match(r"^(\d+)(s|m|h|d)?$", t.lower())
    if not m: return 0
    n, u = int(m.group(1)), m.group(2) or "m"
    return n * {"s":1, "m":60, "h":3600, "d":86400}[u]

# =========================================================================================
# ۴. پنل مدیریت چندصفحه‌ای
# =========================================================================================
@admin_only
async def live_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔐 مدیریت قفل‌ها", callback_data="menu_locks")],
        [InlineKeyboardButton("⚙️ تنظیمات ربات", callback_data="menu_features")],
        [InlineKeyboardButton("📊 آمار و اطلاعات", callback_data="menu_stats")]
    ]
    await update.message.reply_text("⚙️ **پنل مدیریت Enterprise**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await is_admin(update, context): return
    
    chat_id = q.message.chat.id
    cfg = get_config(chat_id)
    action = q.data

    if action == "menu_locks":
        kb = [
            [InlineKeyboardButton(f"🔗 لینک: {'🟢' if cfg['lock_link'] else '🔴'}", callback_data="toggle_lock_link"),
             InlineKeyboardButton(f"📨 فوروارد: {'🟢' if cfg['lock_forward'] else '🔴'}", callback_data="toggle_lock_forward")],
            [InlineKeyboardButton(f"🖼 رسانه: {'🟢' if cfg['lock_media'] else '🔴'}", callback_data="toggle_lock_media"),
             InlineKeyboardButton(f"🎭 استیکر: {'🟢' if cfg['lock_sticker'] else '🔴'}", callback_data="toggle_lock_sticker")],
            [InlineKeyboardButton(f"🤖 ربات: {'🟢' if cfg['lock_bot'] else '🔴'}", callback_data="toggle_lock_bot"),
             InlineKeyboardButton(f"🔤 انگلیسی: {'🟢' if cfg['lock_english'] else '🔴'}", callback_data="toggle_lock_english")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]
        ]
        await q.message.edit_text("🔐 **مدیریت قفل‌ها:**", reply_markup=InlineKeyboardMarkup(kb))
    elif action == "menu_features":
        kb = [
            [InlineKeyboardButton(f"📢 کانال اجباری: {'🟢' if cfg['force_channel'] else '🔴'}", callback_data="toggle_force_channel"),
             InlineKeyboardButton(f"👋 خوش‌آمد: {'🟢' if cfg['welcome'] else '🔴'}", callback_data="toggle_welcome")],
            [InlineKeyboardButton(f"🌊 ضد اسپم: {'🟢' if cfg['antiflood'] else '🔴'}", callback_data="toggle_antiflood"),
             InlineKeyboardButton(f"📝 ضد ادیت: {'🟢' if cfg['antiedit'] else '🔴'}", callback_data="toggle_antiedit")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]
        ]
        await q.message.edit_text("⚙️ **تنظیمات ربات:**", reply_markup=InlineKeyboardMarkup(kb))
    elif action == "menu_stats":
        cdata = get_chat(chat_id)
        await q.message.edit_text(f"📊 **آمار گروه:**\n\n👥 کاربران: {len(cdata['users'])}\n💬 کل پیام‌ها: {sum(u.get('msgs',0) for u in cdata['users'].values())}")
    elif action.startswith("toggle_"):
        key = action.replace("toggle_", "")
        if key in cfg:
            cfg[key] = not cfg[key]
            await db.save()
        await panel_callback(update, context) # رفرش
    elif action == "menu_main":
        await live_panel(q.message, context) # Hacky way to refresh main menu

# =========================================================================================
# ۵. دستورات فارسی (GroupHelp Style)
# =========================================================================================
@admin_only
async def persian_cmds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.text or update.effective_chat.type not in ("group", "supergroup"): return
    
    text = msg.text.strip().split()
    cmd = text[0]
    chat_id = update.effective_chat.id

    if cmd == "پاکسازی":
        if not msg.reply_to_message: return await auto_del(await msg.reply_text("⚠️ روی پیام ریپلای کنید."))
        count = 0
        for i in range(msg.message_id, msg.reply_to_message.message_id - 1, -1):
            try: await context.bot.delete_message(chat_id, i); count += 1
            except: pass
        return await auto_del(await msg.reply_text(f"🧹 {count} پیام پاک شد."))

    if cmd not in ["بن", "سکوت", "آزاد", "اخطار", "پین", "حذف"]: return
    if not msg.reply_to_message: return await auto_del(await msg.reply_text("⚠️ روی پیام کاربر ریپلای کنید."))

    target = msg.reply_to_message.from_user
    udata = get_user(chat_id, target.id)

    if cmd == "بن":
        await context.bot.ban_chat_member(chat_id, target.id)
        await auto_del(await msg.reply_text(f"⛔️ {target.first_name} بن شد."))
    elif cmd == "سکوت":
        await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False))
        await auto_del(await msg.reply_text(f"🔇 {target.first_name} سکوت شد."))
    elif cmd == "آزاد":
        await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
        await auto_del(await msg.reply_text(f"🔊 {target.first_name} آزاد شد."))
    elif cmd == "اخطار":
        udata["warns"] += 1
        await db.save()
        if udata["warns"] >= 3:
            await context.bot.ban_chat_member(chat_id, target.id)
            udata["warns"] = 0
            await db.save()
            await auto_del(await msg.reply_text(f"⛔️ {target.first_name} با ۳ اخطار بن شد."))
        else:
            await auto_del(await msg.reply_text(f"⚠️ {target.first_name} اخطار گرفت ({udata['warns']}/3)."))
    elif cmd == "پین":
        await context.bot.pin_chat_message(chat_id, msg.reply_to_message.message_id)
        await auto_del(await msg.reply_text("📌 پین شد."))
    elif cmd == "حذف":
        await msg.reply_to_message.delete()
        await auto_del(await msg.reply_text("🗑 حذف شد."))

# =========================================================================================
# ۶. مدیریت خودکار، خوش‌آمدگویی و کانال اجباری
# =========================================================================================
async def welcome_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cfg = get_config(chat_id)
    for m in update.message.new_chat_members:
        if m.is_bot: continue
        
        kb = []
        if cfg["force_channel"]:
            kb.append([InlineKeyboardButton("📢 عضویت در کانال", url="https://t.me/Your_Channel")])
            kb.append([InlineKeyboardButton("✅ تایید", callback_data=f"verify_{m.id}")])
            await context.bot.restrict_chat_member(chat_id, m.id, permissions=ChatPermissions(can_send_messages=False))
            
        txt = f"👋 سلام {m.mention_html()} عزیز\nبه گروه AA+ خوش آمدید."
        if cfg["force_channel"]: txt += "\n\n⚠️ برای ارسال پیام در کانال عضو شوید."
        sent = await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb) if kb else None, parse_mode=ParseMode.HTML)
        await auto_del(sent, 60)

async def verify_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = int(q.data.split("_")[1])
    if q.from_user.id != uid: return
    await context.bot.restrict_chat_member(q.message.chat.id, uid, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
    await q.message.edit_text(f"✅ تایید شد! خوش آمدید {q.from_user.first_name}.")

async def auto_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or update.effective_chat.type not in ("group", "supergroup"): return
    if msg.from_user.is_bot or await is_admin(update, context): return

    chat_id = update.effective_chat.id
    cfg = get_config(chat_id)
    udata = get_user(chat_id, msg.from_user.id)
    text = msg.text or msg.caption or ""

    # آمار و XP
    udata["msgs"] += 1
    udata["xp"] += 5
    if udata["msgs"] % 20 == 0: await db.save() # ذخیره هر ۲۰ پیام برای جلوگیری از بلاک شدن API

    # قفل‌ها
    if cfg["lock_media"] and (msg.photo or msg.video): return await msg.delete()
    if cfg["lock_sticker"] and msg.sticker: return await msg.delete()
    if cfg["lock_bot"] and msg.via_bot: return await msg.delete()
    if cfg["lock_forward"] and msg.forward_origin: return await msg.delete()
    if cfg["lock_link"] and re.search(r"(https?://|t\.me/|@[a-zA-Z0-9_]+)", text): return await msg.delete()
    if cfg["lock_english"] and re.search(r"[a-zA-Z]{4,}", text): return await msg.delete()
    
    # فیلترهای پاسخ خودکار
    filters_dict = get_chat(chat_id)["filters"]
    for k, v in filters_dict.items():
        if k in text.lower(): return await msg.reply_text(v)

# =========================================================================================
# ۷. ابزارها (فونت، یادداشت، فیلتر، سرگرمی)
# =========================================================================================
async def font_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("⚠️ `/font hello`")
    t = " ".join(context.args)
    b = "".join([chr(ord(c)+119743) if 'a'<=c<='z' else chr(ord(c)+119737) if 'A'<=c<='Z' else c for c in t])
    i = "".join([chr(ord(c)+119795) if 'a'<=c<='z' else c for c in t])
    await update.message.reply_text(f"عادی: {t}\nبولد: {b}\nایتالیک: {i}")

@admin_only
async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return await update.message.reply_text("⚠️ `/save name متن`")
    name, text = context.args[0], " ".join(context.args[1:])
    get_chat(update.effective_chat.id)["notes"][name] = text
    await db.save()
    await update.message.reply_text(f"✅ `{name}` ذخیره شد.")

async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    note = get_chat(update.effective_chat.id)["notes"].get(context.args[0])
    if note: await update.message.reply_text(note)
    else: await update.message.reply_text("❌ پیدا نشد.")

@admin_only
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return
    k, v = context.args[0].lower(), " ".join(context.args[1:])
    get_chat(update.effective_chat.id)["filters"][k] = v
    await db.save()
    await update.message.reply_text(f"✅ فیلتر `{k}` ساخته شد.")

async def dice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎲 نتیجه: **{random.randint(1,6)}**", parse_mode=ParseMode.MARKDOWN)

# =========================================================================================
# ۸. راه‌اندازی
# =========================================================================================
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("panel", "پنل مدیریت"), BotCommand("font", "فونت ساز"),
        BotCommand("save", "ذخیره یادداشت"), BotCommand("get", "دریافت یادداشت"),
        BotCommand("filter", "ساخت فیلتر"), BotCommand("dice", "تاس")
    ])

def main():
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()

    app.add_handler(CallbackQueryHandler(verify_cb, pattern="^verify_"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^(menu_|toggle_)"))
    
    app.add_handler(CommandHandler("panel", live_panel))
    app.add_handler(CommandHandler("font", font_cmd))
    app.add_handler(CommandHandler("save", save_note))
    app.add_handler(CommandHandler("get", get_note))
    app.add_handler(CommandHandler("filter", add_filter))
    app.add_handler(CommandHandler("dice", dice_cmd))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member))
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, persian_cmds))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Sticker.ALL) & ~filters.COMMAND, auto_moderator))

    logger.info("🚀 Ultimate OS v6.0 Started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
