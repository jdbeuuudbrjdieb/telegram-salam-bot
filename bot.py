import os
import sys
import logging
import re
import time
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ---------------------------------------------------------------------------
# ۱. تنظیمات اولیه
# ---------------------------------------------------------------------------
logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(message)s", level=logging.INFO)
logger = logging.getLogger("ultimate-os")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    sys.exit(1)

FORCE_CHANNEL_ID = "@vcghcxfyuhfr"  # 👈 آیدی کانال خود را اینجا بگذارید
FORCE_CHANNEL_LINK = "https://t.me/vcghcxfyuhfr" # 👈 لینک کانال

# ---------------------------------------------------------------------------
# ۲. دیتابیس‌های حافظه
# ---------------------------------------------------------------------------
group_configs = {}  # تنظیمات قفل‌ها
warns_db = {}       # اخطارها
user_stats = {}     # آمار کاربران
user_flood = {}     # زمان پیام‌ها برای ضد اسپم

BAD_WORDS = ["فحش", "بی‌ادب", "کلمه_ممنوعه"]
URL_PATTERN = re.compile(r"(https?://|www\.|t\.me/|@[a-zA-Z0-9_]+)")

def get_config(chat_id):
    if chat_id not in group_configs:
        group_configs[chat_id] = {
            "lock_link": True, "lock_forward": True, "lock_media": False, 
            "lock_sticker": False, "lock_gif": False, "lock_file": False,
            "force_channel": True, "welcome": True, "antiflood": True
        }
    return group_configs[chat_id]

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ['administrator', 'creator']
    except:
        return False

# ---------------------------------------------------------------------------
# ۳. سیستم کانال اجباری
# ---------------------------------------------------------------------------
async def check_membership(user_id, context) -> bool:
    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL_ID, user_id)
        return member.status not in ['left', 'kicked']
    except:
        return True # در صورت خطا (مثلا ربات در کانال ادمین نیست) اجازه عبور بده

# ---------------------------------------------------------------------------
# ۴. خوش‌آمدگویی و کانال اجباری
# ---------------------------------------------------------------------------
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    config = get_config(chat_id)
    
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        
        keyboard = []
        if config["force_channel"]:
            keyboard.append([InlineKeyboardButton("📢 عضویت در کانال", url=FORCE_CHANNEL_LINK)])
            keyboard.append([InlineKeyboardButton("✅ تایید عضویت", callback_data=f"check_{member.id}")])
            
        msg = await update.message.reply_text(
            f"👋 سلام {member.first_name} عزیز\n"
            f"به گروه **AA+** خوش آمدید.\n\n"
            f"⚠️ برای ارسال پیام، ابتدا در کانال ما عضو شوید.",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode=ParseMode.MARKDOWN
        )

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = int(query.data.split("_")[1])
    
    if await check_membership(user_id, context):
        await context.bot.restrict_chat_member(
            query.message.chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
        )
        await query.message.edit_text(f"✅ تایید شد! خوش آمدید {query.from_user.first_name}.")
    else:
        await query.answer("❌ شما هنوز در کانال عضو نشده‌اید!", show_alert=True)

# ---------------------------------------------------------------------------
# ۵. دستورات فارسی (بن، سکوت، پاکسازی و...)
# ---------------------------------------------------------------------------
async def persian_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text or update.effective_chat.type not in ("group", "supergroup"): return
    if not await is_admin(update, context): return

    text = msg.text.strip()
    chat_id = update.effective_chat.id

    if text == "پاکسازی":
        if not msg.reply_to_message:
            res = await msg.reply_text("⚠️ روی پیامی که می‌خواهید از آنجا پاکسازی شود ریپلای کنید.")
        else:
            count = 0
            for i in range(msg.message_id - 1, msg.reply_to_message.message_id - 1, -1):
                try:
                    await context.bot.delete_message(chat_id, i)
                    count += 1
                except: pass
            res = await msg.reply_text(f"🧹 {count} پیام پاکسازی شد.")
        context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id, res.message_id), 5)
        return

    if not msg.reply_to_message:
        if text in ["بن", "سکوت", "اخطار", "آزاد", "پین", "حذف"]:
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
        warns_db[w_key] = warns_db.get(w_key, 0) + 1
        w_count = warns_db[w_key]
        if w_count >= 3:
            await context.bot.ban_chat_member(chat_id, target.id)
            res = await msg.reply_text(f"⛔️ {target_name} به دلیل ۳ اخطار اخراج شد.")
            warns_db[w_key] = 0
        else:
            res = await msg.reply_text(f"⚠️ {target_name} اخطار گرفت. ({w_count}/3)")
    elif text == "پین":
        await context.bot.pin_chat_message(chat_id, msg.reply_to_message.message_id)
        res = await msg.reply_text("📌 پین شد.")
    elif text == "حذف":
        await msg.reply_to_message.delete()
        res = await msg.reply_text("🗑 حذف شد.")
    
    if 'res' in locals():
        context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id, res.message_id), 5)

# ---------------------------------------------------------------------------
# ۶. فونت ساز هوشمند (۱۰ استایل)
# ---------------------------------------------------------------------------
async def font_maker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ مثال: `/font hello`")
        return
    
    text = " ".join(context.args)
    # تبدیل به فونت‌های مختلف یونیکد
    bold = "".join([chr(ord(c) + 119743) if 'a' <= c <= 'z' else chr(ord(c) + 119737) if 'A' <= c <= 'Z' else c for c in text])
    italic = "".join([chr(ord(c) + 119795) if 'a' <= c <= 'z' else chr(ord(c) + 119789) if 'A' <= c <= 'Z' else c for c in text])
    script = "".join([chr(ord(c) + 119925) if 'a' <= c <= 'z' else chr(ord(c) + 119919) if 'A' <= c <= 'Z' else c for c in text])
    
    result = (
        f"🔤 **فونت‌های شما:**\n\n"
        f"🔹 عادی: {text}\n"
        f"🔹 بولد: {bold}\n"
        f"🔹 ایتالیک: {italic}\n"
        f"🔹 اسکریپت: {script}"
    )
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)

# ---------------------------------------------------------------------------
# ۷. آمار پیشرفته
# ---------------------------------------------------------------------------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    chat_id = update.effective_chat.id
    
    total_msgs = sum([v for (c_id, u_id), v in user_stats.items() if c_id == chat_id])
    active_users = len(set([u_id for (c_id, u_id) in user_stats.keys() if c_id == chat_id]))
    
    await update.message.reply_text(
        f"📊 **آمار گروه AA+**\n\n"
        f"👥 اعضای فعال: {active_users}\n"
        f"💬 کل پیام‌ها: {total_msgs}\n"
        f"🛡 وضعیت: Ultimate OS Active",
        parse_mode=ParseMode.MARKDOWN
    )

# ---------------------------------------------------------------------------
# ۸. پنل زنده قفل‌ها (Dashboard)
# ---------------------------------------------------------------------------
async def live_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    chat_id = update.effective_chat.id
    c = get_config(chat_id)

    keyboard = [
        [InlineKeyboardButton(f"🔗 قفل لینک: {'🟢' if c['lock_link'] else '🔴'}", callback_data="p_lock_link"),
         InlineKeyboardButton(f"📨 قفل فوروارد: {'🟢' if c['lock_forward'] else '🔴'}", callback_data="p_lock_forward")],
        [InlineKeyboardButton(f"🖼 قفل رسانه: {'🟢' if c['lock_media'] else '🔴'}", callback_data="p_lock_media"),
         InlineKeyboardButton(f"🎭 قفل استیکر: {'🟢' if c['lock_sticker'] else '🔴'}", callback_data="p_lock_sticker")],
        [InlineKeyboardButton(f"🎞 قفل گیف: {'🟢' if c['lock_gif'] else '🔴'}", callback_data="p_lock_gif"),
         InlineKeyboardButton(f"📁 قفل فایل: {'🟢' if c['lock_file'] else '🔴'}", callback_data="p_lock_file")],
        [InlineKeyboardButton(f"📢 کانال اجباری: {'🟢' if c['force_channel'] else '🔴'}", callback_data="p_force_channel"),
         InlineKeyboardButton(f"🌊 ضد اسپم: {'🟢' if c['antiflood'] else '🔴'}", callback_data="p_antiflood")],
    ]
    await update.message.reply_text("⚙️ **پنل مدیریت AA+ (Ultimate)**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(update, context): return
    
    chat_id = query.message.chat_id
    c = get_config(chat_id)
    action = query.data.replace("p_", "")
    
    if action in c: c[action] = not c[action]
    
    keyboard = [
        [InlineKeyboardButton(f"🔗 قفل لینک: {'🟢' if c['lock_link'] else '🔴'}", callback_data="p_lock_link"),
         InlineKeyboardButton(f"📨 قفل فوروارد: {'🟢' if c['lock_forward'] else '🔴'}", callback_data="p_lock_forward")],
        [InlineKeyboardButton(f"🖼 قفل رسانه: {'🟢' if c['lock_media'] else '🔴'}", callback_data="p_lock_media"),
         InlineKeyboardButton(f"🎭 قفل استیکر: {'🟢' if c['lock_sticker'] else '🔴'}", callback_data="p_lock_sticker")],
        [InlineKeyboardButton(f"🎞 قفل گیف: {'🟢' if c['lock_gif'] else '🔴'}", callback_data="p_lock_gif"),
         InlineKeyboardButton(f"📁 قفل فایل: {'🟢' if c['lock_file'] else '🔴'}", callback_data="p_lock_file")],
        [InlineKeyboardButton(f"📢 کانال اجباری: {'🟢' if c['force_channel'] else '🔴'}", callback_data="p_force_channel"),
         InlineKeyboardButton(f"🌊 ضد اسپم: {'🟢' if c['antiflood'] else '🔴'}", callback_data="p_antiflood")],
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

# ---------------------------------------------------------------------------
# ۹. مدیریت خودکار (Auto Moderator)
# ---------------------------------------------------------------------------
async def auto_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or update.effective_chat.type not in ("group", "supergroup"): return
    if msg.from_user and msg.from_user.is_bot: return
    if await is_admin(update, context): return

    chat_id = update.effective_chat.id
    c = get_config(chat_id)
    user_id = msg.from_user.id

    # کانال اجباری
    if c["force_channel"]:
        if not await check_membership(user_id, context):
            await msg.delete()
            return

    # آمارگیری
    stat_key = (chat_id, user_id)
    user_stats[stat_key] = user_stats.get(stat_key, 0) + 1

    text = msg.text or msg.caption or ""

    # قفل‌ها
    if c["lock_media"] and (msg.photo or msg.video or msg.audio):
        await msg.delete()
        return
    if c["lock_sticker"] and msg.sticker:
        await msg.delete()
        return
    if c["lock_gif"] and msg.animation:
        await msg.delete()
        return
    if c["lock_file"] and msg.document:
        await msg.delete()
        return
    if c["lock_forward"] and msg.forward_origin:
        await msg.delete()
        return
    for word in BAD_WORDS:
        if word in text:
            await msg.delete()
            return
    if c["lock_link"] and URL_PATTERN.search(text):
        await msg.delete()
        return

# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_"))
    
    app.add_handler(CommandHandler("panel", live_panel))
    app.add_handler(CommandHandler("font", font_maker))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^p_"))
    
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, persian_commands))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION | filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.Sticker.ALL | filters.ANIMATION) & ~filters.COMMAND, auto_moderator))
    
    logger.info("Ultimate OS Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
