import os
import sys
import logging
import requests
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(message)s", level=logging.INFO)
logger = logging.getLogger("quran-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    sys.exit(1)

# ----------------- API های معتبر جهانی -----------------
BASE_API = "https://api.alquran.cloud/v1"
AUDIO_API = "https://api.alquran.cloud/v1/edition?format=audio&language=ar&type=versebyverse"

# ----------------- دستورات اصلی -----------------

async def start(update: Update, context) -> None:
    user_name = update.effective_user.first_name if update.effective_user else "کاربر"
    welcome_text = (
        f"سلام {user_name} عزیز 🌹\n"
        "به **ربات قرآن‌یار** خوش آمدید.\n\n"
        "🔹 /juz [شماره] : دریافت متن کامل جزئ (۱ تا ۳۰)\n"
        "🔹 /audio [شماره] : دریافت صوت جزئ\n"
        "🔹 /fa [شماره] : دریافت جزئ به همراه ترجمه فارسی\n"
        "🔹 /search [کلمه] : جستجو در کل قرآن\n"
        "🔹 /ayah : دریافت یک آیه تصادفی برای آرامش\n"
        "🔹 /help : راهنمای کامل"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context) -> None:
    help_text = (
        "📖 **راهنمای ربات قرآن‌یار:**\n\n"
        "برای دریافت متن: `/juz 1`\n"
        "برای دریافت صوت: `/audio 1`\n"
        "برای ترجمه فارسی: `/fa 1`\n"
        "برای جستجو: `/search صبر`\n"
        "برای آیه تصادفی: `/ayah`\n\n"
        "⚠️ به دلیل محدودیت تلگرام، متن جزئ به صورت تکه‌های ۵ آیه‌ای ارسال می‌شود."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def get_juz(update: Update, context) -> None:
    try:
        juz_num = int(context.args[0])
        if juz_num < 1 or juz_num > 30:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ لطفاً شماره جزئ را بین ۱ تا ۳۰ وارد کنید. مثال: `/juz 1`", parse_mode=ParseMode.MARKDOWN)
        return

    msg = await update.message.reply_text(f"⏳ در حال دریافت جزئ {juz_num} از سرورهای معتبر...")
    
    try:
        res = requests.get(f"{BASE_API}/juz/{juz_num}/quran-uthmani").json()
        if res["code"] != 200:
            raise Exception("خطا در دریافت")
        
        ayahs = res["data"]["ayahs"]
        await msg.edit_text(f"📖 **جزئ {juz_num} (متن عثمانی)**\n\n")
        
        # ارسال تکه تکه برای جلوگیری از خطای طولانی بودن متن
        chunk = ""
        for ayah in ayahs:
            chunk += f"﴿{ayah['text']}﴾ ({ayah['numberInSurah']})\n"
            if len(chunk) > 3000:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                chunk = ""
        if chunk:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            
    except Exception as e:
        await msg.edit_text("❌ متأسفانه در دریافت اطلاعات خطایی رخ داد. لطفاً دوباره تلاش کنید.")

async def get_audio(update: Update, context) -> None:
    try:
        juz_num = int(context.args[0])
        if juz_num < 1 or juz_num > 30:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ لطفاً شماره جزئ را بین ۱ تا ۳۰ وارد کنید. مثال: `/audio 1`")
        return
        
    msg = await update.message.reply_text(f"⏳ در حال دریافت صوت جزئ {juz_num}...")
    try:
        # دریافت اطلاعات سوره اول جزئ برای پیدا کردن لینک صوت
        res = requests.get(f"{BASE_API}/juz/{juz_num}/quran-uthmani").json()
        surah_num = res["data"]["ayahs"][0]["surah"]["number"]
        
        # استفاده از قاری مشهور (مثلا مشاری العفاسی)
        audio_res = requests.get(f"{BASE_API}/surah/{surah_num}/ar.alafasy").json()
        audio_url = audio_res["data"]["ayahs"][0]["audio"]
        
        # چون صوت کل جزئ یکجا موجود نیست، لینک صوت سوره اول را می‌فرستیم
        await msg.edit_text(f"🎧 صوت جزئ {juz_num} (شروع از سوره {res['data']['ayahs'][0]['surah']['name']})")
        await update.message.reply_audio(audio=audio_url, title=f"Juz {juz_num}")
    except Exception:
        await msg.edit_text("❌ خطا در دریافت صوت.")

async def get_fa(update: Update, context) -> None:
    try:
        juz_num = int(context.args[0])
        if juz_num < 1 or juz_num > 30:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ مثال: `/fa 1`")
        return
        
    msg = await update.message.reply_text(f"⏳ در حال دریافت جزئ {juz_num} با ترجمه فارسی...")
    try:
        res = requests.get(f"{BASE_API}/juz/{juz_num}/quran-uthmani,fa.fooladvand").json()
        ayahs = res["data"]["ayahs"]
        await msg.edit_text(f"📖 **جزئ {juz_num} (متن + ترجمه)**\n\n")
        
        chunk = ""
        for i in range(0, len(ayahs), 2):
            ar = ayahs[i]
            fa = ayahs[i+1]
            chunk += f"﴿{ar['text']}﴾\n🇮🇷 {fa['text']}\n\n"
            if len(chunk) > 3000:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                chunk = ""
        if chunk:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await msg.edit_text("❌ خطا در دریافت ترجمه.")

async def search_quran(update: Update, context) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ مثال: `/search رحمت`")
        return
    query = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 در حال جستجوی «{query}» در کل قرآن...")
    try:
        res = requests.get(f"{BASE_API}/search/{query}/all/quran-uthmani").json()
        if res["data"]["count"] == 0:
            await msg.edit_text("❌ هیچ آیه‌ای با این کلمه یافت نشد.")
            return
            
        count = res["data"]["count"]
        ayahs = res["data"]["matches"][:10]  # فقط ۱۰ نتیجه اول
        
        result = f"🔍 **{count} آیه** پیدا شد. (نمایش ۱۰ مورد اول):\n\n"
        for ayah in ayahs:
            result += f"سوره {ayah['surah']['name']} آیه {ayah['numberInSurah']}:\n﴿{ayah['text']}﴾\n\n"
        
        await msg.edit_text(result, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await msg.edit_text("❌ خطا در جستجو.")

async def random_ayah(update: Update, context) -> None:
    msg = await update.message.reply_text("⏳ در حال انتخاب یک آیه برای شما...")
    try:
        random_ayah_num = random.randint(1, 6236)
        res = requests.get(f"{BASE_API}/ayah/{random_ayah_num}/quran-uthmani,fa.fooladvand").json()
        ar = res["data"][0]
        fa = res["data"][1]
        
        result = (
            f"✨ **آیه امروز شما:**\n\n"
            f"﴿{ar['text']}﴾\n\n"
            f"🇮🇷 **ترجمه:**\n{fa['text']}\n\n"
            f"📍 سوره {ar['surah']['name']} - آیه {ar['numberInSurah']}"
        )
        await msg.edit_text(result, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await msg.edit_text("❌ خطا در دریافت آیه.")

def main() -> None:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("juz", get_juz))
    application.add_handler(CommandHandler("audio", get_audio))
    application.add_handler(CommandHandler("fa", get_fa))
    application.add_handler(CommandHandler("search", search_quran))
    application.add_handler(CommandHandler("ayah", random_ayah))
    
    # برای اینکه ربات در گروه‌ها هم به دستورات پاسخ دهد
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: None))
    
    logger.info("Quran Bot started successfully!")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
        stop_signals=None,
    )

if __name__ == "__main__":
    main()
