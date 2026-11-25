from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("لطفاً مقادیر زیر را وارد کنید:")
API_ID = int(input("API ID: "))
API_HASH = input("API HASH: ")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\n✅ این کد را کپی کنید و در Secrets گیت‌هاب به نام SESSION_STRING ذخیره کنید:\n")
    print(client.session.save())
