import os
import sys
import logging
import re
import time
import random
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ---------------------------------------------------------------------------
# تنظیمات لاگ
# ---------------------------------------------------------------------------
logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(message)s", level=logging.INFO)
logger = logging.getLogger("super-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    sys.exit(1)

# ---------------------------------------------------------------------------
# دیتابیس موقت (در حافظه)
# ---------------------------------------------------------------------------
group_configs = {}  # تنظیمات هر گروه
warnings_db = {}    # {(chat_id, user_id): count}
captcha_data = {}   # {user_id: correct_answer}
BAD_WORDS = ["فحش", "بی‌ادب", "کلمه_ممنوعه"]
URL_PATTERN = re.compile(r"(https?://|www\.|t\.me/|@[a-zA-Z0-9_]+)")

def get_config(chat_id):
    if chat_id not in group_configs:
        group_configs[chat_id] = {
            "antilink": True, "antiforward": True, "antiflood": True, 
            "welcome": True, "captcha": True, "media_lock": False
        }
    return group_configs[chat_id]

# ---------------------------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------------------------
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ['administrator', 'creator']
    except:
        return False

# ---------------------------------------------------------------------------
# ۱. سیستم کپچا (ضد ربات)
# ---------------------------------------------------------------------------
async def welcome_and_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    config = get_config(chat_id)
    if not config["welcome"]: return

    for member in update.message.new_chat_members:
        if member.is_bot: continue
        
        if config["captcha"]:
            # ساخت سوال ریاضی تصادفی
            a, b = random.randint(1, 9), random.randint(1, 9)
            correct = a + b
            captcha_data[member.id] = correct
            
            # محدود کردن کاربر تا زمان حل کپچا
            await context.bot.restrict_chat_member(chat_id, member.id, permissions=ChatPermissions(can_send_messages=False))
            
            # ساخت دکمه‌های شیشه‌ای (جواب درست + ۳ جواب غلط)
            options = [correct, correct + random.randint(1,3), correct - random.randint(1,3), correct + random.randint(4,6)]
            random.shuffle(options)
            
            keyboard = [[InlineKeyboardButton(str(opt), callback_data=f"cap_{member.id}_{opt}") for opt in options[i:i+2]] for i in range(0, 4, 2)]
            
            msg = await update.message.reply_text(
                f"👋 سلام {member.first_name} عزیز\n"
                f"برای اثبات اینکه ربات نیستید، به سوال زیر پاسخ دهید:\n\n"
                f"❓ **{a} + {b} = ?**",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            msg = await update.message.reply_text(f"سلام {member.first_name} عزیز 🌹\nبه گروه AA+ خوش آمدید.")

async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    user_id, answer = int(data[1]), int(data[2])
    
    if query.from_user.id != user_id: return # فقط خود کاربر
    
    if captcha_data.get(user_id) == answer:
        # جواب درست -> آزادسازی
        await context.bot.restrict_chat_member(
            query.message.chat_id, user_id, 
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        )
        await query.message.edit_text(f"✅ تایید شد! خوش آمدید {query.from_user.first_name} عزیز.")
        del captcha_data[user_id]
    else:
        await query.message.reply_text("❌ جواب اشتباه است. دوباره تلاش کنید.")

# ---------------------------------------------------------------------------
# ۲. دستورات فارسی (GroupHelp Style)
# ---------------------------------------------------------------------------
async def persian_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text or update.effective_chat.type not in ("group", "supergroup"): return
    if not await is_admin(update, context): return

    text = msg.text.strip()
    chat_id = update.effective_chat.id

    if not msg.reply_to_message:
        if text in ["بن", "سکوت", "اخطار", "آزاد", "پین", "حذف", "پاکسازی"]:
            warn = await msg.reply_text("⚠️ روی پیام کاربر ریپلای کنید.")
            context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id, warn.message_id), 5)
        return

    target = msg.reply_to_message.from_user
    target_name = target.first_name

    if text == "بن":
        await context.bot.ban_chat_member(chat_id, target.id)
        res = await msg.reply_text(f"⛔️ {target_name} اخراج شد.")
    elif text == "سکوت":
        await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False))
        res = await msg.reply_text(f"🔇 {target_name} سکوت شد.")
    elif text == "آزاد":
        await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
        res = await msg.reply_text(f"🔊 {target_name} آزاد شد.")
    elif text == "اخطار":
        w_key = (chat_id, target.id)
        warnings_db[w_key] = warnings_db.get(w_key, 0) + 1
        w_count = warnings_db[w_key]
        if w_count >= 3:
            await context.bot.ban_chat_member(chat_id, target.id)
            res = await msg.reply_text(f"⛔️ {target_name} به دلیل ۳ اخطار اخراج شد.")
            warnings_db[w_key] = 0
        else:
            res = await msg.reply_text(f"⚠️ {target_name} اخطار گرفت. ({w_count}/3)")
    elif text == "پین":
        await context.bot.pin_chat_message(chat_id, msg.reply_to_message.message_id)
        res = await msg.reply_text("📌 پین شد.")
    elif text == "حذف":
        await msg.reply_to_message.delete()
        res = await msg.reply_text("🗑 حذف شد.")
    elif text == "پاکسازی":
        # پاک کردن ۱۰ پیام آخر
        for i in range(msg.message_id - 1, msg.message_id - 11, -1):
            try: await context.bot.delete_message(chat_id, i)
            except: pass
        res = await msg.reply_text("🧹 پاکسازی شد.")
    
    if 'res' in locals():
        context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id, res.message_id), 5)

# ---------------------------------------------------------------------------
# ۳. پنل زنده (Dashboard)
# ---------------------------------------------------------------------------
async def live_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    chat_id = update.effective_chat.id
    c = get_config(chat_id)

    keyboard = [
        [InlineKeyboardButton(f"🔗 ضد لینک: {'🟢' if c['antilink'] else '🔴'}", callback_data="p_antilink"),
         InlineKeyboardButton(f"📨 ضد فوروارد: {'🟢' if c['antiforward'] else '🔴'}", callback_data="p_antiforward")],
        [InlineKeyboardButton(f"🌊 ضد اسپم: {'🟢' if c['antiflood'] else '🔴'}", callback_data="p_antiflood"),
         InlineKeyboardButton(f"👋 خوش‌آمد: {'🟢' if c['welcome'] else '🔴'}", callback_data="p_welcome")],
        [InlineKeyboardButton(f"🤖 کپچا: {'🟢' if c['captcha'] else '🔴'}", callback_data="p_captcha"),
         InlineKeyboardButton(f"🖼 قفل رسانه: {'🟢' if c['media_lock'] else '🔴'}", callback_data="p_media_lock")],
    ]
    await update.message.reply_text("⚙️ **پنل زنده مدیریت AA+**\n\nبرای تغییر وضعیت هر سیستم کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(update, context): return
    
    chat_id = query.message.chat_id
    c = get_config(chat_id)
    action = query.data.replace("p_", "")
    
    if action in c: c[action] = not c[action]
    
    keyboard = [
        [InlineKeyboardButton(f"🔗 ضد لینک: {'🟢' if c['antilink'] else '🔴'}", callback_data="p_antilink"),
         InlineKeyboardButton(f"📨 ضد فوروارد: {'🟢' if c['antiforward'] else '🔴'}", callback_data="p_antiforward")],
        [InlineKeyboardButton(f"🌊 ضد اسپم: {'🟢' if c['antiflood'] else '🔴'}", callback_data="p_antiflood"),
         InlineKeyboardButton(f"👋 خوش‌آمد: {'🟢' if c['welcome'] else '🔴'}", callback_data="p_welcome")],
        [InlineKeyboardButton(f"🤖 کپچا: {'🟢' if c['captcha'] else '🔴'}", callback_data="p_captcha"),
         InlineKeyboardButton(f"🖼 قفل رسانه: {'🟢' if c['media_lock'] else '🔴'}", callback_data="p_media_lock")],
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

# ---------------------------------------------------------------------------
# ۴. مدیریت خودکار
# ---------------------------------------------------------------------------
async def auto_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or update.effective_chat.type not in ("group", "supergroup"): return
    if msg.from_user and msg.from_user.is_bot: return
    if await is_admin(update, context): return

    chat_id = update.effective_chat.id
    c = get_config(chat_id)
    text = msg.text or msg.caption or ""

    # ضد رسانه
    if c["media_lock"] and (msg.photo or msg.video or msg.document or msg.sticker):
        await msg.delete()
        return

    # ضد فوروارد
    if c["antiforward"] and msg.forward_origin:
        await msg.delete()
        return

    # ضد فحش
    for word in BAD_WORDS:
        if word in text:
            await msg.delete()
            return

    # ضد لینک
    if c["antilink"] and URL_PATTERN.search(text):
        await msg.delete()
        return

# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_and_captcha))
    app.add_handler(CallbackQueryHandler(captcha_callback, pattern="^cap_"))
    
    app.add_handler(CommandHandler("panel", live_panel))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^p_"))
    
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, persian_commands))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND, auto_moderator))
    
    logger.info("Super Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
