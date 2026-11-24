# ══════════════════════════════════════════════════════════════════════════════
# 🚀 AFGHAN JOB SAAS PLATFORM - AI AGENT & MONETIZATION EDITION (v6.0)
# ══════════════════════════════════════════════════════════════════════════════
# 💰 کسب درآمد: از طریق خرید ستاره تلگرام (برای آگهی ویژه و VIP)
# 🧠 ایجنت هوش مصنوعی: ساخت رزومه کارجو و دستیار نگارش آگهی برای کارفرما
# 🎨 رابط کاربری: کاملاً دکمه‌ای (بدون نیاز به تایپ طولانی)
# ══════════════════════════════════════════════════════════════════════════════

import os, sys, json, logging, requests, asyncio, base64, time
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatMemberHandler, PreCheckoutQueryHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ══════════════════════════════════════════════════════════════════════════════
# ۱. پیکربندی و امنیت
# ══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(message)s", level=logging.INFO)
logger = logging.getLogger("JobSaaS")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GH_PAT = os.getenv("GH_PAT", "")
GH_REPO = os.getenv("GITHUB_REPOSITORY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MAIN_CHANNEL_ID = int(os.getenv("MAIN_CHANNEL_ID", "0"))
MAIN_CHANNEL_LINK = os.getenv("MAIN_CHANNEL_LINK", "")
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "Admin")

# ══════════════════════════════════════════════════════════════════════════════
# ۲. دیتابیس ابری (مغز ربات)
# ══════════════════════════════════════════════════════════════════════════════
class CloudDB:
    def __init__(self, token, repo):
        self.token, self.repo = token, repo
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        self.sha, self.lock = None, asyncio.Lock()
        self.data = self._load()

    def _load(self):
        if not self.token or not self.repo: return self._default()
        try:
            res = requests.get(f"https://api.github.com/repos/{self.repo}/contents/db.json", headers=self.headers, timeout=10)
            if res.status_code == 200:
                self.sha = res.json()["sha"]
                return json.loads(base64.b64decode(res.json()["content"]).decode("utf-8"))
        except Exception: pass
        return self._default()

    def _default(self):
        return {"users": {}, "jobs": {}, "stats": {"revenue": 0}}

    async def save(self):
        if not self.token or not self.repo: return
        async with self.lock:
            try:
                content = base64.b64encode(json.dumps(self.data, ensure_ascii=False).encode()).decode()
                payload = {"message": "DB Sync", "content": content}
                if self.sha: payload["sha"] = self.sha
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, lambda: requests.put(f"https://api.github.com/repos/{self.repo}/contents/db.json", headers=self.headers, json=payload, timeout=10))
                if res.status_code in (200, 201): self.sha = res.json()["content"]["sha"]
            except Exception as e: logger.error(f"DB Save Error: {e}")

db = CloudDB(GH_PAT, GH_REPO)
for k in ["users", "jobs", "stats"]:
    if k not in db.data: db.data[k] = {}

# ══════════════════════════════════════════════════════════════════════════════
# ۳. ایجنت هوش مصنوعی (AI Agent)
# ══════════════════════════════════════════════════════════════════════════════
async def ai_request(system_prompt, user_text):
    url = "https://text.pollinations.ai/openai"
    payload = {"model": "openai", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]}
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: requests.post(url, json=payload, timeout=20))
        if res.status_code == 200: return res.json()["choices"][0]["message"]["content"]
    except Exception as e: logger.error(f"AI Error: {e}")
    return None

# ══════════════════════════════════════════════════════════════════════════════
# ۴. وضعیت‌ها (Conversation States)
# ══════════════════════════════════════════════════════════════════════════════
(ASK_ROLE, JOB_TITLE, JOB_COMPANY, JOB_DESC, JOB_CONTACT, 
 RES_NAME, RES_SKILLS, RES_EXP, RES_CONTACT) = range(9)

# ══════════════════════════════════════════════════════════════════════════════
# ۵. رابط کاربری اصلی (UI)
# ══════════════════════════════════════════════════════════════════════════════
async def is_member(uid, ctx):
    try: return (await ctx.bot.get_chat_member(MAIN_CHANNEL_ID, uid)).status not in ["left", "kicked"]
    except: return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_member(uid, context):
        kb = [[InlineKeyboardButton("📢 عضویت در کانال", url=MAIN_CHANNEL_LINK)], [InlineKeyboardButton("✅ تایید", callback_data="check_join")]]
        return await update.message.reply_text("⚠️ ابتدا در کانال عضو شوید:", reply_markup=InlineKeyboardMarkup(kb))

    if str(uid) not in db.data["users"]:
        db.data["users"][str(uid)] = {"vip": False, "stars": 0}
        await db.save()

    u = db.data["users"][str(uid)]
    vip_status = "🌟 ویژه" if u.get("vip") else "👤 عادی"
    
    kb = [
        [InlineKeyboardButton("💼 ثبت آگهی (کارفرما)", callback_data="role_employer")],
        [InlineKeyboardButton("📄 ساخت رزومه با AI (کارجو)", callback_data="role_seeker")],
        [InlineKeyboardButton("🔍 جستجوی آگهی‌ها", callback_data="search_jobs")],
        [InlineKeyboardButton("💎 خرید اشتراک VIP (ستاره)", callback_data="buy_vip")],
    ]
    if uid == OWNER_ID:
        kb.append([InlineKeyboardButton("👑 پنل مدیریت", callback_data="owner_panel")])

    text = f"سلام {update.effective_user.first_name}! 🌹\nبه پلتفرم هوشمند کاریابی خوش آمدید.\n\nوضعیت شما: {vip_status}"
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if await is_member(q.from_user.id, context):
        await q.answer("✅ تایید شد! لطفا /start را بزنید.", show_alert=True)
    else: await q.answer("❌ هنوز عضو نشده‌اید!", show_alert=True)

# ══════════════════════════════════════════════════════════════════════════════
# ۶. سیستم پرداخت (Telegram Stars) - کسب درآمد!
# ══════════════════════════════════════════════════════════════════════════════
async def buy_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await context.bot.send_invoice(
        chat_id=q.from_user.id,
        title="اشتراک ویژه VIP",
        description="ثبت نامحدود آگهی + پین شدن خودکار + نشان ویژه 🌟",
        payload="vip_subscription",
        provider_token="", # برای ستاره تلگرام خالی است
        currency="XTR", # واحد پول: ستاره تلگرام
        prices=[LabeledPrice("اشتراک یک ماهه", 50)] # ۵۰ ستاره
    )

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid in db.data["users"]:
        db.data["users"][uid]["vip"] = True
        db.data["stats"]["revenue"] += 50
        await db.save()
    await update.message.reply_text("✅ پرداخت موفق! اشتراک VIP شما فعال شد. 🌟")

# ══════════════════════════════════════════════════════════════════════════════
# ۷. ویزارد ثبت آگهی (مخصوص کارفرما)
# ══════════════════════════════════════════════════════════════════════════════
async def role_employer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.edit_text("📝 **عنوان شغل** را وارد کنید (مثلاً: برنامه‌نویس):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو ❌", callback_data="cancel")]]))
    return JOB_TITLE

async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    await update.message.reply_text("🏢 نام **شرکت** را وارد کنید:")
    return JOB_COMPANY

async def get_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['company'] = update.message.text
    await update.message.reply_text("📝 **توضیحات** و شرایط شغل را بنویسید:\n*(هوش مصنوعی آن را اصلاح و دسته‌بندی می‌کند)*")
    return JOB_DESC

async def get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['desc'] = update.message.text
    await update.message.reply_text("📞 راه **ارتباطی** (شماره یا آیدی):")
    return JOB_CONTACT

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    contact = update.message.text
    msg = await update.message.reply_text("⏳ **ایجنت هوش مصنوعی در حال پردازش...**")
    
    # ایجنت اصلاح و دسته‌بندی
    sys_prompt = "Fix spelling and categorize into: IT, Sales, Engineering, Medical, Education, Admin, Services, Other. Output JSON: {'title':'','desc':'','category':''}"
    res = await ai_request(sys_prompt, f"Title:{context.user_data['title']}\nDesc:{context.user_data['desc']}")
    
    try:
        data = json.loads(res[res.find('{'):res.rfind('}')+1])
        title, desc, cat = data.get('title'), data.get('desc'), data.get('category', 'Other')
    except:
        title, desc, cat = context.user_data['title'], context.user_data['desc'], "Other"

    is_vip = db.data["users"].get(uid, {}).get("vip", False)
    job_id = f"job_{int(time.time())}_{uid}"
    
    db.data["jobs"][job_id] = {
        "uid": uid, "title": title, "company": context.user_data['company'],
        "desc": desc, "cat": cat, "contact": contact, "time": time.time(), "vip": is_vip
    }
    await db.save()

    # ارسال به کانال
    badge = "🌟 **ویژه** 🌟\n" if is_vip else ""
    text = f"{badge}💼 **فرصت شغلی**\n🔹 {title}\n🏢 {context.user_data['company']}\n🗂 {cat}\n\n📝 {desc}\n📞 {contact}"
    
    channel_msg = await context.bot.send_message(MAIN_CHANNEL_ID, text, parse_mode=ParseMode.MARKDOWN)
    if is_vip: await context.bot.pin_chat_message(MAIN_CHANNEL_ID, channel_msg.message_id)

    await msg.edit_text("✅ آگهی شما با موفقیت در کانال منتشر شد!")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# ۸. ایجنت ساخت رزومه (مخصوص کارجو)
# ══════════════════════════════════════════════════════════════════════════════
async def role_seeker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.edit_text("📄 **نام و نام خانوادگی** خود را وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو ❌", callback_data="cancel")]]))
    return RES_NAME

async def get_res_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['res_name'] = update.message.text
    await update.message.reply_text("💡 **مهارت‌های** خود را بنویسید (مثلاً: پایتون، طراحی، مدیریت):")
    return RES_SKILLS

async def get_res_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['res_skills'] = update.message.text
    await update.message.reply_text("🏢 **سوابق شغلی** خود را بنویسید:")
    return RES_EXP

async def get_res_exp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['res_exp'] = update.message.text
    await update.message.reply_text("📞 راه **ارتباطی** (شماره یا آیدی):")
    return RES_CONTACT

async def get_res_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ **ایجنت هوش مصنوعی در حال نگارش رزومه شماست...**")
    prompt = "You are an expert HR. Write a professional, attractive resume in Dari/Farsi based on these details. Make it sound impressive."
    user_data = f"Name: {context.user_data['res_name']}\nSkills: {context.user_data['res_skills']}\nExp: {context.user_data['res_exp']}\nContact: {update.message.text}"
    
    resume = await ai_request(prompt, user_data)
    await msg.edit_text(f"✅ **رزومه حرفه‌ای شما آماده شد:**\n\n{resume}\n\n*(می‌توانید این متن را کپی کنید)*")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# ۹. پنل مالک (مخفی از دیگران)
# ══════════════════════════════════════════════════════════════════════════════
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != OWNER_ID: return await q.answer("⛔️ غیرمجاز", show_alert=True)
    
    vip_users = sum(1 for u in db.data["users"].values() if u.get("vip"))
    revenue = db.data["stats"].get("revenue", 0)
    
    text = f"👑 **پنل درآمد و مدیریت**\n\n💰 درآمد ستاره: {revenue}\n👑 کاربران VIP: {vip_users}\n👥 کل کاربران: {len(db.data['users'])}"
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_start")]]))

async def back_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.message.delete()
    await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.edit_text("❌ عملیات لغو شد. برای شروع مجدد /start را بزنید.")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# ۱۰. اجرای اصلی
# ══════════════════════════════════════════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()

    # هندلر پرداخت
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # هندلرهای ثبت آگهی
    job_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(role_employer, pattern="^role_employer$")],
        states={
            JOB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            JOB_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_company)],
            JOB_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_desc)],
            JOB_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    # هندلرهای ساخت رزومه
    res_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(role_seeker, pattern="^role_seeker$")],
        states={
            RES_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_res_name)],
            RES_SKILLS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_res_skills)],
            RES_EXP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_res_exp)],
            RES_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_res_contact)],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(job_conv)
    app.add_handler(res_conv)
    app.add_handler(CallbackQueryHandler(check_join, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(buy_vip, pattern="^buy_vip$"))
    app.add_handler(CallbackQueryHandler(owner_panel, pattern="^owner_panel$"))
    app.add_handler(CallbackQueryHandler(back_start, pattern="^back_start$"))

    logger.info("🚀 SaaS Platform Started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
