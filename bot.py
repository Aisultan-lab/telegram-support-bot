import asyncio
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID", "0") or "0")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = set(int(x) for x in ADMIN_IDS_RAW.split(",") if x.isdigit())

DB_PATH = "support.db"

# ---------------- DB ----------------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            created_at TEXT,
            category TEXT,
            platform TEXT,
            version TEXT,
            urgency TEXT,
            description TEXT,
            status TEXT,
            taken_by TEXT
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS reply_mode (
            admin_id INTEGER PRIMARY KEY,
            ticket_id INTEGER,
            user_id INTEGER
        )
        """)

# ---------------- UI ----------------
CATEGORIES = [
    ("🐞 Баг", "BUG"),
    ("❓ Вопрос", "QUESTION"),
    ("💡 Предложение", "IDEA"),
    ("💳 Оплата", "PAYMENT"),
    ("🔐 Вход", "AUTH"),
    ("🧩 Другое", "OTHER"),
]

PLATFORMS = [("Android", "ANDROID"), ("iOS", "IOS"), ("Не знаю", "UNKNOWN")]
URGENCY = [("Обычно", "NORMAL"), ("Срочно", "URGENT")]

def kb(items, prefix):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=f"{prefix}:{v}")]
        for t, v in items
    ])

def admin_kb(ticket_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Взять", callback_data=f"take:{ticket_id}"),
            InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply:{ticket_id}")
        ],
        [InlineKeyboardButton(text="🔒 Закрыть", callback_data=f"close:{ticket_id}")]
    ])

# ---------------- FSM ----------------
class Ticket(StatesGroup):
    category = State()
    platform = State()
    version = State()
    urgency = State()
    description = State()

# ---------------- BOT ----------------
dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("👋 Привет! Я бот поддержки.\n\nНажми /new чтобы создать обращение.")

@dp.message(Command("new"))
async def new_ticket(m: Message, state: FSMContext):
    await state.set_state(Ticket.category)
    await m.answer("Выбери тему:", reply_markup=kb(CATEGORIES, "cat"))

@dp.callback_query(F.data.startswith("cat:"))
async def cat(c: CallbackQuery, state: FSMContext):
    await state.update_data(category=c.data.split(":")[1])
    await state.set_state(Ticket.platform)
    await c.message.answer("Платформа:", reply_markup=kb(PLATFORMS, "plat"))

@dp.callback_query(F.data.startswith("plat:"))
async def plat(c: CallbackQuery, state: FSMContext):
    await state.update_data(platform=c.data.split(":")[1])
    await state.set_state(Ticket.version)
    await c.message.answer("Версия приложения:")

@dp.message(Ticket.version)
async def ver(m: Message, state: FSMContext):
    await state.update_data(version=m.text)
    await state.set_state(Ticket.urgency)
    await m.answer("Срочность:", reply_markup=kb(URGENCY, "urg"))

@dp.callback_query(F.data.startswith("urg:"))
async def urg(c: CallbackQuery, state: FSMContext):
    await state.update_data(urgency=c.data.split(":")[1])
    await state.set_state(Ticket.description)
    await c.message.answer("Опиши проблему:")

@dp.message(Ticket.description)
async def desc(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()

    with db() as con:
        cur = con.execute("""
        INSERT INTO tickets (user_id, username, created_at, category, platform, version, urgency, description, status)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            m.from_user.id,
            m.from_user.username or "",
            datetime.now(timezone.utc).isoformat(),
            data["category"],
            data["platform"],
            data["version"],
            data["urgency"],
            m.text,
            "NEW"
        ))
        ticket_id = cur.lastrowid

    await m.answer(f"✅ Обращение #{ticket_id} создано. Мы ответим здесь.")

    if SUPPORT_CHAT_ID != 0:
        await bot.send_message(
            SUPPORT_CHAT_ID,
            f"🆕 Тикет #{ticket_id}\n"
            f"От: {m.from_user.full_name}\n"
            f"Категория: {data['category']}\n"
            f"Платформа: {data['platform']}\n"
            f"Версия: {data['version']}\n"
            f"Срочность: {data['urgency']}\n\n"
            f"{m.text}",
            reply_markup=admin_kb(ticket_id)
        )

@dp.callback_query(F.data.startswith(("take:", "reply:", "close:")))
async def admin_actions(c: CallbackQuery, bot: Bot):
    if c.message.chat.id != SUPPORT_CHAT_ID:
        return

    action, tid = c.data.split(":")
    tid = int(tid)

    if action == "take":
        with db() as con:
            con.execute("UPDATE tickets SET status='IN_PROGRESS', taken_by=? WHERE id=?",
                        (c.from_user.full_name, tid))
        await c.answer("Взято")

    if action == "close":
        with db() as con:
            con.execute("UPDATE tickets SET status='CLOSED' WHERE id=?", (tid,))
        await c.answer("Закрыто")

    if action == "reply":
        with db() as con:
            con.execute("INSERT OR REPLACE INTO reply_mode VALUES (?,?,?)",
                        (c.from_user.id, tid, None))
        await c.answer("Напиши ответ следующим сообщением")

@dp.message(F.chat.id == SUPPORT_CHAT_ID)
async def admin_reply(m: Message, bot: Bot):
    with db() as con:
        row = con.execute("SELECT * FROM reply_mode WHERE admin_id=?",
                          (m.from_user.id,)).fetchone()
        if not row:
            return

        ticket = con.execute("SELECT user_id FROM tickets WHERE id=?",
                             (row["ticket_id"],)).fetchone()
        if ticket:
            await bot.send_message(ticket["user_id"], f"💬 Ответ поддержки:\n\n{m.text}")

        con.execute("DELETE FROM reply_mode WHERE admin_id=?", (m.from_user.id,))

async def main():
    init_db()
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
from aiogram import types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

@dp.message(Command("get_chat_id"), state="*")
async def get_chat_id(message: types.Message, state: FSMContext):
    await message.answer(
        f"Chat ID: `{message.chat.id}`",
        parse_mode="Markdown"
    )
