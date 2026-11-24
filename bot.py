import os
import sys
import json
import logging
import requests
import asyncio
import base64
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ═══════════════════════════════════════════════════════════════════════
# ۱. تنظیمات و دیتابیس ابری گیت‌هاب
# ═══════════════════════════════════════════════════════════════════════
logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(message)s", level=logging.INFO)
logger = logging.getLogger("AgentOS-Autonomous")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GH_PAT = os.getenv("GH_PAT", "")
GH_REPO = os.getenv("GITHUB_REPOSITORY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not BOT_TOKEN:
    sys.exit("BOT_TOKEN یافت نشد.")

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
                payload = {"message": "Auto OS", "content": content}
                if self.sha: payload["sha"] = self.sha
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, lambda: requests.put(url, headers=self.headers, json=payload, timeout=10))
                if res.status_code in (200, 201): self.sha = res.json()["content"]["sha"]
            except Exception as e: logger.error(f"DB Save: {e}")

db = GitHubDB(GH_PAT, GH_REPO)
if "agents" not in db.data: db.data["agents"] = {}
if "bots" not in db.data: db.data["bots"] = {}

user_states = {}
active_bots = {}

# ═══════════════════════════════════════════════════════════════════════
# ۲. موتور هوش مصنوعی بدون کلید (Keyless AI)
# ═══════════════════════════════════════════════════════════════════════
async def ask_ai(system_prompt: str, user_msg: str) -> str:
    """اتصال به سرور رایگان و بدون کلید Pollinations (با پشتیبانی از System Prompt)"""
    url = "https://text.pollinations.ai/openai"
    payload = {
        "model": "openai", # استفاده از بهترین مدل موجود در سرور
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ]
    }
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: requests.post(url, json=payload, timeout=30))
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
        return f"⚠️ سرور شلوغ است. لطفاً چند لحظه بعد دوباره تلاش کنید. (کد {res.status_code})"
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return "❌ خطا در ارتباط با سرور هوش مصنوعی."

# ═══════════════════════════════════════════════════════════════════════
# ۳. دستورات ربات مادر
# ═══════════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 **به سیستم‌عامل خودمختار (Autonomous Agent OS) خوش آمدید**\n\n"
        "من یک مادرِ تمام‌عیار هستم. بدون نیاز به هیچ تنظیمات پیچیده‌ای، برای شما ایجنت می‌سازم و ربات‌های فرزند را روشن می‌کنم.\n\n"
        "🧠 **ایجنت‌ها:**\n"
        "`/newagent` - ساخت شخصیت جدید\n"
        "`/myagents` - لیست ایجنت‌ها\n"
        "`/ask <نام> <سوال>` - صحبت با ایجنت\n\n"
        "🤖 **ساخت ربات زیرمجموعه:**\n"
        "`/newbot` - روشن کردن ربات تلگرام جدید با هوش مصنوعی\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def new_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.effective_user.id] = {"step": "agent_name"}
    await update.message.reply_text("📝 **مرحله ۱ از ۲:**\nیک نام انگلیسی برای ایجنت خود انتخاب کنید (مثلاً `SalesBot`):")

async def list_agents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    my_agents = [name for name, data in db.data["agents"].items() if data["owner"] == user_id]
    if not my_agents: return await update.message.reply_text("📭 شما هنوز ایجنتی نساخته‌اید.")
    await update.message.reply_text("🧠 **ایجنت‌های شما:**\n\n" + "\n".join([f"🔹 `{a}`" for a in my_agents]), parse_mode=ParseMode.MARKDOWN)

async def ask_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return await update.message.reply_text("⚠️ `/ask Name سوال شما`")
    agent_name, question = context.args[0], " ".join(context.args[1:])
    if agent_name not in db.data["agents"]: return await update.message.reply_text("❌ ایجنت پیدا نشد.")
    
    msg = await update.message.reply_text("⏳ در حال پردازش...")
    answer = await ask_ai(db.data["agents"][agent_name]["prompt"], question)
    await msg.edit_text(f"🤖 **{agent_name}:**\n\n{answer}", parse_mode=ParseMode.MARKDOWN)

async def new_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.effective_user.id] = {"step": "bot_token"}
    await update.message.reply_text("🤖 **مرحله ۱ از ۲ (ساخت ربات):**\nتوکن ربات جدید خود را از `@BotFather` بگیرید و اینجا بفرستید:")

# ═══════════════════════════════════════════════════════════════════════
# ۴. کارخانه ساخت ربات فرزند (Sub-Bot Factory)
# ═══════════════════════════════════════════════════════════════════════
async def run_child_bot(token, agent_name, owner_id):
    try:
        app = Application.builder().token(token).build()
        
        async def child_handler(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if not upd.effective_message or not upd.effective_message.text: return
            user_text = upd.effective_message.text
            prompt = db.data["agents"].get(agent_name, {}).get("prompt", "تو یک دستیار مودب هستی.")
            reply = await ask_ai(prompt, user_text)
            await upd.effective_message.reply_text(reply)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, child_handler))
        
        await app.initialize()
        await app.updater.start_polling(drop_pending_updates=True)
        await app.start()
        
        active_bots[owner_id] = app
        logger.info(f"Sub-bot for {agent_name} started successfully.")
    except Exception as e:
        logger.error(f"Failed to start sub-bot: {e}")

# ═══════════════════════════════════════════════════════════════════════
# ۵. روتر وضعیت (Wizard Router)
# ═══════════════════════════════════════════════════════════════════════
async def handle_states(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states: return False

    state = user_states[user_id]
    text = update.message.text.strip()

    if state["step"] == "agent_name":
        if text in db.data["agents"]:
            await update.message.reply_text("⚠️ این نام تکراری است. نام دیگری بفرستید:")
            return True
        state["name"] = text
        state["step"] = "agent_prompt"
        await update.message.reply_text("🧠 **مرحله ۲ از ۲:**\nدستورات (System Prompt) خود را بفرستید.\nمثال: `تو یک مشاور فروش هستی.`")
        return True

    elif state["step"] == "agent_prompt":
        name, prompt = state["name"], text
        db.data["agents"][name] = {"owner": user_id, "prompt": prompt, "created": str(datetime.now())}
        await db.save()
        del user_states[user_id]
        await update.message.reply_text(f"✅ ایجنت `{name}` ساخته شد!\nتست: `/ask {name} سلام`", parse_mode=ParseMode.MARKDOWN)
        return True

    elif state["step"] == "bot_token":
        if ":" not in text:
            await update.message.reply_text("❌ توکن نامعتبر است.")
            return True
        state["token"] = text
        state["step"] = "bot_agent"
        await update.message.reply_text("🧠 **مرحله ۲ از ۲:**\nنام ایجنتی که می‌خواهید این ربات از آن استفاده کند را بفرستید:")
        return True

    elif state["step"] == "bot_agent":
        agent_name = text
        if agent_name not in db.data["agents"]:
            await update.message.reply_text("❌ این ایجنت وجود ندارد. اول با `/newagent` بسازید:")
            return True
        
        msg = await update.message.reply_text("⏳ در حال روشن کردن ربات فرزند...")
        token = state["token"]
        
        asyncio.create_task(run_child_bot(token, agent_name, user_id))
        
        user_id_str = str(user_id)
        if user_id_str not in db.data["bots"]: db.data["bots"][user_id_str] = []
        db.data["bots"][user_id_str].append({"token": token, "agent": agent_name})
        await db.save()
        
        del user_states[user_id]
        await msg.edit_text(f"✅ ربات با موفقیت با شخصیت `{agent_name}` روشن شد!\nحالا به ربات خود پیام دهید.")
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════
# ۶. استارت آپ
# ═══════════════════════════════════════════════════════════════════════
async def post_init(app: Application):
    logger.info("Restarting previous child bots...")
    for owner_id_str, bots in db.data.get("bots", {}).items():
        for b in bots:
            asyncio.create_task(run_child_bot(b["token"], b["agent"], int(owner_id_str)))
            await asyncio.sleep(1)

def main():
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newagent", new_agent))
    app.add_handler(CommandHandler("myagents", list_agents))
    app.add_handler(CommandHandler("ask", ask_agent))
    app.add_handler(CommandHandler("newbot", new_bot))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_states))

    logger.info("🚀 Autonomous Agent OS v3.0 Started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
