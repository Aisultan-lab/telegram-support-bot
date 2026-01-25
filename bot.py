import os
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

# ======================
# CONFIG
# ======================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID", "0") or "0")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ======================
# SETUP MODE (настройка)
# Потом можно удалить, см. ниже
# ======================
@dp.message(Command("setup"))
async def setup_info(message: Message):
    await message.answer(
        "🛠 Режим настройки\n\n"
        "1) Добавь бота в группу поддержки\n"
        "2) В группе напиши: /set_support\n\n"
        "Я отвечу Chat ID группы, его нужно вставить в Render как SUPPORT_CHAT_ID."
    )

@dp.message(Command("set_support"))
async def set_support(message: Message):
    # Команда должна быть отправлена ИЗ группы поддержки
    # Чтобы ты мог получить chat.id без костылей
    await message.answer(f"✅ Chat ID этой группы: `{message.chat.id}`", parse_mode="Markdown")

# ======================
# TICKET FLOW
# ======================
class TicketFlow(StatesGroup):
    topic = State()
    details = State()
    attach = State()

TOPICS = [
    ("🐞 Ошибка", "BUG"),
    ("❓ Вопрос", "QUESTION"),
    ("💡 Предложение", "IDEA"),
    ("💳 Оплата", "PAYMENT"),
    ("🔐 Вход/аккаунт", "AUTH"),
    ("🧩 Другое", "OTHER"),
]

def topics_keyboard():
    kb = InlineKeyboardBuilder()
    for title, code in TOPICS:
        kb.button(text=title, callback_data=f"topic:{code}")
    kb.adjust(2)
    return kb.as_markup()

def yes_no_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📎 Да, прикреплю", callback_data="att:yes")
    kb.button(text="✅ Нет, без вложений", callback_data="att:no")
    kb.adjust(1)
    return kb.as_markup()

def topic_questions(code: str) -> str:
    # Логичные вопросы под каждую категорию
    if code == "BUG":
        return (
            "Опиши ошибку одним сообщением:\n"
            "• Что ты делал(а) перед ошибкой?\n"
            "• Что должно было произойти?\n"
            "• Что произошло на самом деле?\n"
            "• Если есть текст ошибки — вставь сюда."
        )
    if code == "QUESTION":
        return (
            "Задай вопрос одним сообщением:\n"
            "• Что именно хочешь узнать?\n"
            "• В каком месте/разделе возник вопрос?"
        )
    if code == "IDEA":
        return (
            "Опиши идею/улучшение:\n"
            "• Что предлагаешь добавить/изменить?\n"
            "• Зачем это нужно (какая польза)?"
        )
    if code == "PAYMENT":
        return (
            "Опиши проблему с оплатой:\n"
            "• Что именно не получилось (оплата/подписка/возврат)?\n"
            "• Какая ошибка/сообщение было?\n"
            "• Когда примерно это было?"
        )
    if code == "AUTH":
        return (
            "Опиши проблему со входом/аккаунтом:\n"
            "• Не приходит код? Не принимает пароль? Ошибка?\n"
            "• Что именно пишет приложение?\n"
            "• Какой способ входа (телефон/email/Google/Apple)?"
        )
    return (
        "Опиши обращение одним сообщением:\n"
        "• Что случилось?\n"
        "• Что хочешь получить в итоге?"
    )

def topic_title(code: str) -> str:
    for t, c in TOPICS:
        if c == code:
            return t
    return "🧩 Другое"

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Создать обращение", callback_data="new")
    kb.button(text="🛠 Настройка (админ)", callback_data="go_setup")
    kb.adjust(1)

    await message.answer(
        "👋 Привет! Я бот поддержки.\n\n"
        "Нажми «Создать обращение», чтобы написать в поддержку.",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "go_setup")
async def go_setup(call: CallbackQuery):
    await call.answer()
    await call.message.answer(
        "🛠 Настройка:\n"
        "1) Добавь меня в группу поддержки\n"
        "2) В группе напиши: /set_support\n"
        "3) Скопируй Chat ID и вставь в Render как SUPPORT_CHAT_ID\n"
        "4) Перезапусти сервис (Redeploy)\n\n"
        "Пока SUPPORT_CHAT_ID=0, я не смогу отправлять обращения в группу."
    )

@dp.callback_query(F.data == "new")
async def new_ticket(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await call.message.answer("📌 Выбери тему:", reply_markup=topics_keyboard())

@dp.callback_query(F.data.startswith("topic:"))
async def pick_topic(call: CallbackQuery, state: FSMContext):
    await call.answer()
    code = call.data.split(":", 1)[1]
    await state.update_data(topic=code)
    await state.set_state(TicketFlow.details)
    await call.message.answer(topic_questions(code))

@dp.message(TicketFlow.details)
async def save_details(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пожалуйста, отправь текстом описание (одним сообщением).")
        return

    await state.update_data(details=text)
    await state.set_state(TicketFlow.attach)
    await message.answer("Хочешь прикрепить скрин/видео/файл?", reply_markup=yes_no_keyboard())

@dp.callback_query(F.data.startswith("att:"))
async def attach_choice(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    data = await state.get_data()
    topic_code = data["topic"]
    details = data["details"]

    # Сообщение в группу поддержки
    user = call.from_user
    username = f"@{user.username}" if user.username else "(нет username)"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    support_text = (
        "📩 НОВОЕ ОБРАЩЕНИЕ\n\n"
        f"🕒 {stamp}\n"
        f"👤 Пользователь: {user.full_name} {username}\n"
        f"🆔 User ID: {user.id}\n"
        f"📌 Тема: {topic_title(topic_code)}\n\n"
        f"💬 Сообщение:\n{details}\n"
    )

    if SUPPORT_CHAT_ID == 0:
        await call.message.answer(
            "⚠️ Поддержка ещё не настроена (SUPPORT_CHAT_ID=0).\n"
            "Сделай так:\n"
            "1) Добавь бота в группу поддержки\n"
            "2) В группе напиши /set_support\n"
            "3) Вставь ID в Render как SUPPORT_CHAT_ID\n"
            "4) Redeploy\n\n"
            "После этого обращения будут падать в группу."
        )
        await state.clear()
        return

    await bot.send_message(SUPPORT_CHAT_ID, support_text)

    if choice == "yes":
        await call.message.answer("Ок! Пришли следующим сообщением скрин/видео/файл. Можно 1 файл.")
        # ждём вложение
        await state.set_state(State("await_attachment"))
    else:
        await call.message.answer("✅ Принято! Мы ответим тебе здесь в Telegram.")
        await state.clear()

@dp.message(F.photo | F.video | F.document | F.voice | F.video_note)
async def handle_attachment(message: Message, state: FSMContext):
    st = await state.get_state()
    if st != "await_attachment":
        return

    if SUPPORT_CHAT_ID != 0:
        try:
            await message.copy_to(SUPPORT_CHAT_ID)
            await bot.send_message(SUPPORT_CHAT_ID, "📎 Вложение к обращению (см. выше).")
        except Exception:
            pass

    await message.answer("✅ Вложение отправлено. Спасибо! Мы ответим тебе здесь.")
    await state.clear()

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it in Render Environment Variables.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
