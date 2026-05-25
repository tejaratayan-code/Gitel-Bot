from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pathlib import Path
import os
import requests
import asyncio
from asyncio import Lock
import py7zr
import secrets
import time
import random
import pymysql
import threading
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
import subprocess

load_dotenv()

# ====================== تنظیمات ======================
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BALE_TOKEN = os.getenv("BALE_TOKEN", "")
BALE_BOT_USERNAME = os.getenv("BALE_BOT_USERNAME", "")
BALE_USER_ID = int(os.getenv("BALE_USER_ID", 0))
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
BASE_URL = os.getenv("BASE_URL", "https://tapi.bale.ai/bot")

BASE_DIR = Path(__file__).parent
DOWNLOADS_PATH = BASE_DIR / "Downloads"
DOWNLOADS_PATH.mkdir(exist_ok=True)

DAILY_LIMIT = 1024 * 1024 * 1024
DANGEROUS_EXT = {'.php', '.phtml', '.html', '.htm', '.js', '.exe', '.bat', '.sh', '.py', '.pl', '.cgi', '.jsp', '.asp'}

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", ""),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", ""),
}

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "tejaratayan-code")
GITHUB_REPO = os.getenv("GITHUB_REPO", "BaleTelobot")
GITHUB_API = "https://api.github.com"

LOCAL_REPO_PATH = BASE_DIR / "local_repo"

upload_lock = Lock()
app = Client("large_file_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

cancel_flags = {}

def get_db():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)

def init_database():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS connections (
                    telegram_id BIGINT PRIMARY KEY,
                    bale_id BIGINT,
                    connected BOOLEAN DEFAULT FALSE,
                    daily_uploaded BIGINT DEFAULT 0,
                    total_uploaded BIGINT DEFAULT 0,
                    file_count BIGINT DEFAULT 0,
                    last_reset_date DATE,
                    github_token TEXT,
                    github_repo VARCHAR(255) DEFAULT 'GitelUpload',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("SHOW COLUMNS FROM connections")
            existing = {row['Field'] for row in cur.fetchall()}

            columns = {
                'bale_id': 'BIGINT',
                'connected': 'BOOLEAN DEFAULT FALSE',
                'daily_uploaded': 'BIGINT DEFAULT 0',
                'total_uploaded': 'BIGINT DEFAULT 0',
                'file_count': 'BIGINT DEFAULT 0',
                'last_reset_date': 'DATE',
                'github_token': 'TEXT',
                'github_repo': 'VARCHAR(255) DEFAULT \'GitelUpload\''
            }

            for col, definition in columns.items():
                if col not in existing:
                    cur.execute(f"ALTER TABLE connections ADD COLUMN {col} {definition}")
                    print(f"✅ ستون {col} اضافه شد.")

            conn.commit()
    print("✅ دیتابیس با موفقیت ابتدایی‌سازی شد.")

init_database()

def get_expiration_minutes(size_mb: float) -> int:
    if size_mb < 100:   return 10
    elif size_mb < 300: return 20
    elif size_mb < 500: return 30
    elif size_mb < 700: return 40
    else:               return int(size_mb / 1000) * 60 + 60

def bale_polling():
    offset = 0
    while True:
        try:
            url = f"{BASE_URL}{BALE_TOKEN}/getUpdates?offset={offset}&timeout=30"
            resp = requests.get(url, timeout=40).json()
            if resp.get("ok"):
                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        bale_chat_id = update["message"]["chat"]["id"]
                        if text.startswith("connect:Bale:"):
                            parts = text.split(":")
                            if len(parts) == 4:
                                tg_id = int(parts[2])
                                with get_db() as conn:
                                    with conn.cursor() as cur:
                                        cur.execute(
                                            "INSERT INTO connections (telegram_id, bale_id, connected) "
                                            "VALUES (%s, %s, TRUE) ON DUPLICATE KEY UPDATE bale_id=%s, connected=TRUE",
                                            (tg_id, bale_chat_id, bale_chat_id)
                                        )
                                        conn.commit()
                                requests.post(f"{BASE_URL}{BALE_TOKEN}/sendMessage", json={"chat_id": bale_chat_id, "text": "✅ اتصال با موفقیت انجام شد!"])
                                try:
                                    app.send_message(tg_id, "✅ اتصال به بله با موفقیت انجام شد!")
                                except:
                                    pass
        except:
            time.sleep(5)

async def get_user_status(tg_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM connections WHERE telegram_id=%s", (tg_id,))
            return cur.fetchone()

async def build_main_menu_text(row):
    if not row:
        status = "❌ متصل نیست"
        daily_mb = 0
        total_mb = 0
        github_status = "❌ متصل نیست"
    else:
        status = "✅ متصل" if row.get("connected") else "❌ متصل نیست"
        daily_mb = (row.get("daily_uploaded") or 0) / (1024 * 1024)
        total_mb = (row.get("total_uploaded") or 0) / (1024 * 1024)
        github_status = "✅ متصل" if row.get("github_token") else "❌ متصل نیست"

    remaining_mb = max(0, 1024 - daily_mb)

    return (
        f"━━━ 🤖 👋 منوی اصلی ━━━\n\n"
        f"📤 فایل یا لینک خود را ارسال کنید.\n"
        f"🔒 فایل‌ها با رمز یکبار مصرف قوی رمزگذاری می‌شوند.\n\n"
        f"━━━━━━━ 📊 وضعیت حساب ━━━━━━━\n"
        f"🏷 پلن: رایگان\n"
        f"محدودیت روزانه : 1024 MB\n"
        f"مصرفی: {daily_mb:.1f} MB | باقی: {remaining_mb:.2f} MB\n"
        f"وضعیت اتصال به بله : {status}\n"
        f"وضعیت گیت‌هاب شخصی : {github_status}\n"
        f"⏳ اعتبار لینک: 1 ساعت (1GB=1 H)\n\n"
        f"📜 قوانین: محتوای غیرقانونی ممنوع | مسئولیت فایل‌ها با کاربر است.\n\n"
        f"👇 فایل خود را ارسال کنید:"
    )

@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    tg_id = message.from_user.id
    row = await get_user_status(tg_id)
    text = await build_main_menu_text(row)

    buttons = []
    if row and row.get("connected"):
        buttons.append([InlineKeyboardButton("🔌 قطع اتصال به بله", callback_data="disconnect")])
    else:
        buttons.append([InlineKeyboardButton("🔗 اتصال به بله", callback_data="connect")])

    buttons.append([InlineKeyboardButton("🐙 اتصال گیت‌هاب شخصی", callback_data="connect_github")])

    if tg_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])

    keyboard = InlineKeyboardMarkup(buttons)
    await message.reply_text(text, reply_markup=keyboard)

@app.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data
    tg_id = callback_query.from_user.id
    msg = callback_query.message

    if data == "connect":
        random_code = secrets.token_hex(8).upper()
        code = f"connect:Bale:{tg_id}:{random_code}"
        await msg.edit_text(f"🔗 کد اتصال شما:\n\n`{code}`\n\nاین کد را برای @{BALE_BOT_USERNAME} بفرستید.")

    elif data == "disconnect":
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE connections SET connected=FALSE WHERE telegram_id=%s", (tg_id,))
                conn.commit()
        row = await get_user_status(tg_id)
        text = await build_main_menu_text(row)
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 اتصال به بله", callback_data="connect")],
            [InlineKeyboardButton("🐙 اتصال گیت‌هاب شخصی", callback_data="connect_github")]
        ]))

    elif data == "connect_github":
        await msg.edit_text(
            "🐙 **اتصال گیت‌هاب شخصی**\n\n"
            "توکن گیت‌هاب خود را بفرستید (با ghp_ یا github_pat_ شروع می‌شود):\n\n"
            "⚠️ این توکن فقط برای آپلود فایل استفاده می‌شود و ذخیره می‌گردد."
        )

    elif data == "admin_panel" and tg_id == ADMIN_ID:
        await show_admin_panel(client, callback_query)

    elif data == "back_to_start":
        row = await get_user_status(tg_id)
        text = await build_main_menu_text(row)
        buttons = []
        if row and row.get("connected"):
            buttons.append([InlineKeyboardButton("🔌 قطع اتصال به بله", callback_data="disconnect")])
        else:
            buttons.append([InlineKeyboardButton("🔗 اتصال به بله", callback_data="connect")])
        buttons.append([InlineKeyboardButton("🐙 اتصال گیت‌هاب شخصی", callback_data="connect_github")])
        if tg_id == ADMIN_ID:
            buttons.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("cancel:"):
        cancel_id = data.split(":")[1]
        cancel_flags[cancel_id] = True
        try:
            await msg.edit_text("❌ آپلود کنسل شد.\nفایل جزئی حذف شد.")
        except:
            pass

@app.on_message(filters.private & ~filters.command("start"))
async def github_token_handler(client: Client, message: Message):
    tg_id = message.from_user.id

    # Only process text messages
    if not message.text:
        return

    text = message.text.strip()

    # Accept both classic (ghp_) and fine-grained (github_pat_) tokens
    if text.startswith("ghp_") or text.startswith("github_pat_"):
        headers = {"Authorization": f"token {text}", "Accept": "application/vnd.github.v3+json"}
        test = requests.get(f"{GITHUB_API}/user", headers=headers)

        if test.status_code == 200:
            user_data = test.json()
            github_username = user_data.get("login")

            repo_check = requests.get(f"{GITHUB_API}/repos/{github_username}/GitelUpload", headers=headers)
            if repo_check.status_code == 404:
                create_repo = requests.post(f"{GITHUB_API}/user/repos", json={
                    "name": "GitelUpload",
                    "private": False,
                    "description": "Bale Telegram Bot Uploads"
                }, headers=headers)
                if create_repo.status_code in [201, 200]:
                    await message.reply_text("✅ ریپوی GitelUpload ساخته شد!")
                else:
                    await message.reply_text(f"❌ خطا در ساخت ریپو: {create_repo.text}")
                    return

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE connections SET github_token=%s, github_repo='GitelUpload' WHERE telegram_id=%s",
                        (text, tg_id)
                    )
                    conn.commit()

            await message.reply_text(
                f"✅ **اتصال موفق!**\n\n"
                f"گیت‌هاب شما ({github_username}) متصل شد.\n"
                f"ریپو: GitelUpload\n\n"
                f"حالا می‌توانید فایل بفرستید."
            )
        else:
            await message.reply_text("❌ توکن نامعتبر است. لطفاً دوباره تلاش کنید.")

@app.on_message(
    (filters.document | filters.video | filters.audio | filters.voice | filters.photo) & filters.private
)
async def download_handler(client: Client, message: Message):
    tg_id = message.from_user.id
    cancel_id = str(message.id)
    cancel_flags[cancel_id] = False

    row = await get_user_status(tg_id)
    if not row or not row.get("github_token"):
        await message.reply_text(
            "❌ **گیت‌هاب شخصی متصل نیست!**\n\n"
            "لطفاً ابتدا از منوی اصلی گزینه '🐙 اتصال گیت‌هاب شخصی' را انتخاب کنید."
        )
        return

    file_name = getattr(message.document, "file_name", "") if message.document else ""
    ext = os.path.splitext(file_name)[1].lower()
    if ext in DANGEROUS_EXT:
        await message.reply_text("❌ این فرمت فایل به دلایل امنیتی مجاز نیست.")
        return

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT daily_uploaded, last_reset_date FROM connections WHERE telegram_id=%s", (tg_id,))
            row = cur.fetchone()
            today = date.today()
            if not row or row["last_reset_date"] != today:
                cur.execute("UPDATE connections SET daily_uploaded=0, last_reset_date=%s WHERE telegram_id=%s", (today, tg_id))
                conn.commit()
                daily_used = 0
            else:
                daily_used = row["daily_uploaded"] or 0

    if daily_used >= DAILY_LIMIT:
        await message.reply_text("❌ محدودیت روزانه شما (۱ گیگ) تمام شده است.")
        return

    await message.reply_text("📥 فایل دریافت شد، در حال پردازش...")

    if message.photo:
        if isinstance(message.photo, list):
            file_attr = message.photo[-1]
        else:
            file_attr = message.photo
    else:
        file_attr = message.document or message.video or message.audio or message.voice

    if not file_attr: 
        await message.reply_text("❌ فایل پشتیبانی نمی‌شود.")
        return

    file_name = getattr(file_attr, "file_name", f"file_{message.id}.jpg")
    destination = DOWNLOADS_PATH / file_name

    status = await message.reply_text(
        f"🚀 در حال دانلود `{file_name}`...",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ کنسل", callback_data=f"cancel:{cancel_id}")]])
    )

    status.start_time = time.time()
    status.prev_bytes = 0
    status.prev_time = time.time()

    try:
        await client.download_media(
            message=message,
            file_name=str(destination),
            progress=progress_callback,
            progress_args=(status, file_name, getattr(file_attr, "file_size", 0))
        )

        if cancel_flags.get(cancel_id, False):
            if destination.exists(): os.remove(destination)
            return

        file_size = destination.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        await status.edit_text(f"✅ دانلود کامل شد ({file_size_mb:.1f} MB).")

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE connections 
                    SET daily_uploaded = daily_uploaded + %s,
                        total_uploaded = total_uploaded + %s,
                        file_count = file_count + 1
                    WHERE telegram_id=%s
                """, (file_size, file_size, tg_id))
                conn.commit()

        await upload_to_user_github(destination, file_name, status, client, message.chat.id, tg_id, cancel_id)

    except Exception as e:
        await status.edit_text(f"❌ خطا: {str(e)}")

async def progress_callback(current, total, status_msg, file_name, file_size):
    if total == 0: return
    percent = (current / total) * 100
    filled = int(percent / 10)
    bar = "█" * filled + "░" * (10 - filled)

    now = time.time()
    speed = (current - status_msg.prev_bytes) / (now - status_msg.prev_time + 0.001)
    status_msg.prev_bytes = current
    status_msg.prev_time = now

    speed_mb = speed / (1024 * 1024)
    eta = "—" if speed <= 0 else (f"{int((total-current)/speed)} ثانیه" if (total-current)/speed < 60 else f"{(total-current)/speed/60:.1f} دقیقه")

    try:
        await status_msg.edit_text(
            f"📥 **دریافت فایل از تلگرام**\n\n"
            f"[{bar}] {percent:.1f}%\n"
            f"📦 {current / (1024*1024):.1f} MB از {total / (1024*1024):.1f} MB\n"
            f"⚡ سرعت: {speed_mb:.2f} MB/s\n"
            f"⏱ زمان باقی‌مانده: {eta}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ کنسل", callback_data=f"cancel:{status_msg.id}")]])
        )
    except:
        pass

async def upload_to_user_github(file_path: Path, file_name: str, status_msg: Message, client, chat_id, user_id, cancel_id):
    try:
        row = await get_user_status(user_id)
        if not row or not row.get("github_token"):
            await status_msg.edit_text("❌ توکن گیت‌هاب یافت نشد!")
            return

        user_token = row["github_token"]
        github_repo = row.get("github_repo", "GitelUpload")

        password = secrets.token_urlsafe(64)
        zip_path = file_path.with_suffix(".7z")
        random_num = random.randint(100000, 999999)
        branch_name = f"user_{user_id}_{random_num}"

        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        await status_msg.edit_text(f"🗜 در حال فشرده‌سازی فایل ({file_size_mb:.1f} MB)...\nلطفاً صبر کنید...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ کنسل", callback_data=f"cancel:{cancel_id}")]]))

        with py7zr.SevenZipFile(zip_path, mode='w', password=password) as z:
            z.write(file_path, arcname=file_path.name)

        if cancel_flags.get(cancel_id, False):
            if file_path.exists(): os.remove(file_path)
            if zip_path.exists(): os.remove(zip_path)
            return

        await status_msg.edit_text("☁️ در حال آپلود به گیت‌هاب شما...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ کنسل", callback_data=f"cancel:{cancel_id}")]]))

        headers = {
            "Authorization": f"token {user_token}",
            "Accept": "application/vnd.github.v3+json"
        }

        user_info = requests.get(f"{GITHUB_API}/user", headers=headers).json()
        github_username = user_info.get("login")

        repo_info = requests.get(f"{GITHUB_API}/repos/{github_username}/{github_repo}", headers=headers).json()
        default_branch = repo_info.get("default_branch", "main")

        ref = requests.get(f"{GITHUB_API}/repos/{github_username}/{github_repo}/git/ref/heads/{default_branch}", headers=headers).json()
        base_sha = ref["object"]["sha"]

        requests.post(f"{GITHUB_API}/repos/{github_username}/{github_repo}/git/refs", json={"ref": f"refs/heads/{branch_name}", "sha": base_sha}, headers=headers)

        with open(zip_path, "rb") as f:
            content = f.read()
        content_b64 = base64.b64encode(content).decode()

        put_url = f"{GITHUB_API}/repos/{github_username}/{github_repo}/contents/{zip_path.name}"
        put_data = {
            "message": f"Upload {file_name}",
            "content": content_b64,
            "branch": branch_name
        }

        response = requests.put(put_url, json=put_data, headers=headers)
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to upload: {response.text}")

        download_link = f"https://codeload.github.com/{github_username}/{github_repo}/zip/refs/heads/{branch_name}"

        size_mb = file_path.stat().st_size / (1024 * 1024)
        minutes = get_expiration_minutes(size_mb)
        expire_time = datetime.now() + timedelta(minutes=minutes)
        expire_str = expire_time.strftime("%Y/%m/%d — %H:%M")

        telegram_text = f"━━━ 🟢 🟢 آپلود موفق! 🎉 ━━━\n\nفایل `{file_name}` با موفقیت آپلود شد.\n\n🔗 لینک: {download_link}\n\n🔑 رمز: `{password}`\n\n📦 حجم: {size_mb:.1f} MB\n⏳ اعتبار تا: {expire_str}"

        await client.send_message(chat_id, telegram_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="back_to_start")]]))
        await status_msg.edit_text("✅ آپلود به گیت‌هاب شما انجام شد.")

        if file_path.exists(): os.remove(file_path)
        if zip_path.exists(): os.remove(zip_path)

    except Exception as e:
        error_msg = f"❌ خطا در آپلود: {str(e)}"
        print(error_msg)
        await status_msg.edit_text(error_msg)

async def upload_direct_to_bale(file_path: Path, file_name: str, status_msg: Message, client, chat_id, bale_id):
    try:
        url = f"{BASE_URL}{BALE_TOKEN}/sendDocument"
        with open(file_path, "rb") as f:
            files = {"document": (file_name, f)}
            data = {"chat_id": bale_id, "caption": f"📤 {file_name}"}
            response = requests.post(url, data=data, files=files, timeout=300)

        if response.status_code == 200:
            await status_msg.edit_text("✅ فایل به بله ارسال شد.")
            await client.send_message(chat_id, f"✅ فایل `{file_name}` مستقیم به بله شما ارسال شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="back_to_start")]]))
        else:
            await status_msg.edit_text("❌ خطا در ارسال به بله")
    finally:
        if file_path.exists():
            os.remove(file_path)

async def send_to_bale(text: str):
    requests.post(f"{BASE_URL}{BALE_TOKEN}/sendMessage", json={"chat_id": BALE_USER_ID, "text": text})

print("✅ ربات کامل و نهایی (Gitel Bot) در حال اجرا...")
threading.Thread(target=bale_polling, daemon=True).start()
app.run()