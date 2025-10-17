#!/usr/bin/env python3
import logging
import sqlite3
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "8294340245:AAGHWLftKLDmzG9FNefbTvVAEkJPv8HYWkY"
DB_PATH = "concoin.db"
DAILY_AMOUNT = 50
TIMEZONE = "Africa/Cairo"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            joined_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def add_or_update_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if c.fetchone():
        c.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    else:
        c.execute(
            "INSERT INTO users (user_id, username, balance, joined_at) VALUES (?, ?, ?, ?)",
            (user_id, username, 0, now),
        )
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def change_balance(user_id, delta):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
    conn.commit()
    conn.close()

def find_user_by_username(username):
    if username.startswith("@"):
        username = username[1:]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM users WHERE lower(username) = lower(?)", (username,))
    row = c.fetchone()
    conn.close()
    return row

def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_leaderboard(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, user_id, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user.id, user.username or None)
    text = (
        f"Welcome {user.first_name}.\n"
        f"You will receive {DAILY_AMOUNT} con daily.\n\n"
        "Commands:\n"
        "/balance\n"
        "/send <@username|user_id> <amount>\n"
        "/leaderboard\n"
    )
    await update.message.reply_text(text)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bal = get_balance(user.id)
    await update.message.reply_text(f"Balance: {bal} con")

async def send_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /send <@username|user_id> <amount>")
        return

    target = args[0]
    try:
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("Amount must be an integer.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be greater than zero.")
        return

    sender_balance = get_balance(user.id)
    if sender_balance < amount:
        await update.message.reply_text("Insufficient balance.")
        return

    recipient_row = None
    if target.startswith("@"):
        recipient_row = find_user_by_username(target)
    else:
        try:
            target_id = int(target)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, username FROM users WHERE user_id = ?", (target_id,))
            recipient_row = c.fetchone()
            conn.close()
        except ValueError:
            recipient_row = None

    if not recipient_row:
        await update.message.reply_text("Recipient not found. Ask them to send /start first.")
        return

    recipient_id = recipient_row[0]
    change_balance(user.id, -amount)
    change_balance(recipient_id, amount)
    await update.message.reply_text(f"Sent {amount} con to id:{recipient_id}")
    try:
        await context.bot.send_message(recipient_id, f"You received {amount} con from {user.username or user.first_name}")
    except Exception as e:
        logger.info(f"Could not notify recipient {recipient_id}: {e}")

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_leaderboard(10)
    if not rows:
        await update.message.reply_text("No users yet.")
        return
    text_lines = ["Leaderboard (top 10):"]
    rank = 1
    for username, user_id, bal in rows:
        display = f"@{username}" if username else f"id:{user_id}"
        text_lines.append(f"{rank}. {display} — {bal} con")
        rank += 1
    await update.message.reply_text("\n".join(text_lines))

def daily_credit_job():
    tz = timezone(TIMEZONE)
    now = datetime.now(tz)
    logger.info(f"Running daily credit job at {now.isoformat()}")
    user_ids = get_all_user_ids()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for uid in user_ids:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (DAILY_AMOUNT, uid))
    conn.commit()
    conn.close()
    logger.info(f"Credited {DAILY_AMOUNT} con to {len(user_ids)} users.")

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("send", send_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(daily_credit_job, trigger="cron", hour=0, minute=0)
    scheduler.start()
    logger.info("Scheduler started.")
    app.run_polling()

if __name__ == "__main__":
    main()