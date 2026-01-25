import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ===== STATES =====
class TicketState(StatesGroup):
    waiting_for_text = State()


# ===== START =====
@dp.message(Command("start"))
async def start(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Создать обращение", callback_data="new_ticket")

    await message.answer(
        "👋 Привет!\n\n"
        "Я бот поддержки.\n"
        "Нажми кнопку ниже, чтобы создать обращение.",
        reply_markup=kb.as_markup()
    )


# ===== NEW TICKET =====
@dp.callback_query(F.data == "new_ticket")
async def new_ticket(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🐞 Ошибка", callback_data="topic_bug")
    kb.button(text="❓ Вопрос", callback_data="topic_question")
    kb.button(text="💡 Предложение", callback_data="topic_idea")
    kb.button(text="💳 Оплата", callback_data="topic_payment")
    kb.button(text="🔐 Вход / аккаунт", callback_data="topic_login")
    kb.button(text="🧩 Другое", callback_data="topic_other")
    kb.adjust(2)

    await call.message.edit_text(
        "📌 Выбери тему обращения:",
        reply_markup=kb.as_markup()
    )


# ===== TOPIC SELECT =====
@dp.callback_query(F.data.startswith("topic_"))
async def select_topic(call: CallbackQuery, state: FSMContext):
    topic_map = {
        "topic_bug": "🐞 Ошибка",
        "topic_question": "❓ Вопрос",
        "topic_idea": "💡 Предложение",
        "topic_payment": "💳 Оплата",
        "topic_login": "🔐 Вход / аккаунт",
        "topic_other": "🧩 Другое",
    }

    topic = topic_map.get(call.data, "Другое")
    await state.update_data(topic=topic)

    await call.message.edit_text(
        f"✍️ Опиши проблему одним сообщением.\n\n"
        f"Тема: {topic}"
    )
    await state.set_state(TicketState.waiting_for_text)


# ===== TEXT FROM USER =====
@dp.message(TicketState.waiting_for_text)
async def get_text(message: Message, state: FSMContext):
    data = await state.get_data()
    topic = data["topic"]

    user = message.from_user
    text = message.text

    support_text = (
        "📩 НОВОЕ ОБРАЩЕНИЕ\n\n"
        f"👤 Пользователь: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📌 Тема: {topic}\n\n"
        f"💬 Сообщение:\n{text}"
    )

    await bot.send_message(SUPPORT_CHAT_ID, support_text)

    await message.answer(
        "✅ Спасибо!\n"
        "Обращение отправлено в поддержку.\n"
        "Мы ответим вам здесь."
    )

    await state.clear()


# ===== MAIN =====
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
