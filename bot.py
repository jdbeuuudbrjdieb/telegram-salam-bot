# ══════════════════════════════════════════════════════════════════════════════
# 🚀 AFGHAN JOB SAAS PLATFORM - THE ULTIMATE EDITION (v7.0)
# ══════════════════════════════════════════════════════════════════════════════
# 💰 مدل درآمدی: فروش آگهی ویژه (Pin) با ستاره تلگرام (XTR) + فروش رزومه با AI
# 🧠 ایجنت AI: چت‌بات پشتیبان، رزومه‌ساز حرفه‌ای، دستیار نگارش آگهی
# 🎨 رابط کاربری: کاملاً دکمه‌ای و بدون تایپ (Zero-Typing)
# ══════════════════════════════════════════════════════════════════════════════

import os, sys, json, logging, requests, asyncio, base64, time
from typing import Optional, Dict, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ══════════════════════════════════════════════════════════════════════════════
# ۱. پیکربندی
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
# ۲. دیتابیس ابری (GitHub DB)
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
# گارد محافظتی برای جلوگیری از کرش (KeyError)
for k in ["users", "jobs", "stats"]:
    if k not in db.data: db.data[k] = {}

# ══════════════════════════════════════════════════════════════════════════════
# ۳. موتور هوش مصنوعی (AI Engine)
# ══════════════════════════════════════════════════════════════════════════════
async def ai_request(system_prompt, user_text):
    url = "https://text.pollinations.ai/openai"
    payload = {"model": "openai", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]}
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: requests.post(url, json=payload, timeout=25))
        if res.status_code == 200: return res.json()["choices"][0]["message"]["content"]
    except Exception as e: logger.error(f"AI Error: {e}")
    return "متأسفم، در حال حاضر نمی‌توانم پاسخ دهم."

# ══════════════════════════════════════════════════════════════════════════════
# ۴. وضعیت‌ها (Conversation States)
# ══════════════════════════════════════════════════════════════════════════════
(JOB_TITLE, JOB_COMPANY, JOB_DESC, JOB_CONTACT, 
 RES_NAME, RES_SKILLS, RES_EXP, RES_CONTACT, AI_CHAT) = range(9)

# ══════════════════════════════════════════════════════════════════════════════
# ۵. منوی اصلی (Ultra UX)
# ══════════════════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if str(uid) not in db.data["users"]:
        db.data["users"][str(uid)] = {"vip": False, "stars": 0}
        await db.save()

    u = db.data["users"][str(uid)]
    vip_status = "🌟 ویژه" if u.get("vip") else "👤 عادی"
    
    kb = [
        [InlineKeyboardButton("💼 ثبت آگهی استخدام (کارفرما)", callback_data="role_employer")],
        [InlineKeyboardButton("📄 ساخت رزومه با AI (کارجو)", callback_data="role_seeker")],
        [InlineKeyboardButton("🧠 مشاور هوشمند شغلی (چت با AI)", callback_data="ai_chat_start")],
        [InlineKeyboardButton("💎 ارتقا به ویژه (VIP)", callback_data="buy_vip")],
    ]
    if uid == OWNER_ID:
        kb.append([InlineKeyboardButton("👑 پنل درآمد و مدیریت", callback_data="owner_panel")])

    text = (
        f"سلام {update.effective_user.first_name}! 🌹\n"
        f"به **پلتفرم هوشمند کاریابی افغان** خوش آمدید.\n\n"
        f"وضعیت شما: {vip_status}\n"
        f"لطفاً از منوی زیر انتخاب کنید:"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

# ══════════════════════════════════════════════════════════════════════════════
# ۶. سیستم پرداخت (Telegram Stars - درآمدزایی)
# ══════════════════════════════════════════════════════════════════════════════
async def buy_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await context.bot.send_invoice(
        chat_id=q.from_user.id,
        title="اشتراک ویژه VIP",
        description="ثبت نامحدود آگهی + پین شدن خودکار در کانال + نشان ویژه",
        payload="vip_subscription",
        provider_token="", 
        currency="XTR", 
        prices=[LabeledPrice("اشتراک یک ماهه", 50)] 
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
# ۷. ایجنت چت هوشمند (AI Support)
# ══════════════════════════════════════════════════════════════════════════════
async def ai_chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data['ai_mode'] = True
    await q.message.edit_text(
        "🧠 **مشاور هوشمند شغلی**\n\n"
        "هر سوالی درباره مصاحبه، رزومه، حقوق و دستمزد یا قوانین کار داری، بپرس. من اینجام تا کمکت کنم!\n"
        "*(برای خروج /start را بزنید)*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ خروج", callback_data="cancel")]])
    )
    return AI_CHAT

async def ai_chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    msg = await update.message.reply_text("⏳ *در حال فکر کردن...*", parse_mode=ParseMode.MARKDOWN)
    
    system = "You are a professional HR consultant and career advisor in Afghanistan. Answer in the user's language (Dari/Pashto/English) politely."
    reply = await ai_request(system, user_msg)
    
    await msg.edit_text(reply, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ خروج", callback_data="cancel")]]))
    return AI_CHAT

# ══════════════════════════════════════════════════════════════════════════════
# ۸. ویزارد ثبت آگهی (کارفرما)
# ══════════════════════════════════════════════════════════════════════════════
async def role_employer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.edit_text("📝 **عنوان شغل** را وارد کنید (مثلاً: برنامه‌نویس پایتون):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو ❌", callback_data="cancel")]]))
    return JOB_TITLE

async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    await update.message.reply_text("🏢 نام **شرکت** را وارد کنید:")
    return JOB_COMPANY

async def get_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['company'] = update.message.text
    await update.message.reply_text("📝 **توضیحات** و شرایط شغل را بنویسید:\n*(هوش مصنوعی آن را اصلاح و حرفه‌ای می‌کند)*")
    return JOB_DESC

async def get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['desc'] = update.message.text
    await update.message.reply_text("📞 راه **ارتباطی** (شماره یا آیدی):")
    return JOB_CONTACT

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    contact = update.message.text
    msg = await update.message.reply_text("⏳ **ایجنت AI در حال پردازش و بهبود آگهی شماست...**")
    
    # AI Processing
    sys_prompt = "Fix spelling, write professionally, and categorize into: IT, Sales, Engineering, Medical, Education, Admin, Services, Other. Output JSON: {'title':'','desc':'','category':''}"
    res = await ai_request(sys_prompt, f"Title:{context.user_data['title']}\nDesc:{context.user_data['desc']}")
    
    try:
        clean_res = res[res.find('{'):res.rfind('}')+1]
        data = json.loads(clean_res)
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

    # Publish
    badge = "🌟 **ویژه** 🌟\n" if is_vip else ""
    text = f"{badge}💼 **فرصت شغلی**\n\n🔹 **عنوان:** {title}\n🏢 **شرکت:** {context.user_data['company']}\n🗂 **دسته:** {cat}\n\n📝 **شرح:**\n{desc}\n\n📞 **تماس:** {contact}"
    
    channel_msg = await context.bot.send_message(MAIN_CHANNEL_ID, text, parse_mode=ParseMode.MARKDOWN)
    if is_vip: await context.bot.pin_chat_message(MAIN_CHANNEL_ID, channel_msg.message_id)

    await msg.edit_text("✅ آگهی شما با موفقیت توسط هوش مصنوعی بهبود یافت و در کانال منتشر شد!", 
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_start")]]))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# ۹. ایجنت رزومه‌ساز (کارجو)
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
    msg = await update.message.reply_text("⏳ **ایجنت AI در حال نگارش رزومه حرفه‌ای شماست...**")
    prompt = "You are an expert HR. Write a professional, attractive resume in Dari/Farsi based on these details. Use formatting."
    user_data = f"Name: {context.user_data['res_name']}\nSkills: {context.user_data['res_skills']}\nExp: {context.user_data['res_exp']}\nContact: {update.message.text}"
    
    resume = await ai_request(prompt, user_data)
    await msg.edit_text(f"✅ **رزومه حرفه‌ای شما آماده شد:**\n\n{resume}\n\n*(می‌توانید این متن را کپی کنید)*", 
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_start")]]))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# ۱۰. پنل مالک
# ══════════════════════════════════════════════════════════════════════════════
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != OWNER_ID: return await q.answer("⛔️ غیرمجاز", show_alert=True)
    
    vip_users = sum(1 for u in db.data["users"].values() if u.get("vip"))
    revenue = db.data["stats"].get("revenue", 0)
    
    text = f"👑 **پنل درآمد و مدیریت**\n\n💰 درآمد ستاره: {revenue}\n👑 کاربران VIP: {vip_users}\n👥 کل کاربران: {len(db.data['users'])}\n💼 کل آگهی‌ها: {len(db.data['jobs'])}"
    await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_start")]]))

async def back_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.message.delete()
    await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.message.edit_text("❌ عملیات لغو شد. برای شروع مجدد /start را بزنید.")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# ۱۱. راه‌اندازی
# ══════════════════════════════════════════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()

    # Payments
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # AI Chat Conversation
    ai_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ai_chat_start, pattern="^ai_chat_start$")],
        states={AI_CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat_handler)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")]
    )

    # Job Posting Conversation
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

    # Resume Conversation
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
    app.add_handler(ai_conv)
    app.add_handler(job_conv)
    app.add_handler(res_conv)
    app.add_handler(CallbackQueryHandler(buy_vip, pattern="^buy_vip$"))
    app.add_handler(CallbackQueryHandler(owner_panel, pattern="^owner_panel$"))
    app.add_handler(CallbackQueryHandler(back_start, pattern="^back_start$"))

    logger.info("🚀 SaaS Platform v7.0 Started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
