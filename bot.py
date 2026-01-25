import os
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID"))

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ================= DATA =================
TICKETS = {}      # ticket_id -> user_id
REPLY_MODE = {}   # admin_id -> ticket_id
TICKET_COUNTER = 1

# ================= STATES =================
class TicketFlow(StatesGroup):
    details = State()
    waiting_attachment = State()

# ================= TOPICS =================
TOPICS = [
    ("🐞 Ошибка", "BUG"),
    ("❓ Вопрос", "QUESTION"),
    ("💡 Предложение", "IDEA"),
    ("💳 Оплата", "PAYMENT"),
    ("🔐 Вход / аккаунт", "AUTH"),
    ("🧩 Другое", "OTHER"),
]

# ================= KEYBOARDS =================
def topics_kb():
    kb = InlineKeyboardBuilder()
    for t, c in TOPICS:
        kb.button(text=t, callback_data=f"topic:{c}")
    kb.adjust(2)
    return kb.as_markup()

def back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="back")
    return kb.as_markup()

def attach_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📎 Прикрепить файл", callback_data="attach_yes")
    kb.button(text="➡️ Без вложений", callback_data="attach_no")
    kb.adjust(1)
    return kb.as_markup()

def finish_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новое обращение", callback_data="new")
    kb.button(text="🏠 В начало", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()

def admin_kb(ticket_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Ответить", callback_data=f"reply:{ticket_id}")
    kb.button(text="🟡 В работе", callback_data=f"progress:{ticket_id}")
    kb.button(text="🔒 Закрыто", callback_data=f"close:{ticket_id}")
    kb.adjust(1)
    return kb.as_markup()

# ================= HELPERS =================
def topic_title(code):
    return dict(TOPICS).get(code, "🧩 Другое")

def topic_prompt(code):
    prompts = {
        "BUG": "🐞 Опишите ошибку одним сообщением.\nПосле можно прикрепить файл.",
        "QUESTION": "❓ Опишите вопрос одним сообщением.",
        "IDEA": "💡 Опишите предложение или идею.",
        "PAYMENT": "💳 Опишите проблему с оплатой.",
        "AUTH": "🔐 Опишите проблему со входом.",
    }
    return prompts.get(code, "🧩 Опишите обращение.")

# ================= START =================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Создать обращение", callback_data="new")
    await message.answer(
        "Здравствуйте.\n\n"
        "🤖 Служба поддержки.\n"
        "Здесь вы можете отправить обращение нашей команде.",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery, state: FSMContext):
    await start(call.message, state)

# ================= NEW =================
@dp.callback_query(F.data == "new")
async def new_ticket(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "📌 Выберите категорию обращения:",
        reply_markup=topics_kb()
    )

@dp.callback_query(F.data == "back")
async def back(call: CallbackQuery, state: FSMContext):
    await new_ticket(call, state)

# ================= TOPIC =================
@dp.callback_query(F.data.startswith("topic:"))
async def pick_topic(call: CallbackQuery, state: FSMContext):
    await state.update_data(topic=call.data.split(":")[1])
    await call.message.edit_text(
        topic_prompt(call.data.split(":")[1]),
        reply_markup=back_kb()
    )
    await state.set_state(TicketFlow.details)

# ================= DETAILS =================
@dp.message(TicketFlow.details)
async def details(message: Message, state: FSMContext):
    await state.update_data(details=message.text)
    await message.answer(
        "📎 Хотите прикрепить файл?",
        reply_markup=attach_kb()
    )

# ================= SEND =================
async def send_ticket(user, state, attachment: Message | None = None):
    global TICKET_COUNTER
    data = await state.get_data()

    ticket_id = TICKET_COUNTER
    TICKET_COUNTER += 1
    TICKETS[ticket_id] = user.id

    text = (
        f"📩 ОБРАЩЕНИЕ #{ticket_id}\n\n"
        f"👤 {user.full_name}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"📌 Категория: {topic_title(data['topic'])}\n\n"
        f"💬 Сообщение:\n{data['details']}"
    )

    await bot.send_message(
        SUPPORT_CHAT_ID,
        text,
        reply_markup=admin_kb(ticket_id)
    )

    if attachment:
        await attachment.forward(SUPPORT_CHAT_ID)

# ================= ATTACH =================
@dp.callback_query(F.data == "attach_no")
async def no_attach(call: CallbackQuery, state: FSMContext):
    await send_ticket(call.from_user, state)
    await call.message.answer(
        "✅ Обращение принято.\nМы свяжемся с вами в ближайшее время.",
        reply_markup=finish_kb()
    )
    await state.clear()

@dp.callback_query(F.data == "attach_yes")
async def yes_attach(call: CallbackQuery, state: FSMContext):
    await state.set_state(TicketFlow.waiting_attachment)
    await call.message.answer("📎 Пришлите файл.")

@dp.message(
    TicketFlow.waiting_attachment,
    F.photo | F.video | F.document | F.video_note
)
async def attachment(message: Message, state: FSMContext):
    await send_ticket(message.from_user, state, attachment=message)
    await message.answer(
        "✅ Обращение принято.\nМы свяжемся с вами в ближайшее время.",
        reply_markup=finish_kb()
    )
    await state.clear()

# ================= ADMIN =================
@dp.callback_query(F.data.startswith(("reply", "progress", "close")))
async def admin_actions(call: CallbackQuery):
    action, tid = call.data.split(":")
    tid = int(tid)

    if action == "reply":
        REPLY_MODE[call.from_user.id] = tid
        await call.answer("Введите ответ следующим сообщением")
    elif action == "progress":
        await call.answer("Статус: в работе")
    elif action == "close":
        uid = TICKETS.get(tid)
        if uid:
            await bot.send_message(uid, f"🔒 Обращение #{tid} закрыто.")
        await call.answer("Обращение закрыто")

@dp.message(F.chat.id == SUPPORT_CHAT_ID)
async def admin_reply(message: Message):
    admin_id = message.from_user.id
    if admin_id not in REPLY_MODE:
        return

    tid = REPLY_MODE.pop(admin_id)
    uid = TICKETS.get(tid)
    if uid:
        await bot.send_message(
            uid,
            f"✉️ Ответ по обращению #{tid}:\n\n{message.text}"
        )

# ================= MAIN =================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
