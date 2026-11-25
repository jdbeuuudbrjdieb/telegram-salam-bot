import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.errors import FloodWaitError

# ══════════════════════════════════════════════════════════════════════════════
# ۱. تنظیمات لاگ
# ══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("UserBotClock")

# ══════════════════════════════════════════════════════════════════════════════
# ۲. خواندن اطلاعات امن از Secrets
# ══════════════════════════════════════════════════════════════════════════════
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
BASE_NAME = os.getenv("BASE_NAME", "My Name")

if not API_ID or not API_HASH or not SESSION_STRING:
    logger.error("❌ متغیرهای محیطی (API_ID, API_HASH, SESSION_STRING) یافت نشدند.")
    exit(1)

# ساعت افغانستان (UTC + 4:30)
AFGHAN_TZ = timezone(timedelta(hours=4, minutes=30))

# ══════════════════════════════════════════════════════════════════════════════
# ۳. تابع اصلی آپدیت پروفایل
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    logger.info("🚀 در حال اتصال به تلگرام...")
    
    # ساخت کلاینت با Session String (بدون نیاز به کد تایید)
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("❌ سشن منقضی شده است. لطفاً SESSION_STRING جدید بسازید.")
        return

    logger.info("✅ اتصال برقرار شد. شروع فرآیند به‌روزرسانی ساعت...")

    while True:
        try:
            # محاسبه زمان دقیق افغانستان
            now = datetime.now(AFGHAN_TZ)
            time_str = now.strftime("%H:%M")  # فرمت ساعت:دقیقه
            
            # ساخت نام جدید (حداکثر ۶۴ کاراکتر در تلگرام)
            # فرمت: 🕒 12:30 | Ali
            new_name = f"🕒 {time_str} | {BASE_NAME}"
            
            # آپدیت پروفایل
            await client(UpdateProfileRequest(first_name=new_name[:64]))
            logger.info(f"✅ نام پروفایل به '{new_name}' تغییر یافت.")
            
        except FloodWaitError as e:
            logger.warning(f"⚠️ محدودیت تلگرام. باید {e.seconds} ثانیه صبر کنیم.")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"❌ خطای غیرمنتظره: {e}")
            
        # صبر تا دقیقه بعد (با احتساب ثانیه‌های طی شده)
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 خاموش شدن ربات.")
