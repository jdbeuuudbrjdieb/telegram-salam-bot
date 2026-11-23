import os
import sys
import logging
import random
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# ---------------------------------------------------------------------------
# تنظیمات لاگینگ و توکن
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("quran-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN missing")
    sys.exit(1)

BASE_API = "https://api.alquran.cloud/v1"

# ---------------------------------------------------------------------------
# دستور /start با دکمه‌های شیشه‌ای
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("📖 متن قرآن (عثمانی)", callback_data="guide_text")],
        [InlineKeyboardButton("🇮🇷 ترجمه فارسی", callback_data="guide_fa")],
        [InlineKeyboardButton("🎧 صوت قرآن", callback_data="guide_audio")],
        [InlineKeyboardButton("🔍 راهنمای جستجو", callback_data="guide_search")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "🌹 **به ربات قرآن‌یار خوش آمدید**\n\n"
        "این ربات با اتصال به معتبرترین سرورهای قرآنی جهان، "
        "کل ۳۰ جزئ را بدون هیچ اشتباهی در اختیار شما قرار می‌دهد.\n\n"
        "برای شروع، یکی از گزینه‌های زیر را انتخاب کنید یا از دستورات زیر استفاده کنید:"
    )
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# ---------------------------------------------------------------------------
# مدیریت دکمه‌های شیشه‌ای
# ---------------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "guide_text":
        await query.message.reply_text("📖 برای دریافت متن، دستور زیر را بفرستید:\n`/juz 1`\n(شماره را بین ۱ تا ۳۰ تغییر دهید)", parse_mode=ParseMode.MARKDOWN)
    elif query.data == "guide_fa":
        await query.message.reply_text("🇮🇷 برای دریافت ترجمه، دستور زیر را بفرستید:\n`/fa 1`\n(شماره را بین ۱ تا ۳۰ تغییر دهید)", parse_mode=ParseMode.MARKDOWN)
    elif query.data == "guide_audio":
        await query.message.reply_text("🎧 برای دریافت صوت، دستور زیر را بفرستید:\n`/audio 1`\n(شماره را بین ۱ تا ۳۰ تغییر دهید)", parse_mode=ParseMode.MARKDOWN)
    elif query.data == "guide_search":
        await query.message.reply_text("🔍 برای جستجو، دستور زیر را بفرستید:\n`/search رحمت`\n(کلمه مورد نظر خود را جایگزین کنید)", parse_mode=ParseMode.MARKDOWN)

# ---------------------------------------------------------------------------
# دستور /juz (متن عثمانی)
# ---------------------------------------------------------------------------
async def get_juz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ لطفاً شماره جزئ را وارد کنید. مثال:\n`/juz 1`", parse_mode=ParseMode.MARKDOWN)
        return
        
    try:
        juz_num = int(context.args[0])
        if not 1 <= juz_num <= 30: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ شماره جزئ باید بین ۱ تا ۳۰ باشد.")
        return

    msg = await update.message.reply_text(f"⏳ در حال دریافت جزئ {juz_num} از سرور...")
    
    try:
        res = requests.get(f"{BASE_API}/juz/{juz_num}/quran-uthmani", timeout=15).json()
        if res.get("code") != 200: raise Exception("API Error")
        
        ayahs = res["data"]["ayahs"]
        await msg.edit_text(f"📖 **جزئ {juz_num} (متن عثمانی)**\n\n")
        
        chunk = ""
        for ayah in ayahs:
            chunk += f"﴿{ayah['text']}﴾ ({ayah['numberInSurah']})\n"
            if len(chunk) > 3500:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                chunk = ""
        if chunk:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            
    except Exception as e:
        logger.error(f"Error in get_juz: {e}")
        await msg.edit_text("❌ خطا در دریافت اطلاعات از سرور. لطفاً دوباره تلاش کنید.")

# ---------------------------------------------------------------------------
# دستور /fa (ترجمه فارسی)
# ---------------------------------------------------------------------------
async def get_fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ مثال: `/fa 1`", parse_mode=ParseMode.MARKDOWN)
        return
        
    try:
        juz_num = int(context.args[0])
        if not 1 <= juz_num <= 30: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ شماره جزئ باید بین ۱ تا ۳۰ باشد.")
        return
        
    msg = await update.message.reply_text(f"⏳ در حال دریافت جزئ {juz_num} با ترجمه...")
    try:
        res = requests.get(f"{BASE_API}/juz/{juz_num}/quran-uthmani,fa.fooladvand", timeout=15).json()
        ayahs = res["data"]["ayahs"]
        await msg.edit_text(f"📖 **جزئ {juz_num} (متن + ترجمه)**\n\n")
        
        chunk = ""
        for i in range(0, len(ayahs), 2):
            ar = ayahs[i]
            fa = ayahs[i+1]
            chunk += f"﴿{ar['text']}﴾\n🇮🇷 {fa['text']}\n\n"
            if len(chunk) > 3500:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                chunk = ""
        if chunk:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in get_fa: {e}")
        await msg.edit_text("❌ خطا در دریافت ترجمه.")

# ---------------------------------------------------------------------------
# دستور /audio (صوت)
# ---------------------------------------------------------------------------
async def get_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ مثال: `/audio 1`", parse_mode=ParseMode.MARKDOWN)
        return
        
    try:
        juz_num = int(context.args[0])
        if not 1 <= juz_num <= 30: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ شماره جزئ باید بین ۱ تا ۳۰ باشد.")
        return
        
    msg = await update.message.reply_text(f"⏳ در حال دریافت صوت جزئ {juz_num}...")
    try:
        res = requests.get(f"{BASE_API}/juz/{juz_num}/quran-uthmani", timeout=15).json()
        surah_num = res["data"]["ayahs"][0]["surah"]["number"]
        surah_name = res["data"]["ayahs"][0]["surah"]["name"]
        
        # استفاده از قاری مشهور (مشاری العفاسی)
        audio_res = requests.get(f"{BASE_API}/surah/{surah_num}/ar.alafasy", timeout=15).json()
        audio_url = audio_res["data"]["ayahs"][0]["audio"]
        
        await msg.edit_text(f"🎧 صوت جزئ {juz_num} (شروع از سوره {surah_name})")
        await update.message.reply_audio(audio=audio_url, title=f"Juz {juz_num}")
    except Exception as e:
        logger.error(f"Error in get_audio: {e}")
        await msg.edit_text("❌ خطا در دریافت صوت.")

# ---------------------------------------------------------------------------
# دستور /search (جستجو)
# ---------------------------------------------------------------------------
async def search_quran(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ مثال: `/search رحمت`", parse_mode=ParseMode.MARKDOWN)
        return
    query = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 در حال جستجوی «{query}»...")
    
    try:
        res = requests.get(f"{BASE_API}/search/{query}/all/quran-uthmani", timeout=15).json()
        if res["data"]["count"] == 0:
            await msg.edit_text("❌ هیچ آیه‌ای با این کلمه یافت نشد.")
            return
            
        count = res["data"]["count"]
        ayahs = res["data"]["matches"][:10]
        
        result = f"🔍 **{count} آیه** پیدا شد. (نمایش ۱۰ مورد اول):\n\n"
        for ayah in ayahs:
            result += f"سوره {ayah['surah']['name']} آیه {ayah['numberInSurah']}:\n﴿{ayah['text']}﴾\n\n"
        
        await msg.edit_text(result, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in search_quran: {e}")
        await msg.edit_text("❌ خطا در جستجو.")

# ---------------------------------------------------------------------------
# دستور /ayah (آیه تصادفی)
# ---------------------------------------------------------------------------
async def random_ayah(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("⏳ در حال انتخاب یک آیه برای شما...")
    try:
        random_num = random.randint(1, 6236)
        res = requests.get(f"{BASE_API}/ayah/{random_num}/quran-uthmani,fa.fooladvand", timeout=15).json()
        
        ar = res["data"][0]
        fa = res["data"][1]
        
        result = (
            f"✨ **آیه امروز شما:**\n\n"
            f"﴿{ar['text']}﴾\n\n"
            f"🇮🇷 **ترجمه:**\n{fa['text']}\n\n"
            f"📍 سوره {ar['surah']['name']} - آیه {ar['numberInSurah']}"
        )
        await msg.edit_text(result, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in random_ayah: {e}")
        await msg.edit_text("❌ خطا در دریافت آیه.")

# ---------------------------------------------------------------------------
# اجرای اصلی ربات
# ---------------------------------------------------------------------------
def main() -> None:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("juz", get_juz))
    application.add_handler(CommandHandler("fa", get_fa))
    application.add_handler(CommandHandler("audio", get_audio))
    application.add_handler(CommandHandler("search", search_quran))
    application.add_handler(CommandHandler("ayah", random_ayah))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Quran Bot started successfully!")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
        stop_signals=None,
    )

if __name__ == "__main__":
    main()
