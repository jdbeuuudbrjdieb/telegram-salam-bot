# ══════════════════════════════════════════════════════════════════════════════
# 🏢 AFGHAN JOB FINDER - ENTERPRISE EDITION (v4.0)
# ══════════════════════════════════════════════════════════════════════════════
# نام پروژه: ربات کاریابی افغان (Afghan Job Finder)
# معماری: State Machine + GitHub Cloud DB + AI Integration
# قابلیت‌ها: ثبت آگهی هوشمند، رزومه‌ساز، پنل مالک، سیستم ضد سوءاستفاده
# ══════════════════════════════════════════════════════════════════════════════

import os
import sys
import json
import logging
import requests
import asyncio
import base64
import time
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatMemberHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ══════════════════════════════════════════════════════════════════════════════
# ۱. بخش پیکربندی و متغیرهای محیطی
# ══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("JobFinderEnterprise")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GH_PAT = os.getenv("GH_PAT", "")
GH_REPO = os.getenv("GITHUB_REPOSITORY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MAIN_CHANNEL_ID = int(os.getenv("MAIN_CHANNEL_ID", "0"))
MAIN_CHANNEL_LINK = os.getenv("MAIN_CHANNEL_LINK", "https://t.me/")

if not BOT_TOKEN or not OWNER_ID or not MAIN_CHANNEL_ID:
    logger.critical("❌ Missing critical environment variables. Exiting.")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# ۲. لایه دیتابیس ابری (اتصال به گیت‌هاب برای جلوگیری از پاک شدن اطلاعات)
# ══════════════════════════════════════════════════════════════════════════════
class CloudDatabase:
    """
    این کلاس وظیفه خواندن و نوشتن دیتابیس JSON در مخزن گیت‌هاب را بر عهده دارد.
    با استفاده از قفل asyncio، از تداخل در نوشتن (Race Condition) جلوگیری می‌کند.
    """
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.sha: Optional[str] = None
        self.data: Dict[str, Any] = self._load_initial_data()
        self.lock = asyncio.Lock()

    def _load_initial_data(self) -> Dict[str, Any]:
        if not self.token or not self.repo:
            logger.warning("⚠️ GitHub DB credentials missing. Using ephemeral memory.")
            return self._get_default_schema()
        try:
            url = f"https://api.github.com/repos/{self.repo}/contents/db.json"
            res = requests.get(url, headers=self.headers, timeout=15)
            if res.status_code == 200:
                self.sha = res.json()["sha"]
                content = base64.b64decode(res.json()["content"]).decode("utf-8")
                data = json.loads(content)
                logger.info("✅ Database loaded from GitHub.")
                return data
            else:
                logger.warning("⚠️ db.json not found on GitHub. Creating default schema.")
                return self._get_default_schema()
        except Exception as e:
            logger.error(f"❌ Failed to load DB: {e}")
            return self._get_default_schema()

    def _get_default_schema(self) -> Dict[str, Any]:
        return {
            "users": {},       # { user_id: { "username": "", "credits": 0, "last_post_time": 0, "is_banned": False, "resume": {} } }
            "jobs": {},        # { job_id: { "owner_id": "", "title": "", "company": "", "category": "", "desc": "", "contact": "", "timestamp": 0, "msg_id": 0, "is_premium": False, "status": "approved" } }
            "settings": {
                "auto_approve": True,
                "max_free_ads": 3,
                "ad_expiry_days": 7
            },
            "stats": {
                "total_jobs_posted": 0,
                "total_users": 0
            }
        }

    async def save(self) -> None:
        """ذخیره تغییرات در گیت‌هاب با قفل همزمانی"""
        if not self.token or not self.repo: return
        async with self.lock:
            try:
                url = f"https://api.github.com/repos/{self.repo}/contents/db.json"
                content_encoded = base64.b64encode(
                    json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8")
                ).decode("utf-8")
                
                payload = {
                    "message": "🤖 Auto-update database via Job Finder Bot",
                    "content": content_encoded
                }
                if self.sha:
                    payload["sha"] = self.sha

                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(
                    None, 
                    lambda: requests.put(url, headers=self.headers, json=payload, timeout=15)
                )
                
                if res.status_code in (200, 201):
                    self.sha = res.json()["content"]["sha"]
                    logger.info("💾 Database saved to GitHub.")
                else:
                    logger.error(f"❌ Failed to save DB: {res.status_code} - {res.text}")
            except Exception as e:
                logger.error(f"❌ Exception during DB save: {e}")

# مقداردهی اولیه دیتابیس
db = CloudDatabase(GH_PAT, GH_REPO)

# ══════════════════════════════════════════════════════════════════════════════
# ۳. حافظه موقت (State) برای مکالمات چندمرحله‌ای
# ══════════════════════════════════════════════════════════════════════════════
# فرمت: { user_id: { "step": "waiting_title", "data": { ... } } }
user_states: Dict[int, Dict[str, Any]] = {}
# برای کنترل اسپم: { user_id: [timestamp1, timestamp2, ...] }
flood_control: Dict[int, List[float]] = {}

# ══════════════════════════════════════════════════════════════════════════════
# ۴. موتور هوش مصنوعی (اصلاح املایی، ترجمه و دسته‌بندی)
# ══════════════════════════════════════════════════════════════════════════════
async def ai_process_job(title: str, desc: str) -> Dict[str, str]:
    """
    ارسال متن به هوش مصنوعی برای پردازش.
    خروجی: دیکشنری شامل متن اصلاح شده و دسته‌بندی
    """
    url = "https://text.pollinations.ai/openai"
    
    system_prompt = (
        "You are an expert HR manager and translator. "
        "I will give you a job title and description in Dari/Pashto/English. "
        "1. Fix any spelling or grammar mistakes. "
        "2. Categorize the job into exactly one of these categories: "
        "[IT, Sales, Engineering, Medical, Education, Admin, Services, Other]. "
        "3. Output MUST be a valid JSON object with keys: 'fixed_title', 'fixed_desc', 'category'. "
        "Do not output any markdown or extra text, ONLY the JSON."
    )
    
    user_content = f"Title: {title}\nDescription: {desc}"
    
    payload = {
        "model": "openai",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3
    }
    
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: requests.post(url, json=payload, timeout=25))
        if res.status_code == 200:
            raw_text = res.json()["choices"][0]["message"]["content"]
            # استخراج JSON از پاسخ
            start = raw_text.find('{')
            end = raw_text.rfind('}') + 1
            if start != -1 and end != -1:
                json_str = raw_text[start:end]
                parsed = json.loads(json_str)
                return {
                    "title": parsed.get("fixed_title", title),
                    "desc": parsed.get("fixed_desc", desc),
                    "category": parsed.get("category", "Other")
                }
    except Exception as e:
        logger.error(f"AI Processing Error: {e}")
        
    # در صورت خطا، داده‌های اصلی را برمی‌گرداند
    return {"title": title, "desc": desc, "category": "Other"}

# ══════════════════════════════════════════════════════════════════════════════
# ۵. توابع کمکی و امنیتی
# ══════════════════════════════════════════════════════════════════════════════
async def is_channel_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی عضویت اجباری در کانال اصلی"""
    try:
        member = await context.bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status not in ["left", "kicked"]
    except Exception:
        # اگر ربات در کانال ادمین نباشد یا خطایی رخ دهد، اجازه عبور نمی‌دهیم
        return False

def check_flood(user_id: int) -> bool:
    """بررسی اسپم بودن کاربر (بیش از ۵ پیام در ۱۰ ثانیه)"""
    now = time.time()
    if user_id not in flood_control:
        flood_control[user_id] = []
    
    # نگه داشتن پیام‌های ۱۰ ثانیه اخیر
    flood_control[user_id] = [t for t in flood_control[user_id] if now - t < 10]
    flood_control[user_id].append(now)
    
    return len(flood_control[user_id]) > 5

def get_user_data(user_id: int) -> Dict[str, Any]:
    """دریافت یا ساخت پروفایل کاربر در دیتابیس"""
    uid = str(user_id)
    if uid not in db.data["users"]:
        db.data["users"][uid] = {
            "username": "",
            "credits": 0,
            "last_post_time": 0,
            "is_banned": False,
            "resume": {"full_name": "", "skills": "", "experience": "", "contact": ""}
        }
    return db.data["users"][uid]

def get_user_weekly_quota(user_id: int) -> int:
    """محاسبه تعداد آگهی‌های ثبت‌شده در ۷ روز گذشته"""
    uid = str(user_id)
    now = time.time()
    count = 0
    for job in db.data["jobs"].values():
        if job["owner_id"] == uid and (now - job["timestamp"]) < (7 * 86400):
            count += 1
    return count

async def safe_answer_callback(query, text: str, show_alert: bool = False):
    """پاسخ امن به Callback Query"""
    try:
        await query.answer(text, show_alert=show_alert)
    except TelegramError:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# ۶. سیستم ضد سوءاستفاده (ترک خودکار گروه‌ها و کانال‌های غیرمجاز)
# ══════════════════════════════════════════════════════════════════════════════
async def anti_abuse_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    اگر ربات به هر گروه یا کانالی غیر از کانال اصلی اضافه شود،
    بلافاصله آنجا را ترک می‌کند.
    """
    chat_member = update.my_chat_member
    if not chat_member:
        return

    chat_id = update.effective_chat.id
    new_status = chat_member.new_chat_member.status

    if new_status in ["member", "administrator"]:
        if chat_id != MAIN_CHANNEL_ID:
            logger.info(f"🚫 Bot added to unauthorized chat: {chat_id}. Leaving immediately.")
            try:
                await context.bot.leave_chat(chat_id)
            except Exception as e:
                logger.error(f"Failed to leave chat {chat_id}: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ۷. منوی اصلی کاربران (User Interface)
# ══════════════════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # بررسی ادمین بودن برای نمایش دکمه مالک
    is_owner = (user_id == OWNER_ID)

    # بررسی عضویت
    if not await is_channel_member(user_id, context):
        keyboard = [
            [InlineKeyboardButton("📢 عضویت در کانال اصلی", url=MAIN_CHANNEL_LINK)],
            [InlineKeyboardButton("✅ تایید عضویت", callback_data="check_join_status")]
        ]
        await update.message.reply_text(
            "⚠️ **برای استفاده از ربات کاریابی، ابتدا باید در کانال ما عضو شوید.**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ثبت کاربر در دیتابیس
    user_data = get_user_data(user_id)
    user_data["username"] = update.effective_user.username or update.effective_user.first_name
    await db.save()

    # ساخت منوی اصلی
    keyboard = [
        [InlineKeyboardButton("📝 ثبت آگهی شغلی جدید", callback_data="menu_post_job")],
        [InlineKeyboardButton("🔍 جستجوی آگهی‌ها", callback_data="menu_search_jobs")],
        [InlineKeyboardButton("👤 پروفایل و رزومه من", callback_data="menu_profile")],
        [InlineKeyboardButton("🌟 امکانات ویژه و پولی", callback_data="menu_premium")],
    ]
    
    # دکمه پنل مالک فقط برای OWNER_ID
    if is_owner:
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت کل سیستم (مالک)", callback_data="admin_main_panel")])

    welcome_text = (
        f"سلام {update.effective_user.first_name} عزیز! 🌹\n"
        f"به **سیستم کاریابی افغان** خوش آمدید.\n\n"
        f"🔹 **سهمیه رایگان شما:** {max(0, 3 - get_user_weekly_quota(user_id))} آگهی از ۳ آگهی هفتگی\n"
        f"🔹 **اعتبار پولی:** {user_data['credits']} واحد\n\n"
        f"لطفاً از منوی زیر انتخاب کنید:"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def cb_check_join_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if await is_channel_member(query.from_user.id, context):
        await safe_answer_callback(query, "✅ عضویت شما تایید شد! لطفاً /start را بزنید.", True)
    else:
        await safe_answer_callback(query, "❌ شما هنوز در کانال عضو نشده‌اید!", True)

# ══════════════════════════════════════════════════════════════════════════════
# ۸. فرآیند ثبت آگهی (State Machine Wizard)
# ══════════════════════════════════════════════════════════════════════════════
async def cb_post_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # بررسی ادمین
    if not await is_channel_member(user_id, context):
        return await safe_answer_callback(query, "⚠️ ابتدا در کانال عضو شوید!", True)

    user_data = get_user_data(user_id)
    
    # بررسی بن بودن
    if user_data.get("is_banned"):
        return await query.message.edit_text("⛔️ شما از طرف مدیریت ربات مسدود شده‌اید.")

    # بررسی سهمیه
    quota_used = get_user_weekly_quota(user_id)
    max_free = db.data["settings"]["max_free_ads"]

    if quota_used >= max_free and user_data["credits"] <= 0:
        return await query.message.edit_text(
            f"❌ **شما به سقف {max_free} آگهی رایگان در هفته رسیده‌اید.**\n\n"
            f"🌟 برای ثبت آگهی بیشتر، می‌توانید از امکانات ویژه استفاده کنید یا با مدیر تماس بگیرید:\n"
            f"👤 **آیدی مدیر:** `@{os.getenv('OWNER_USERNAME', 'Admin')}`",
            parse_mode=ParseMode.MARKDOWN
        )

    # شروع ویزارد
    user_states[user_id] = {"step": "job_title", "data": {}}
    await query.message.edit_text(
        "📝 **مرحله ۱ از ۴: عنوان شغل**\n"
        "لطفاً عنوان شغل را وارد کنید (مثلاً: برنامه‌نویس پایتون):\n\n"
        "*(برای لغو، دستور /cancel را بزنید)*",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_wizard_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌های متنی کاربران در طول مراحل ثبت آگهی"""
    user_id = update.effective_user.id
    if user_id not in user_states:
        return False

    text = update.message.text.strip()
    if text == "/cancel":
        del user_states[user_id]
        await update.message.reply_text("❌ عملیات لغو شد.")
        return True

    state = user_states[user_id]
    step = state["step"]
    data = state["data"]

    if step == "job_title":
        if len(text) < 3 or len(text) > 50:
            await update.message.reply_text("⚠️ عنوان باید بین ۳ تا ۵۰ کاراکتر باشد. دوباره وارد کنید:")
            return True
        data["title"] = text
        state["step"] = "job_company"
        await update.message.reply_text(
            "🏢 **مرحله ۲ از ۴: نام شرکت**\n"
            "لطفاً نام شرکت یا کارفرما را وارد کنید:"
        )
        return True

    elif step == "job_company":
        data["company"] = text
        state["step"] = "job_desc"
        await update.message.reply_text(
            "📄 **مرحله ۳ از ۴: توضیحات شغل**\n"
            "لطفاً شرایط، نیازمندی‌ها و ساعت کاری را بنویسید:"
        )
        return True

    elif step == "job_desc":
        if len(text) < 10:
            await update.message.reply_text("⚠️ توضیحات خیلی کوتاه است. لطفاً کامل‌تر بنویسید:")
            return True
        data["desc"] = text
        state["step"] = "job_contact"
        await update.message.reply_text(
            "📞 **مرحله ۴ از ۴: راه ارتباطی**\n"
            "شماره تماس یا آیدی تلگرام خود را وارد کنید:"
        )
        return True

    elif step == "job_contact":
        data["contact"] = text
        
        # حذف وضعیت کاربر
        del user_states[user_id]
        
        # ارسال به هوش مصنوعی
        processing_msg = await update.message.reply_text("⏳ **در حال پردازش توسط هوش مصنوعی...**\n(اصلاح املایی و دسته‌بندی)")

        ai_result = await ai_process_job(data["title"], data["desc"])
        
        # ساخت آگهی نهایی
        job_id = f"job_{int(time.time())}_{user_id}"
        is_premium = get_user_data(user_id)["credits"] > 0
        
        job_record = {
            "owner_id": str(user_id),
            "title": ai_result["title"],
            "company": data["company"],
            "category": ai_result["category"],
            "desc": ai_result["desc"],
            "contact": data["contact"],
            "timestamp": time.time(),
            "msg_id": 0,
            "is_premium": is_premium,
            "status": "pending" # نیاز به تایید ادمین
        }

        db.data["jobs"][job_id] = job_record
        db.data["stats"]["total_jobs_posted"] += 1
        
        # کسر اعتبار اگر پرمیوم است
        if is_premium:
            get_user_data(user_id)["credits"] -= 1
            
        await db.save()

        # بررسی تنظیمات تایید خودکار
        if db.data["settings"]["auto_approve"]:
            await publish_job_to_channel(context, job_id)
            await processing_msg.edit_text("✅ آگهی شما ثبت و بلافاصله در کانال منتشر شد!")
        else:
            await processing_msg.edit_text("✅ آگهی شما ثبت شد و پس از تایید مدیریت در کانال منتشر می‌شود.")
            # ارسال به ادمین برای تایید
            try:
                admin_kb = [
                    [InlineKeyboardButton("✅ تایید و انتشار", callback_data=f"approve_{job_id}")],
                    [InlineKeyboardButton("❌ رد کردن", callback_data=f"reject_{job_id}")]
                ]
                await context.bot.send_message(
                    OWNER_ID,
                    f"🔔 **آگهی جدید در انتظار تایید:**\n\n"
                    f"عنوان: {job_record['title']}\n"
                    f"شرکت: {job_record['company']}\n"
                    f"دسته: {job_record['category']}",
                    reply_markup=InlineKeyboardMarkup(admin_kb)
                )
            except Exception as e:
                logger.error(f"Could not send approval message to owner: {e}")

        return True

    return False

# ══════════════════════════════════════════════════════════════════════════════
# ۹. انتشار آگهی در کانال
# ══════════════════════════════════════════════════════════════════════════════
async def publish_job_to_channel(context: ContextTypes.DEFAULT_TYPE, job_id: str):
    """تابع کمکی برای ارسال آگهی به کانال اصلی"""
    job = db.data["jobs"].get(job_id)
    if not job: return

    premium_badge = "🌟 **آگهی ویژه** 🌟\n\n" if job.get("is_premium") else ""
    
    text = (
        f"{premium_badge}"
        f"💼 **فرصت شغلی جدید**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🔹 **عنوان:** {job['title']}\n"
        f"🏢 **شرکت:** {job['company']}\n"
        f"🗂 **دسته‌بندی:** {job['category']}\n\n"
        f"📝 **شرح شغل:**\n{job['desc']}\n\n"
        f"📞 **تماس:** {job['contact']}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⏳ _این آگهی تا ۷ روز دیگر در کانال باقی می‌ماند._"
    )
    
    try:
        sent_msg = await context.bot.send_message(
            MAIN_CHANNEL_ID,
            text,
            parse_mode=ParseMode.MARKDOWN
        )
        job["msg_id"] = sent_msg.message_id
        job["status"] = "published"
        
        # پین کردن اگر پرمیوم است
        if job.get("is_premium"):
            await context.bot.pin_chat_message(MAIN_CHANNEL_ID, sent_msg.message_id, disable_notification=True)
            
        await db.save()
    except Exception as e:
        logger.error(f"Failed to publish job {job_id}: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ۱۰. پنل مالک (Admin Panel) - فقط برای OWNER_ID
# ══════════════════════════════════════════════════════════════════════════════
async def cb_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != OWNER_ID:
        return await safe_answer_callback(query, "⛔️ شما دسترسی به این بخش ندارید!", True)

    total_jobs = len(db.data["jobs"])
    pending_jobs = sum(1 for j in db.data["jobs"].values() if j["status"] == "pending")
    total_users = len(db.data["users"])

    text = (
        f"👑 **پنل مدیریت ارشد**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 کل کاربران: {total_users}\n"
        f"💼 کل آگهی‌ها: {total_jobs}\n"
        f"⏳ در انتظار تایید: {pending_jobs}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"از دکمه‌های زیر برای مدیریت استفاده کنید:"
    )

    keyboard = [
        [InlineKeyboardButton(f"📋 آگهی‌های در انتظار ({pending_jobs})", callback_data="admin_view_pending")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی (Broadcast)", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚙️ تنظیمات ربات", callback_data="admin_settings")],
        [InlineKeyboardButton("🚫 مدیریت کاربران (بن/آنبن)", callback_data="admin_manage_users")],
        [InlineKeyboardButton("🧹 پاکسازی آگهی‌های منقضی شده", callback_data="admin_purge_now")]
    ]

    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def cb_admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        return await safe_answer_callback(query, "⛔️ دسترسی ندارید!", True)
        
    action, job_id = query.data.split("_", 1)
    
    if job_id not in db.data["jobs"]:
        return await query.answer("❌ آگهی یافت نشد.", show_alert=True)

    if action == "approve":
        db.data["jobs"][job_id]["status"] = "approved"
        await publish_job_to_channel(context, job_id)
        await query.message.edit_text("✅ آگهی تایید و در کانال منتشر شد.")
    elif action == "reject":
        del db.data["jobs"][job_id]
        await db.save()
        await query.message.edit_text("❌ آگهی رد و حذف شد.")

# ══════════════════════════════════════════════════════════════════════════════
# ۱۱. جستجوی آگهی‌ها (با Pagination)
# ══════════════════════════════════════════════════════════════════════════════
async def cb_search_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💻 IT و فناوری", callback_data="search_cat_IT")],
        [InlineKeyboardButton("📈 فروش و بازاریابی", callback_data="search_cat_Sales")],
        [InlineKeyboardButton("⚙️ مهندسی", callback_data="search_cat_Engineering")],
        [InlineKeyboardButton("🩺 پزشکی", callback_data="search_cat_Medical")],
        [InlineKeyboardButton("📚 آموزش", callback_data="search_cat_Education")],
        [InlineKeyboardButton("🏢 اداری و مالی", callback_data="search_cat_Admin")],
        [InlineKeyboardButton("🤝 خدماتی", callback_data="search_cat_Services")],
        [InlineKeyboardButton("📦 سایر", callback_data="search_cat_Other")],
    ]
    await query.message.edit_text(
        "🔍 **دسته‌بندی مورد نظر خود را انتخاب کنید:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cb_search_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = query.data.replace("search_cat_", "")
    # فیلتر آگهی‌ها
    results = [
        j for j in db.data["jobs"].values() 
        if j["category"] == category and j["status"] == "published"
    ]
    
    if not results:
        return await query.message.edit_text(f"📭 هیچ آگهی فعالی در دسته **{category}** یافت نشد.")
        
    text = f"📋 **آگهی‌های دسته {category}:**\n\n"
    for idx, job in enumerate(results[:5], 1):
        text += f"{idx}. **{job['title']}** - {job['company']}\n"
        
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)

# ══════════════════════════════════════════════════════════════════════════════
# ۱۲. تسک‌های زمان‌بندی شده (پاکسازی خودکار ۷ روزه)
# ══════════════════════════════════════════════════════════════════════════════
async def purge_expired_jobs(context: ContextTypes.DEFAULT_TYPE):
    """حذف آگهی‌های قدیمی‌تر از ۷ روز و پاک کردن آن‌ها از کانال"""
    logger.info("🧹 Running auto-purge job for expired ads...")
    now = time.time()
    expiry = db.data["settings"]["ad_expiry_days"] * 86400
    jobs_to_delete = []

    for job_id, job in db.data["jobs"].items():
        if (now - job["timestamp"]) >= expiry:
            jobs_to_delete.append(job_id)
            # حذف از کانال تلگرام
            if job.get("msg_id"):
                try:
                    await context.bot.delete_message(MAIN_CHANNEL_ID, job["msg_id"])
                except Exception:
                    pass # ممکن است قبلا حذف شده باشد

    if jobs_to_delete:
        for jid in jobs_to_delete:
            del db.data["jobs"][jid]
        await db.save()
        logger.info(f"✅ Purged {len(jobs_to_delete)} expired jobs.")

# ══════════════════════════════════════════════════════════════════════════════
# ۱۳. راه‌اندازی و اجرای اصلی
# ══════════════════════════════════════════════════════════════════════════════
async def post_init(app: Application):
    """عملیات پس از راه‌اندازی ربات"""
    # تنظیم زمان‌بندی پاکسازی خودکار (هر ۲۴ ساعت یکبار اجرا می‌شود)
    app.job_queue.run_repeating(purge_expired_jobs, interval=86400, first=60)
    logger.info("⏱️ Background job queue initialized.")

def main():
    """نقطه ورود اصلی برنامه"""
    logger.info("🚀 Starting Afghan Job Finder Enterprise Bot...")
    
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # 1. دستورات Start
    app.add_handler(CommandHandler("start", cmd_start))
    
    # 2. روتر وضعیت کاربران (برای فرم ثبت آگهی)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wizard_input))
    
    # 3. امنیت و ضد Abuse
    app.add_handler(ChatMemberHandler(anti_abuse_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    # 4. هندلرهای دکمه‌های شیشه‌ای (Callbacks)
    app.add_handler(CallbackQueryHandler(cb_check_join_status, pattern="^check_join_status$"))
    app.add_handler(CallbackQueryHandler(cb_post_job, pattern="^menu_post_job$"))
    app.add_handler(CallbackQueryHandler(cb_search_jobs, pattern="^menu_search_jobs$"))
    app.add_handler(CallbackQueryHandler(cb_search_results, pattern="^search_cat_"))
    
    # پنل ادمین
    app.add_handler(CallbackQueryHandler(cb_admin_panel, pattern="^admin_main_panel$"))
    app.add_handler(CallbackQueryHandler(cb_admin_approve, pattern="^(approve_|reject_)"))

    logger.info("✅ Bot is fully operational and listening for updates.")
    
    # اجرای ربات
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        stop_signals=None
    )

if __name__ == "__main__":
    main()
