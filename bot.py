import os
import json
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")

SUPPORT_CHAT_ID = None
CFG_FILE = "support_cfg.json"
DATA_FILE = "tickets.json"

# ---------------- DATA ----------------

@dataclass
class TicketUser:
    user_id: int
    username: str | None
    full_name: str

@dataclass
class Ticket:
    id: int
    status: str
    topic: str
    text: str
    created: str
    user: TicketUser
    attachments: list
    group_msg_id: int | None = None

tickets: Dict[int, Ticket] = {}
ticket_counter = 0
admin_reply_wait: Dict[int, int] = {}

# ---------------- UTILS ----------------

def now():
    return datetime.utcnow().isoformat()

def save_cfg():
    with open(CFG_FILE, "w") as f:
        json.dump({"support_chat_id": SUPPORT_CHAT_ID}, f)

def load_cfg():
    global SUPPORT_CHAT_ID
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE) as f:
            SUPPORT_CHAT_ID = json.load(f).get("support_chat_id")

def save_tickets():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "counter": ticket_counter,
            "tickets": {k: asdict(v) for k, v in tickets.items()}
        }, f, ensure_ascii=False)

def load_tickets():
    global ticket_counter, tickets
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
            ticket_counter = data["counter"]
            tickets = {int(k): Ticket(**v) for k, v in data["tickets"].items()}

def next_id():
    global ticket_counter
    ticket_counter += 1
    return ticket_counter

def extract_media(msg: Message):
    if msg.photo:
        return ("photo", msg.photo[-1].file_id)
    if msg.video:
        return ("video", msg.video.file_id)
    if msg.document:
        return ("document", msg.document.file_id)
    return None

# ---------------- FSM ----------------

class Form(StatesGroup):
    topic = State()
    text = State()
    files = State()

# ---------------- KEYBOARDS ----------------

def kb_start():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новое обращение", callback_data="new")]
    ])

def kb_topics():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐞 Баг", callback_data="bug")],
        [InlineKeyboardButton(text="❓ Вопрос", callback_data="question")],
        [InlineKeyboardButton(text="💡 Предложение", callback_data="idea")],
        [InlineKeyboardButton(text="💳 Оплата", callback_data="payment")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="other")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="back")]
    ])

def kb_send():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="send")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="back")]
    ])

def kb_admin(tid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 В работе", callback_data=f"work:{tid}"),
            InlineKeyboardButton(text="✉ Ответить", callback_data=f"reply:{tid}"),
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"close:{tid}")
        ]
    ])

# ---------------- ROUTERS ----------------

user = Router()
admin = Router()

# ---------------- USER ----------------

@user.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "Здравствуйте.\n"
        "Это служба поддержки.\n\n"
        "Нажмите кнопку ниже для создания обращения.",
        reply_markup=kb_start()
    )

@user.callback_query(F.data == "new")
async def new_ticket(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.topic)
    await cb.message.edit_text("Выберите тему обращения:", reply_markup=kb_topics())
    await cb.answer()

@user.callback_query(Form.topic)
async def choose_topic(cb: CallbackQuery, state: FSMContext):
    if cb.data == "back":
        await state.clear()
        await cb.message.edit_text("Главное меню", reply_markup=kb_start())
        return
    await state.update_data(topic=cb.data, files=[])
    await state.set_state(Form.text)
    await cb.message.edit_text("Опишите проблему одним сообщением.")
    await cb.answer()

@user.message(Form.text)
async def get_text(msg: Message, state: FSMContext):
    await state.update_data(text=msg.text)
    await state.set_state(Form.files)
    await msg.answer(
        "Прикрепите файлы (если нужно) или нажмите «Отправить».",
        reply_markup=kb_send()
    )

@user.message(Form.files)
async def get_files(msg: Message, state: FSMContext):
    data = await state.get_data()
    media = extract_media(msg)
    if media:
        data["files"].append(media)
        await state.update_data(files=data["files"])
        await msg.answer("Файл добавлен. Можно отправить ещё или нажать «Отправить».")

@user.callback_query(Form.files, F.data == "send")
async def send_ticket(cb: CallbackQuery, state: FSMContext, bot: Bot):
    global SUPPORT_CHAT_ID
    load_cfg()
    if not SUPPORT_CHAT_ID:
        await cb.message.edit_text("Группа поддержки не настроена.")
        return

    data = await state.get_data()
    tid = next_id()

    user_data = TicketUser(
        user_id=cb.from_user.id,
        username=cb.from_user.username,
        full_name=cb.from_user.full_name
    )

    ticket = Ticket(
        id=tid,
        status="new",
        topic=data["topic"],
        text=data["text"],
        created=now(),
        user=user_data,
        attachments=data["files"]
    )

    tickets[tid] = ticket
    save_tickets()

    text = (
        f"📩 ОБРАЩЕНИЕ #{tid}\n"
        f"Статус: 🔵 Новое\n\n"
        f"👤 {user_data.full_name}\n"
        f"🆔 {user_data.user_id}\n"
        f"👤 @{user_data.username or 'нет'}\n\n"
        f"📌 Тема: {data['topic']}\n\n"
        f"💬 {data['text']}"
    )

    msg = await bot.send_message(
        SUPPORT_CHAT_ID,
        text,
        reply_markup=kb_admin(tid)
    )

    ticket.group_msg_id = msg.message_id
    save_tickets()

    for t, fid in ticket.attachments:
        if t == "photo":
            await bot.send_photo(SUPPORT_CHAT_ID, fid, reply_to_message_id=msg.message_id)
        if t == "video":
            await bot.send_video(SUPPORT_CHAT_ID, fid, reply_to_message_id=msg.message_id)
        if t == "document":
            await bot.send_document(SUPPORT_CHAT_ID, fid, reply_to_message_id=msg.message_id)

    await state.clear()
    await cb.message.edit_text(
        "✅ Обращение принято.\n"
        "Мы свяжемся с вами в ближайшее время.",
        reply_markup=kb_start()
    )

# ---------------- ADMIN ----------------

@admin.message(Command("set_support"))
async def set_support(msg: Message):
    global SUPPORT_CHAT_ID
    SUPPORT_CHAT_ID = msg.chat.id
    save_cfg()
    await msg.answer("✅ Группа поддержки установлена.")

@admin.callback_query(F.data.startswith("work:"))
async def set_work(cb: CallbackQuery, bot: Bot):
    tid = int(cb.data.split(":")[1])
    tickets[tid].status = "in_work"
    save_tickets()
    await cb.answer("В работе")

@admin.callback_query(F.data.startswith("close:"))
async def close(cb: CallbackQuery, bot: Bot):
    tid = int(cb.data.split(":")[1])
    tickets[tid].status = "closed"
    save_tickets()
    await bot.send_message(
        tickets[tid].user.user_id,
        f"✅ Обращение №{tid} закрыто.\nЕсли понадобится помощь — создайте новое обращение.",
        reply_markup=kb_start()
    )
    await cb.answer("Закрыто")

@admin.callback_query(F.data.startswith("reply:"))
async def reply(cb: CallbackQuery):
    tid = int(cb.data.split(":")[1])
    admin_reply_wait[tid] = cb.from_user.id
    await cb.message.reply("Напишите ответ следующим сообщением.")
    await cb.answer()

@admin.message(F.chat.type.in_(["group", "supergroup"]))
async def admin_reply(msg: Message, bot: Bot):
    for tid, admin_id in list(admin_reply_wait.items()):
        if msg.from_user.id == admin_id:
            user_id = tickets[tid].user.user_id
            await bot.send_message(
                user_id,
                f"📩 Ответ по обращению №{tid}:\n{msg.text}",
                reply_markup=kb_start()
            )
            admin_reply_wait.pop(tid)
            await msg.reply("Ответ отправлен.")
            break

# ---------------- START ----------------

async def main():
    load_cfg()
    load_tickets()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(user)
    dp.include_router(admin)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
