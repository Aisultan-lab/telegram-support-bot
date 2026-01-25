import os
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= STATES =================
class TicketFlow(StatesGroup):
    details = State()
    waiting_attachment = State()

# ================= TOPICS =================
TOPICS = [
    ("🐞 Баг", "BUG"),
    ("❓ Вопрос", "QUESTION"),
    ("💡 Предложение", "IDEA"),
    ("💳 Оплата", "PAYMENT"),
    ("🔐 Вход / аккаунт", "AUTH"),
    ("🧩 Другое", "OTHER"),
]

def topics_kb():
    kb = InlineKeyboardBuilder()
    for t, c in TOPICS:
        kb.button(text=t, callback_data=f"topic:{c}")
    kb.adjust(2)
    return kb.as_markup()

def back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="back_to_topics")
    return kb.as_markup()

def attach_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📎 Прикрепить файл", callback_data="attach_yes")
    kb.button(text="✅ Без вложений", callback_data="attach_no")
    kb.adjust(1)
    return kb.as_markup()

def topic_title(code):
    for t, c in TOPICS:
        if c == code:
            return t
    return "🧩 Другое"

def topic_prompt(code):
    if code == "BUG":
        return (
            "🐞 Ошибка\n\n"
            "Опишите проблему одним сообщением:\n"
            "• какие действия вы выполняли;\n"
            "• что ожидали получить;\n"
            "• что произошло фактически.\n\n"
            "После этого можно прикрепить скриншот или видео."
        )
    if code == "QUESTION":
        return (
            "❓ Вопрос\n\n"
            "Опишите ваш вопрос одним сообщением."
        )
    if code == "IDEA":
        return (
            "💡 Предложение\n\n"
            "Опишите предложение или идею.\n"
            "По возможности укажите ожидаемую пользу."
        )
    if code == "PAYMENT":
        return (
            "💳 Оплата\n\n"
            "Опишите проблему с оплатой:\n"
            "• что именно не получилось;\n"
            "• было ли сообщение об ошибке."
        )
    if code == "AUTH":
        return (
            "🔐 Вход / аккаунт\n\n"
            "Опишите проблему со входом:\n"
            "• код не приходит / неверный пароль / ошибка;\n"
            "• какой способ входа используется."
        )
    return (
        "🧩 Другое\n\n"
        "Опишите обращение одним сообщением."
    )

# ================= START =================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Создать обращение", callback_data="new_ticket")

    await message.answer(
        "Здравствуйте.\n\n"
        "🤖 Служба поддержки.\n"
        "Здесь вы можете отправить обращение нашей команде.\n\n"
        "Нажмите кнопку ниже, чтобы создать обращение.",
        reply_markup=kb.as_markup()
    )

# ================= NEW =================
@dp.callback_query(F.data == "new_ticket")
async def new_ticket(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "📌 Выберите категорию обращения:",
        reply_markup=topics_kb()
    )

# ================= TOPIC PICK =================
@dp.callback_query(F.data.startswith("topic:"))
async def pick_topic(call: CallbackQuery, state: FSMContext):
    code = call.data.split(":")[1]
    await state.update_data(topic=code)
    await call.message.edit_text(
        topic_prompt(code),
        reply_markup=back_kb()
    )
    await state.set_state(TicketFlow.details)

@dp.callback_query(F.data == "back_to_topics")
async def back_to_topics(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "📌 Выберите категорию обращения:",
        reply_markup=topics_kb()
    )

# ================= DETAILS =================
@dp.message(TicketFlow.details)
async def get_details(message: Message, state: FSMContext):
    await state.update_data(details=message.text)
    await message.answer(
        "📎 Хотите прикрепить файл (скриншот или видео), чтобы уточнить обращение?",
        reply_markup=attach_kb()
    )

# ================= ATTACH CHOICE =================
@dp.callback_query(F.data == "attach_no")
async def no_attach(call: CallbackQuery, state: FSMContext):
    await send_ticket(call.from_user, state)
    await call.message.answer(
        "✅ Обращение отправлено в поддержку.\n"
        "Ответ будет направлен вам в этом чате."
    )
    await state.clear()

@dp.callback_query(F.data == "attach_yes")
async def yes_attach(call: CallbackQuery, state: FSMContext):
    await state.set_state(TicketFlow.waiting_attachment)
    await call.message.answer(
        "📎 Пришлите один файл (скриншот, видео или документ)."
    )

# ================= ATTACHMENT =================
@dp.message(
    TicketFlow.waiting_attachment,
    F.photo | F.video | F.document | F.video_note | F.voice
)
async def get_attachment(message: Message, state: FSMContext):
    await send_ticket(message.from_user, state, attachment_message=message)
    await message.answer(
        "✅ Обращение и вложение отправлены в поддержку.\n"
        "Ответ будет направлен вам в этом чате."
    )
    await state.clear()

# ================= SEND =================
async def send_ticket(user, state, attachment_message: Message | None = None):
    data = await state.get_data()
    topic = topic_title(data["topic"])
    details = data["details"]

    text = (
        "📩 НОВОЕ ОБРАЩЕНИЕ\n\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"👤 Пользователь: {user.full_name}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"📌 Категория: {topic}\n\n"
        f"💬 Сообщение:\n{details}"
    )

    await bot.send_message(SUPPORT_CHAT_ID, text)

    if attachment_message:
        await attachment_message.forward(SUPPORT_CHAT_ID)

# ================= MAIN =================
async def main():
    if not BOT_TOKEN or not SUPPORT_CHAT_ID:
        raise RuntimeError("Проверь BOT_TOKEN и SUPPORT_CHAT_ID в переменных окружения.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
