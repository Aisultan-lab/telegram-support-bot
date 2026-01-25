import os
import asyncio
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
TICKETS = {}          # ticket_id -> user_id
REPLY_MODE = {}       # admin_id -> ticket_id
TICKET_STATUS = {}    # ticket_id -> "new"|"progress"|"closed"
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
    kb.button(text="✉️ Ответить пользователю", callback_data=f"reply:{ticket_id}")
    kb.button(text="🟡 В работе", callback_data=f"progress:{ticket_id}")
    kb.button(text="✅ Завершить", callback_data=f"close:{ticket_id}")
    kb.adjust(1)
    return kb.as_markup()

def user_after_close_kb(ticket_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Всё решено", callback_data=f"confirm_ok:{ticket_id}")
    kb.button(text="❌ Нужна помощь", callback_data=f"confirm_no:{ticket_id}")
    kb.adjust(1)
    return kb.as_markup()

def user_restart_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новое обращение", callback_data="new")
    kb.button(text="🏠 В начало", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()

# ================= HELPERS =================
def topic_title(code):
    return dict(TOPICS).get(code, "🧩 Другое")

def topic_prompt(code):
    prompts = {
        "BUG": "🐞 Опишите проблему одним сообщением.\nПри необходимости можно прикрепить файл.",
        "QUESTION": "❓ Опишите вопрос одним сообщением.",
        "IDEA": "💡 Опишите предложение или идею.",
        "PAYMENT": "💳 Опишите вопрос по оплате.",
        "AUTH": "🔐 Опишите проблему со входом.",
    }
    return prompts.get(code, "🧩 Опишите обращение.")

def user_ticket_accepted_text():
    return (
        "✅ Обращение принято.\n"
        "Мы свяжемся с вами в ближайшее время."
    )

def user_support_reply_text(ticket_id, reply_text):
    # ДЕЛОВОЙ формат, без “сырого” префикса
    return (
        f"📩 Сообщение от поддержки (обращение #{ticket_id})\n\n"
        f"{reply_text}"
    )

def user_close_text(ticket_id):
    return (
        f"✅ Мы завершили обработку обращения #{ticket_id}.\n"
        "Пожалуйста, подтвердите результат:"
    )

# ================= START =================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Создать обращение", callback_data="new")
    await message.answer(
        "Здравствуйте.\n\n"
        "🤖 Служба поддержки.\n"
        "Вы можете отправить обращение нашей команде.",
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
    await message.answer("📎 Хотите прикрепить файл?", reply_markup=attach_kb())

# ================= SEND =================
async def send_ticket(user, state, attachment: Message | None = None):
    global TICKET_COUNTER
    data = await state.get_data()

    ticket_id = TICKET_COUNTER
    TICKET_COUNTER += 1

    TICKETS[ticket_id] = user.id
    TICKET_STATUS[ticket_id] = "new"

    text = (
        f"📩 ОБРАЩЕНИЕ #{ticket_id}\n\n"
        f"👤 {user.full_name}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"📌 Категория: {topic_title(data['topic'])}\n\n"
        f"💬 Сообщение:\n{data['details']}"
    )

    await bot.send_message(SUPPORT_CHAT_ID, text, reply_markup=admin_kb(ticket_id))

    if attachment:
        await attachment.forward(SUPPORT_CHAT_ID)

    return ticket_id

# ================= ATTACH =================
@dp.callback_query(F.data == "attach_no")
async def no_attach(call: CallbackQuery, state: FSMContext):
    await send_ticket(call.from_user, state)
    await call.message.answer(user_ticket_accepted_text(), reply_markup=finish_kb())
    await state.clear()

@dp.callback_query(F.data == "attach_yes")
async def yes_attach(call: CallbackQuery, state: FSMContext):
    await state.set_state(TicketFlow.waiting_attachment)
    await call.message.answer("📎 Пришлите файл (скриншот/видео/документ).")

@dp.message(TicketFlow.waiting_attachment, F.photo | F.video | F.document | F.video_note)
async def attachment(message: Message, state: FSMContext):
    await send_ticket(message.from_user, state, attachment=message)
    await message.answer(user_ticket_accepted_text(), reply_markup=finish_kb())
    await state.clear()

# ================= ADMIN ACTIONS =================
@dp.callback_query(F.data.startswith(("reply", "progress", "close")))
async def admin_actions(call: CallbackQuery):
    action, tid = call.data.split(":")
    tid = int(tid)

    if action == "reply":
        REPLY_MODE[call.from_user.id] = tid
        await call.answer("Введите ответ следующим сообщением в группе.")
        return

    if action == "progress":
        TICKET_STATUS[tid] = "progress"
        # ВАЖНО: пользователю ничего не отправляем (это внутренний статус)
        await call.answer("Статус установлен: В работе")
        return

    if action == "close":
        TICKET_STATUS[tid] = "closed"
        uid = TICKETS.get(tid)
        if uid:
            await bot.send_message(uid, user_close_text(tid), reply_markup=user_after_close_kb(tid))
        await call.answer("Обращение завершено (пользователю отправлено подтверждение).")
        return

# ================= ADMIN REPLY =================
@dp.message(F.chat.id == SUPPORT_CHAT_ID)
async def admin_reply(message: Message):
    admin_id = message.from_user.id
    if admin_id not in REPLY_MODE:
        return

    tid = REPLY_MODE.pop(admin_id)
    uid = TICKETS.get(tid)
    if not uid:
        return

    await bot.send_message(uid, user_support_reply_text(tid, message.text), reply_markup=user_restart_kb())

# ================= USER CONFIRM AFTER CLOSE =================
@dp.callback_query(F.data.startswith(("confirm_ok", "confirm_no")))
async def confirm_close(call: CallbackQuery):
    action, tid = call.data.split(":")
    tid = int(tid)

    if action == "confirm_ok":
        await call.message.edit_text(
            "✅ Спасибо! Если появятся вопросы — вы можете создать новое обращение.",
        )
        await call.message.answer("Выберите действие:", reply_markup=finish_kb())
        await call.answer()
        return

    if action == "confirm_no":
        # По сути: заново создаём обращение, но логично и удобно
        await call.message.edit_text(
            "Понял. Давайте уточним проблему.\n\n"
            "📌 Выберите категорию обращения:",
            reply_markup=topics_kb()
        )
        await call.answer()
        return

# ================= MAIN =================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
