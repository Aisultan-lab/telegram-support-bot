import os
import asyncio
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID"))

# -------- FSM --------

class TicketFlow(StatesGroup):
    category = State()
    text = State()

# -------- Keyboards --------

def kb_start():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать обращение", callback_data="new")]
    ])

def kb_categories():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐞 Баг", callback_data="bug")],
        [InlineKeyboardButton(text="❓ Вопрос", callback_data="question")],
        [InlineKeyboardButton(text="💡 Предложение", callback_data="idea")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="other")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

def kb_user_after():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новое обращение", callback_data="new")],
        [InlineKeyboardButton(text="🏠 В начало", callback_data="home")]
    ])

def kb_admin(ticket_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 В работе", callback_data=f"work:{ticket_id}"),
            InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply:{ticket_id}"),
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"close:{ticket_id}")
        ]
    ])

# -------- Router --------

router = Router()
ticket_counter = 0
reply_wait = {}

# -------- User --------

@router.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "Здравствуйте.\n\n"
        "Это служба поддержки.\n"
        "Нажмите кнопку ниже, чтобы создать обращение.",
        reply_markup=kb_start()
    )

@router.callback_query(F.data == "home")
async def home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Главное меню.", reply_markup=kb_start())
    await cb.answer()

@router.callback_query(F.data == "new")
async def new_ticket(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TicketFlow.category)
    await cb.message.edit_text("Выберите тему обращения:", reply_markup=kb_categories())
    await cb.answer()

@router.callback_query(TicketFlow.category)
async def choose_category(cb: CallbackQuery, state: FSMContext):
    if cb.data == "back":
        await state.clear()
        await cb.message.edit_text("Главное меню.", reply_markup=kb_start())
        return

    await state.update_data(category=cb.data)
    await state.set_state(TicketFlow.text)
    await cb.message.edit_text(
        "Опишите ситуацию одним сообщением.\n"
        "Вы можете прикрепить скриншот или видео следующим сообщением."
    )
    await cb.answer()

@router.message(TicketFlow.text)
async def receive_text(msg: Message, state: FSMContext, bot: Bot):
    global ticket_counter
    ticket_counter += 1
    data = await state.get_data()

    user = msg.from_user
    text = (
        f"📩 ОБРАЩЕНИЕ #{ticket_counter}\n"
        f"Статус: 🔵 Новое\n\n"
        f"👤 Пользователь: {user.full_name}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"👤 Username: @{user.username if user.username else 'нет'}\n"
        f"🔗 Написать: tg://user?id={user.id}\n\n"
        f"📌 Тема: {data['category']}\n\n"
        f"💬 Сообщение:\n{msg.text}"
    )

    sent = await bot.send_message(
        SUPPORT_CHAT_ID,
        text,
        reply_markup=kb_admin(ticket_counter)
    )

    await msg.answer(
        "✅ Обращение принято.\n"
        "Мы свяжемся с вами в ближайшее время.",
        reply_markup=kb_user_after()
    )

    await state.clear()

# -------- Admin --------

@router.callback_query(F.data.startswith("reply:"))
async def admin_reply(cb: CallbackQuery):
    tid = cb.data.split(":")[1]
    reply_wait[cb.from_user.id] = tid
    await cb.message.reply("Напишите ответ следующим сообщением.")
    await cb.answer()

@router.message(F.chat.id == SUPPORT_CHAT_ID)
async def admin_send_reply(msg: Message, bot: Bot):
    admin_id = msg.from_user.id
    if admin_id not in reply_wait:
        return

    tid = reply_wait.pop(admin_id)
    await bot.send_message(
        msg.reply_to_message.text.split("tg://user?id=")[1].split("\n")[0],
        f"📩 Ответ от службы поддержки:\n\n{msg.text}",
        reply_markup=kb_user_after()
    )
    await msg.reply("✅ Ответ отправлен пользователю.")

@router.callback_query(F.data.startswith("close:"))
async def admin_close(cb: CallbackQuery, bot: Bot):
    await bot.send_message(
        cb.message.text.split("tg://user?id=")[1].split("\n")[0],
        "✅ Мы завершили обработку вашего обращения.\n"
        "Если потребуется помощь — создайте новое обращение.",
        reply_markup=kb_user_after()
    )
    await cb.answer("Обращение закрыто")

# -------- Start --------

async def main():
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
