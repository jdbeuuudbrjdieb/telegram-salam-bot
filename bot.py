import os
import re
import sys
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("salam-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN missing")
    sys.exit(1)

SALAM_PATTERN = re.compile(
    r"^\s*(?:سلام+|س+لام+|الس?لام\s*علیکم|سلام\s*علیکم|hi|hello)\s*[!.،,❤️🙏😊]*\s*$",
    flags=re.IGNORECASE | re.UNICODE,
)
REPLY_TEXT = "علیکم السلام 🌹"


async def handle_message(update: Update, context) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        return
    if msg.from_user and msg.from_user.is_bot:
        return
    if SALAM_PATTERN.match(msg.text):
        try:
            await msg.reply_text(
                REPLY_TEXT,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=msg.message_id,
                allow_sending_without_reply=True,
            )
            logger.info("replied | chat=%s", update.effective_chat.id)
        except Exception as exc:
            logger.exception("error: %s", exc)


def main() -> None:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    logger.info("bot started")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
        stop_signals=None,
    )


if __name__ == "__main__":
    main()
