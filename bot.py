# ══════════════════════════════════════════════════════════════════════════════
# 🏢 AFGHAN JOB FINDER - ULTIMATE ENTERPRISE EDITION (v5.1 Fixed)
# ══════════════════════════════════════════════════════════════════════════════
# 📌 توضیحات: سیستم‌عامل کاریابی هوشمند با دیتابیس ابری گیت‌هاب
# 🛡️ امنیت: تمامی توکن‌ها از Secrets خوانده می‌شوند (بدون هاردکد)
# 🧠 هوش مصنوعی: اصلاح املایی، دسته‌بندی خودکار
# 👑 مدیریت: پنل اختصاصی مالک (فقط برای OWNER_ID)
# ══════════════════════════════════════════════════════════════════════════════

import os
import sys
import json
import logging
import requests
import asyncio
import base64
import time
from datetime import datetime
from typing import Optional, Dict, List, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatMemberHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

# ══════════════════════════════════════════════════════════════════════════════
# ۱. تنظیمات و متغیرهای محیطی
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
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "Admin")

if not BOT_TOKEN or not OWNER_ID or not MAIN_CHANNEL_ID:
    logger.critical("❌ متغیرهای محیطی ناقص هستند. لطفا Secrets را بررسی کنید.")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# ۲. لایه دیتابیس ابری (GitHub Cloud DB)
# ══════════════════════════════════════════════════════════════════════════════
class CloudDatabase:
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
            return self._get_default_schema()
        try:
            url = f"https://api.github.com/repos/{self.repo}/contents/db.json"
            res = requests.get(url, headers=self.headers, timeout=15)
            if res.status_code == 200:
                self.sha = res.json()["sha"]
                content = base64.b64decode(res.json()["content"]).decode("utf-8")
                return json.loads(content)
            return self._get_default_schema()
        except Exception as e:
            logger.error(f"❌ خطا در خواندن دیتابیس: {e}")
            return self._get_default_schema()

    def _get_default_schema(self) -> Dict[str, Any]:
        return {
            "users": {},
            "jobs": {},
            "settings": {"auto_approve": False, "max_free_ads": 3, "ad_expiry_days": 7},
            "stats": {"total_jobs_posted": 0, "total_users": 0}
        }

    async def save(self) -> None:
        if not self.token or not self.repo: return
        async with self.lock:
            try:
                url = f"https://api.github.com/repos/{self.repo}/contents/db.json"
                content_encoded = base64.b64encode(
                    json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8")
                ).decode("utf-8")
                
                payload = {"message": "🤖 Auto-update DB", "content": content_encoded}
                if self.sha:
                    payload["sha"] = self.sha

                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(
                    None, lambda: requests.put(url, headers=self.headers, json=payload, timeout=15)
                )
                if res.status_code in (200, 201):
                    self.sha = res.json()["content"]["sha"]
            except Exception as e:
                logger.error(f"❌ خطا در ذخیره دیتابیس: {e}")

db = CloudDatabase(GH_PAT, GH_REPO)

# ══════════════════════════════════════════════════════════════════════════════
# ۳. متغیرهای سراسری
# ══════════════════════════════════════════════════════════════════════════════
user_states: Dict[int, Dict[str, Any]] = {}
flood_control: Dict[int, List[float]] = {}

# ══════════════════════════════════════════════════════════════════════════════
# ۴. موتور هوش مصنوعی
# ══════════════════════════════════════════════════════════════════════════════
async def ai_process_job(title: str, desc: str) -> Dict[str, str]:
    url = "https://text.pollinations.ai/openai"
    system_prompt = (
        "You are an expert HR manager. I will give you a job title and description. "
        "1. Fix spelling mistakes. "
        "2. Categorize strictly into: [IT, Sales, Engineering, Medical, Education, Admin, Services, Other]. "
        "3. Output MUST be a valid JSON object with keys: 'fixed_title', 'fixed_desc', 'category'. "
        "Do NOT output any markdown or extra text. ONLY JSON."
    )
    payload = {
        "model": "openai",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Title: {title}\nDescription: {desc}"}
        ],
        "temperature": 0.3
    }
    
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: requests.post(url, json=payload, timeout=25))
        if res.status_code == 200:
            raw_text = res.json()["choices"][0]["message"]["content"]
            start, end = raw_text.find('{'), raw_text.rfind('}') + 1
            if start != -1 and end != -1:
                parsed = json.loads(raw_text[start:end])
                return {
                    "title": parsed.get("fixed_title", title),
                    "desc": parsed.get("fixed_desc", desc),
                    "category": parsed.get("category", "Other")
                }
    except Exception as e:
        logger.error(f"AI Error: {e}")
    return {"title": title, "desc": desc, "category": "Other"}

# ══════════════════════════════════════════════════════════════════════════════
# ۵. توابع کمکی
# ══════════════════════════════════════════════════════════════════════════════
async def is_channel_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status not in ["left", "kicked"]
    except Exception:
        return False

def check_flood(user_id: int) -> bool:
    now = time.time()
    if user_id not in flood_control:
        flood_control[user_id] = []
    flood_control[user_id] = [t for t in flood_control[user_id] if now - t < 10]
    flood_control[user_id].append(now)
    return len(flood_control[user_id]) > 5

def get_user_data(user_id: int) -> Dict[str, Any]:
    uid = str(user_id)
    if uid not in db.data["users"]:
        db.data["users"][uid] = {
            "username": "",
            "credits": 0,
            "is_banned": False,
        }
        db.data["stats"]["total_users"] += 1
    return db.data["users"][uid]

def get_user_weekly_quota(user_id: int) -> int:
    uid = str(user_id)
    now = time.time()
    return sum(1 for job in db.data["jobs"].values() if job["owner_id"] == uid and (now - job["timestamp"]) < (7 * 86400))

async def safe_edit_message(query, text: str, reply_markup=None):
    try:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Edit Message Error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ۶. سیستم ضد سوءاستفاده
# ══════════════════════════════════════════════════════════════════════════════
async def anti_abuse_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.my_chat_member
    if not chat_member: return
    chat_id = update.effective_chat.id
    if chat_member.new_chat_member.status in ["member", "administrator"]:
        if chat_id != MAIN_CHANNEL_ID:
            try: await context.bot.leave_chat(chat_id)
            except: pass

# ══════════════════════════════════════════════════════════════════════════════
# ۷. منوی اصلی
# ══════════════════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await is_channel_member(user_id, context):
        kb = [
            [InlineKeyboardButton("📢 عضویت در کانال اصلی", url=MAIN_CHANNEL_LINK)],
            [InlineKeyboardButton("✅ تایید عضویت", callback_data="check_join")]
        ]
        return await update.message.reply_text("⚠️ برای استفاده از ربات، ابتدا باید در کانال ما عضو شوید:", reply_markup=InlineKeyboardMarkup(kb))

    user_data = get_user_data(user_id)
    user_data["username"] = update.effective_user.username or update.effective_user.first_name
    await db.save()

    quota_left = max(0, db.data["settings"]["max_free_ads"] - get_user_weekly_quota(user_id))

    kb = [
        [InlineKeyboardButton("📝 ثبت آگهی شغلی جدید", callback_data="post_job")],
        [InlineKeyboardButton("🔍 جستجوی آگهی‌ها", callback_data="search_jobs")],
        [InlineKeyboardButton("🌟 امکانات ویژه (پولی)", callback_data="premium")],
    ]
    
    # دکمه پنل مالک فقط برای شخص شما
    if user_id == OWNER_ID:
        kb.append([InlineKeyboardButton("👑 پنل مدیریت (مخصوص مالک)", callback_data="admin_panel")])

    text = (
        f"سلام {update.effective_user.first_name} عزیز! 🌹\n"
        f"به **سیستم کاریابی افغان** خوش آمدید.\n\n"
        f"🔹 **سهمیه رایگان:** {quota_left} از {db.data['settings']['max_free_ads']} آگهی\n"
        f"🔹 **اعتبار پولی:** {user_data['credits']} واحد\n\n"
        f"لطفاً یک گزینه را انتخاب کنید:"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def cb_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if await is_channel_member(query.from_user.id, context):
        await query.answer("✅ عضویت شما تایید شد! لطفاً /start را بزنید.", show_alert=True)
    else:
        await query.answer("❌ شما هنوز در کانال عضو نشده‌اید!", show_alert=True)

# ══════════════════════════════════════════════════════════════════════════════
# ۸. ثبت آگهی
# ══════════════════════════════════════════════════════════════════════════════
async def cb_post_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await is_channel_member(user_id, context):
        return await query.answer("⚠️ ابتدا در کانال عضو شوید!", show_alert=True)

    user_data = get_user_data(user_id)
    if user_data.get("is_banned"):
        return await safe_edit_message(query, "⛔️ شما از طرف مدیریت مسدود شده‌اید.")

    quota_used = get_user_weekly_quota(user_id)
    max_free = db.data["settings"]["max_free_ads"]

    if quota_used >= max_free and user_data["credits"] <= 0:
        return await safe_edit_message(
            query,
            f"❌ **شما به سقف {max_free} آگهی رایگان در هفته رسیده‌اید.**\n\n"
            f"🌟 برای ثبت آگهی بیشتر، با مدیر تماس بگیرید:\n👤 `@{OWNER_USERNAME}`"
        )

    user_states[user_id] = {"step": "title", "data": {}}
    await safe_edit_message(query, "📝 **مرحله ۱ از ۴: عنوان شغل**\nلطفاً عنوان شغل را وارد کنید:\n\n*(برای لغو /cancel را بزنید)*")

async def wizard_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states: return False
    if check_flood(user_id):
        await update.message.reply_text("⚠️ لطفاً کمی آرام‌تر! (ضد اسپم)")
        return True

    text = update.message.text.strip()
    if text == "/cancel":
        del user_states[user_id]
        await update.message.reply_text("❌ عملیات لغو شد.")
        return True

    state = user_states[user_id]
    step, data = state["step"], state["data"]

    if step == "title":
        if len(text) < 3 or len(text) > 50:
            return await update.message.reply_text("⚠️ عنوان باید بین ۳ تا ۵۰ کاراکتر باشد:") or True
        data["title"] = text
        state["step"] = "company"
        await update.message.reply_text("🏢 **مرحله ۲ از ۴: نام شرکت**\nنام شرکت یا کارفرما را وارد کنید:")
        return True

    elif step == "company":
        data["company"] = text
        state["step"] = "desc"
        await update.message.reply_text("📄 **مرحله ۳ از ۴: توضیحات شغل**\nشرایط و نیازمندی‌ها را بنویسید:")
        return True

    elif step == "desc":
        if len(text) < 10:
            return await update.message.reply_text("⚠️ توضیحات خیلی کوتاه است:") or True
        data["desc"] = text
        state["step"] = "contact"
        await update.message.reply_text("📞 **مرحله ۴ از ۴: راه ارتباطی**\nشماره تماس یا آیدی تلگرام را وارد کنید:")
        return True

    elif step == "contact":
        data["contact"] = text
        del user_states[user_id]
        
        msg = await update.message.reply_text("⏳ **هوش مصنوعی در حال پردازش متن شماست...**")
        ai_res = await ai_process_job(data["title"], data["desc"])
        
        job_id = f"job_{int(time.time())}_{user_id}"
        is_premium = get_user_data(user_id)["credits"] > 0
        
        job_record = {
            "owner_id": str(user_id),
            "title": ai_res["title"],
            "company": data["company"],
            "category": ai_res["category"],
            "desc": ai_res["desc"],
            "contact": data["contact"],
            "timestamp": time.time(),
            "msg_id": 0,
            "is_premium": is_premium,
            "status": "pending"
        }
        
        db.data["jobs"][job_id] = job_record
        db.data["stats"]["total_jobs_posted"] += 1
        if is_premium: get_user_data(user_id)["credits"] -= 1
        await db.save()

        if db.data["settings"]["auto_approve"]:
            await publish_job(context, job_id)
            await msg.edit_text("✅ آگهی ثبت و منتشر شد!")
        else:
            await msg.edit_text("✅ آگهی ثبت شد و پس از تایید مدیر منتشر می‌شود.")
            kb = [
                [InlineKeyboardButton("✅ تایید", callback_data=f"approve_{job_id}")],
                [InlineKeyboardButton("❌ رد", callback_data=f"reject_{job_id}")]
            ]
            try:
                await context.bot.send_message(
                    OWNER_ID, 
                    f"🔔 **آگهی جدید:**\n{job_record['title']} - {job_record['company']}",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            except: pass
        return True
    return False

# ══════════════════════════════════════════════════════════════════════════════
# ۹. انتشار در کانال
# ══════════════════════════════════════════════════════════════════════════════
async def publish_job(context: ContextTypes.DEFAULT_TYPE, job_id: str):
    job = db.data["jobs"].get(job_id)
    if not job: return
    badge = "🌟 **آگهی ویژه** 🌟\n\n" if job.get("is_premium") else ""
    text = (
        f"{badge}💼 **فرصت شغلی جدید**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🔹 **عنوان:** {job['title']}\n"
        f"🏢 **شرکت:** {job['company']}\n"
        f"🗂 **دسته:** {job['category']}\n\n"
        f"📝 **شرح:**\n{job['desc']}\n\n"
        f"📞 **تماس:** {job['contact']}"
    )
    try:
        msg = await context.bot.send_message(MAIN_CHANNEL_ID, text, parse_mode=ParseMode.MARKDOWN)
        job["msg_id"], job["status"] = msg.message_id, "published"
        if job.get("is_premium"):
            await context.bot.pin_chat_message(MAIN_CHANNEL_ID, msg.message_id, disable_notification=True)
        await db.save()
    except Exception as e:
        logger.error(f"Publish Error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ۱۰. پنل مالک
# ══════════════════════════════════════════════════════════════════════════════
async def cb_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        return await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)

    pending = sum(1 for j in db.data["jobs"].values() if j["status"] == "pending")
    text = (
        f"👑 **پنل مدیریت ارشد**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 کاربران: {len(db.data['users'])}\n"
        f"💼 کل آگهی‌ها: {len(db.data['jobs'])}\n"
        f"⏳ در انتظار تایید: {pending}\n"
    )
    kb = [
        [InlineKeyboardButton(f"📋 آگهی‌های در انتظار ({pending})", callback_data="admin_pending")],
        [InlineKeyboardButton("⚙️ تنظیمات ربات", callback_data="admin_settings")],
        [InlineKeyboardButton("🧹 پاکسازی دستی آگهی‌ها", callback_data="admin_purge")]
    ]
    await safe_edit_message(query, text, InlineKeyboardMarkup(kb))

async def cb_admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID: return
    action, job_id = query.data.split("_", 1)
    
    if job_id not in db.data["jobs"]:
        return await query.answer("❌ یافت نشد.", show_alert=True)
        
    if action == "approve":
        db.data["jobs"][job_id]["status"] = "approved"
        await publish_job(context, job_id)
        await query.message.edit_text("✅ تایید و منتشر شد.")
    elif action == "reject":
        del db.data["jobs"][job_id]
        await db.save()
        await query.message.edit_text("❌ رد و حذف شد.")

async def cb_admin_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID: return
    await query.answer()
    
    pending_jobs = [(jid, j) for jid, j in db.data["jobs"].items() if j["status"] == "pending"]
    if not pending_jobs:
        return await safe_edit_message(query, "📭 هیچ آگهی در انتظاری وجود ندارد.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))
        
    jid, job = pending_jobs[0]
    text = (
        f"⏳ **آگهی در انتظار:**\n\n"
        f"🔹 {job['title']}\n"
        f"🏢 {job['company']}\n"
        f"📝 {job['desc'][:100]}...\n"
        f"📞 {job['contact']}"
    )
    kb = [
        [InlineKeyboardButton("✅ تایید", callback_data=f"approve_{jid}"), InlineKeyboardButton("❌ رد", callback_data=f"reject_{jid}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
    ]
    await safe_edit_message(query, text, InlineKeyboardMarkup(kb))

async def cb_admin_purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID: return
    await query.answer("در حال پاکسازی...")
    await purge_expired_jobs(context.bot, force=True)
    await safe_edit_message(query, "✅ پاکسازی انجام شد.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))

# ══════════════════════════════════════════════════════════════════════════════
# ۱۱. جستجوی آگهی‌ها
# ══════════════════════════════════════════════════════════════════════════════
async def cb_search_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("💻 IT", callback_data="cat_IT"), InlineKeyboardButton("📈 فروش", callback_data="cat_Sales")],
        [InlineKeyboardButton("⚙️ مهندسی", callback_data="cat_Engineering"), InlineKeyboardButton("🩺 پزشکی", callback_data="cat_Medical")],
        [InlineKeyboardButton("📚 آموزش", callback_data="cat_Education"), InlineKeyboardButton("🏢 اداری", callback_data="cat_Admin")],
        [InlineKeyboardButton("🤝 خدماتی", callback_data="cat_Services"), InlineKeyboardButton("📦 سایر", callback_data="cat_Other")],
    ]
    await safe_edit_message(query, "🔍 **دسته‌بندی مورد نظر را انتخاب کنید:**", InlineKeyboardMarkup(kb))

async def cb_search_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("cat_", "")
    results = [j for j in db.data["jobs"].values() if j["category"] == cat and j["status"] == "published"]
    
    if not results:
        return await safe_edit_message(query, f"📭 در دسته {cat} آگهی فعالی نیست.")
        
    text = f"📋 **آگهی‌های {cat}:**\n\n"
    for idx, j in enumerate(results[:5], 1):
        text += f"{idx}. {j['title']} - {j['company']}\n"
    await safe_edit_message(query, text)

# ══════════════════════════════════════════════════════════════════════════════
# ۱۲. پاکسازی خودکار (بدون نیاز به JobQueue)
# ══════════════════════════════════════════════════════════════════════════════
async def purge_expired_jobs(bot, force=False):
    now = time.time()
    expiry = db.data["settings"]["ad_expiry_days"] * 86400
    to_delete = []

    for jid, j in db.data["jobs"].items():
        if force or (now - j["timestamp"]) >= expiry:
            to_delete.append(jid)
            if j.get("msg_id"):
                try: await bot.delete_message(MAIN_CHANNEL_ID, j["msg_id"])
                except: pass

    for jid in to_delete:
        del db.data["jobs"][jid]
    if to_delete: await db.save()

async def background_purger(bot):
    """تایمر پس‌زمینه برای پاکسازی خودکار هر ۲۴ ساعت"""
    await asyncio.sleep(60) # اجرای اول پس از ۱ دقیقه
    while True:
        try:
            await purge_expired_jobs(bot)
        except Exception as e:
            logger.error(f"Auto Purge Error: {e}")
        await asyncio.sleep(86400) # ۲۴ ساعت

# ══════════════════════════════════════════════════════════════════════════════
# ۱۳. راه‌اندازی نهایی
# ══════════════════════════════════════════════════════════════════════════════
async def post_init(app: Application):
    # راه‌اندازی تایمر با asyncio (کاملاً مستقل از JobQueue)
    asyncio.create_task(background_purger(app.bot))
    logger.info("⏱️ تایمر پاکسازی خودکار فعال شد.")

def main():
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_router))
    app.add_handler(ChatMemberHandler(anti_abuse_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(CallbackQueryHandler(cb_check_join, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(cb_post_job, pattern="^post_job$"))
    app.add_handler(CallbackQueryHandler(cb_search_jobs, pattern="^search_jobs$"))
    app.add_handler(CallbackQueryHandler(cb_search_results, pattern="^cat_"))
    
    app.add_handler(CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(cb_admin_pending, pattern="^admin_pending$"))
    app.add_handler(CallbackQueryHandler(cb_admin_purge, pattern="^admin_purge$"))
    app.add_handler(CallbackQueryHandler(cb_admin_approve, pattern="^(approve_|reject_)"))

    logger.info("🚀 ربات کاریابی افغان با موفقیت استارت شد!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
