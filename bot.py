import os
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID_RAW = os.getenv("SUPPORT_CHAT_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")
if not SUPPORT_CHAT_ID_RAW:
    raise RuntimeError("Не задан SUPPORT_CHAT_ID (ID группы) в переменных окружения.")

SUPPORT_CHAT_ID = int(SUPPORT_CHAT_ID_RAW)

MAX_ATTACHMENTS = 5

# -------------------- Категории --------------------
CATEGORIES: List[Tuple[str, str]] = [
    ("BUG", "🐞 Ошибка"),
    ("QUESTION", "❓ Вопрос"),
    ("IDEA", "💡 Предложение"),
    ("PAYMENT", "💳 Оплата"),
    ("AUTH", "🔐 Вход / аккаунт"),
    ("OTHER", "🧩 Другое"),
]
CAT_TITLE = {code: title for code, title in CATEGORIES}

# -------------------- Статусы --------------------
STATUS_LABEL = {
    "new": "🔵 Новое",
    "in_work": "🟡 В работе",
    "closed": "✅ Закрыто",
}

# -------------------- Память (без JSON) --------------------
@dataclass
class Attachment:
    kind: str  # photo|video|document|video_note|voice|audio
    file_id: str
    caption: str = ""

@dataclass
class Ticket:
    ticket_id: int
    status: str
    user_id: int
    username: Optional[str]
    full_name: str
    category: str
    text: str
    attachments: List[Attachment] = field(default_factory=list)
    group_message_id: Optional[int] = None
    created_at: str = ""

tickets: Dict[int, Ticket] = {}
ticket_counter = 0

# admin reply mode: admin_id -> ticket_id
REPLY_MODE: Dict[int, int] = {}

# -------------------- FSM --------------------
class Flow(StatesGroup):
    choosing_category = State()
    collecting = State()      # можно слать текст и файлы
    confirming = State()      # подтверждение перед отправкой (и можно добавлять файлы)

# -------------------- UI клавиатуры --------------------
def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать обращение", callback_data="u:new")],
    ])

def kb_after_user() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новое обращение", callback_data="u:new")],
        [InlineKeyboardButton(text="🏠 В начало", callback_data="u:home")],
    ])

def kb_categories() -> InlineKeyboardMarkup:
    rows = []
    for code, title in CATEGORIES:
        rows.append([InlineKeyboardButton(text=title, callback_data=f"u:cat:{code}")])
    rows.append([InlineKeyboardButton(text="🏠 В начало", callback_data="u:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_collecting() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад (категории)", callback_data="u:back_cat")],
        [InlineKeyboardButton(text="🏠 В начало", callback_data="u:home")],
    ])

def kb_confirm(can_send: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_send:
        rows.append([InlineKeyboardButton(text="✅ Подтвердить и отправить", callback_data="u:send")])
    rows.append([InlineKeyboardButton(text="📎 Добавить файл", callback_data="u:add_file_tip")])
    rows.append([InlineKeyboardButton(text="✏️ Изменить текст", callback_data="u:edit_text")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад (категории)", callback_data="u:back_cat")])
    rows.append([InlineKeyboardButton(text="🏠 В начало", callback_data="u:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_admin(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 В работе", callback_data=f"a:work:{ticket_id}"),
            InlineKeyboardButton(text="✉️ Ответить", callback_data=f"a:reply:{ticket_id}"),
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"a:close:{ticket_id}"),
        ]
    ])

# -------------------- Helpers --------------------
def user_card(user_id: int, username: Optional[str], full_name: str) -> str:
    uname = f"@{username}" if username else "нет"
    link = f"tg://user?id={user_id}"
    return (
        f"👤 Пользователь: {full_name}\n"
        f"🆔 Telegram ID: {user_id}\n"
        f"👤 Username: {uname}\n"
        f"🔗 Написать: {link}"
    )

def render_ticket_text(t: Ticket) -> str:
    cat = CAT_TITLE.get(t.category, t.category)
    return (
        f"📩 ОБРАЩЕНИЕ #{t.ticket_id}\n"
        f"Статус: {STATUS_LABEL.get(t.status, t.status)}\n\n"
        f"{user_card(t.user_id, t.username, t.full_name)}\n\n"
        f"📌 Категория: {cat}\n\n"
        f"💬 Сообщение:\n{t.text}"
    )

def extract_attachment(msg: Message) -> Optional[Attachment]:
    # ловим основные типы
    if msg.photo:
        return Attachment(kind="photo", file_id=msg.photo[-1].file_id, caption=msg.caption or "")
    if msg.video:
        return Attachment(kind="video", file_id=msg.video.file_id, caption=msg.caption or "")
    if msg.document:
        return Attachment(kind="document", file_id=msg.document.file_id, caption=msg.caption or "")
    if msg.video_note:
        return Attachment(kind="video_note", file_id=msg.video_note.file_id, caption=msg.caption or "")
    if msg.voice:
        return Attachment(kind="voice", file_id=msg.voice.file_id, caption=msg.caption or "")
    if msg.audio:
        return Attachment(kind="audio", file_id=msg.audio.file_id, caption=msg.caption or "")
    return None

async def add_att(state: FSMContext, att: Attachment) -> bool:
    data = await state.get_data()
    atts: List[Attachment] = data.get("attachments", [])
    if len(atts) >= MAX_ATTACHMENTS:
        return False
    atts.append(att)
    await state.update_data(attachments=atts)
    return True

def atts_count(data: dict) -> int:
    return len(data.get("attachments", []) or [])

def confirm_text(data: dict) -> str:
    cat_code = data.get("category")
    cat = CAT_TITLE.get(cat_code, cat_code or "—")
    text = data.get("text") or ""
    cnt = atts_count(data)
    parts = [
        "🧾 Проверьте обращение перед отправкой:",
        f"📌 Категория: {cat}",
        f"💬 Текст: {text if text else '—'}",
        f"📎 Вложения: {cnt}",
        "",
        "Если всё верно — нажмите «✅ Подтвердить и отправить».",
    ]
    return "\n".join(parts)

# -------------------- Router --------------------
router = Router()

# -------------------- Пользователь --------------------
@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте.\n\n"
        "🤖 Служба поддержки\n"
        "Нажмите «➕ Создать обращение», чтобы написать в поддержку.",
        reply_markup=kb_start()
    )

@router.callback_query(F.data == "u:home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🏠 Главное меню\n\nНажмите «➕ Создать обращение».",
        reply_markup=kb_start()
    )
    await call.answer()

@router.callback_query(F.data == "u:new")
async def new_ticket(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Flow.choosing_category)
    await call.message.edit_text("📌 Выберите категорию обращения:", reply_markup=kb_categories())
    await call.answer()

@router.callback_query(Flow.choosing_category, F.data.startswith("u:cat:"))
async def pick_category(call: CallbackQuery, state: FSMContext):
    cat = call.data.split(":")[-1]
    if cat not in CAT_TITLE:
        await call.answer("Неизвестная категория", show_alert=True)
        return

    await state.update_data(category=cat, text=None, attachments=[])
    await state.set_state(Flow.collecting)

    await call.message.edit_text(
        f"✅ Категория: {CAT_TITLE[cat]}\n\n"
        "✍️ Отправьте описание одним сообщением.\n"
        "📎 При необходимости можете сразу отправлять скриншот/видео/файл (до 5 вложений).\n\n"
        "Когда будете готовы — мы покажем экран подтверждения перед отправкой.",
        reply_markup=kb_collecting()
    )
    await call.answer()

@router.callback_query(F.data == "u:back_cat")
async def back_to_categories(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Flow.choosing_category)
    await call.message.edit_text("📌 Выберите категорию обращения:", reply_markup=kb_categories())
    await call.answer()

# В collecting: ловим текст и вложения (в любой последовательности)
@router.message(Flow.collecting)
async def collecting_any(message: Message, state: FSMContext):
    data = await state.get_data()

    # 1) вложение
    att = extract_attachment(message)
    if att:
        ok = await add_att(state, att)
        if not ok:
            await message.answer(f"⚠️ Можно прикрепить не более {MAX_ATTACHMENTS} файлов.")
            return

        data = await state.get_data()
        # если текст уже есть — можно перейти к подтверждению
        if data.get("text"):
            await state.set_state(Flow.confirming)
            await message.answer(confirm_text(data), reply_markup=kb_confirm(can_send=True))
        else:
            await message.answer("📎 Вложение добавлено. Теперь отправьте текст с описанием.")
        return

    # 2) текст
    if message.text and message.text.strip():
        await state.update_data(text=message.text.strip())
        data = await state.get_data()
        await state.set_state(Flow.confirming)
        await message.answer(confirm_text(data), reply_markup=kb_confirm(can_send=True))
        return

    await message.answer("Пожалуйста, отправьте текст описания или вложение (скрин/видео/файл).")

# В confirming: можно добавлять вложения, менять текст, и подтвердить отправку
@router.callback_query(Flow.confirming, F.data == "u:add_file_tip")
async def add_file_tip(call: CallbackQuery):
    await call.answer()
    await call.message.answer("📎 Пришлите файл (скриншот/видео/документ). Затем вернёмся к подтверждению.")

@router.callback_query(Flow.confirming, F.data == "u:edit_text")
async def edit_text(call: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.collecting)
    data = await state.get_data()
    cat = CAT_TITLE.get(data.get("category"), "—")
    await call.message.answer(
        f"✍️ Изменение текста\n\nКатегория: {cat}\n"
        "Отправьте новый текст описания. (Вложения сохранятся.)",
        reply_markup=kb_collecting()
    )
    await call.answer()

@router.message(Flow.confirming)
async def confirming_any(message: Message, state: FSMContext):
    # если прислали вложение на подтверждении — добавим и обновим подтверждение
    att = extract_attachment(message)
    if att:
        ok = await add_att(state, att)
        if not ok:
            await message.answer(f"⚠️ Можно прикрепить не более {MAX_ATTACHMENTS} файлов.")
            return
        data = await state.get_data()
        await message.answer("📎 Вложение добавлено.")
        await message.answer(confirm_text(data), reply_markup=kb_confirm(can_send=bool(data.get("text"))))
        return

    # если прислали новый текст на подтверждении — обновим и тоже подтверждение покажем
    if message.text and message.text.strip():
        await state.update_data(text=message.text.strip())
        data = await state.get_data()
        await message.answer("✍️ Текст обновлён.")
        await message.answer(confirm_text(data), reply_markup=kb_confirm(can_send=True))
        return

    await message.answer("Отправьте текст или вложение, либо нажмите кнопку на экране подтверждения.")

@router.callback_query(Flow.confirming, F.data == "u:send")
async def send_ticket(call: CallbackQuery, state: FSMContext, bot: Bot):
    global ticket_counter

    data = await state.get_data()
    cat = data.get("category")
    text = data.get("text")

    if not cat or not text:
        await call.answer("Не хватает данных: выберите категорию и напишите текст.", show_alert=True)
        return

    ticket_counter += 1
    u = call.from_user
    atts: List[Attachment] = data.get("attachments", [])

    t = Ticket(
        ticket_id=ticket_counter,
        status="new",
        user_id=u.id,
        username=u.username,
        full_name=u.full_name or "Пользователь",
        category=cat,
        text=text,
        attachments=atts,
        created_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        group_message_id=None
    )
    tickets[t.ticket_id] = t

    # 1) отправляем карточку в группу
    sent = await bot.send_message(
        chat_id=SUPPORT_CHAT_ID,
        text=render_ticket_text(t),
        reply_markup=kb_admin(t.ticket_id)
    )
    t.group_message_id = sent.message_id

    # 2) отправляем вложения в группу (реплаем на карточку)
    for a in t.attachments:
        cap = a.caption or ""
        try:
            if a.kind == "photo":
                await bot.send_photo(SUPPORT_CHAT_ID, a.file_id, caption=cap or None, reply_to_message_id=sent.message_id)
            elif a.kind == "video":
                await bot.send_video(SUPPORT_CHAT_ID, a.file_id, caption=cap or None, reply_to_message_id=sent.message_id)
            elif a.kind == "document":
                await bot.send_document(SUPPORT_CHAT_ID, a.file_id, caption=cap or None, reply_to_message_id=sent.message_id)
            elif a.kind == "video_note":
                await bot.send_video_note(SUPPORT_CHAT_ID, a.file_id, reply_to_message_id=sent.message_id)
            elif a.kind == "voice":
                await bot.send_voice(SUPPORT_CHAT_ID, a.file_id, caption=cap or None, reply_to_message_id=sent.message_id)
            elif a.kind == "audio":
                await bot.send_audio(SUPPORT_CHAT_ID, a.file_id, caption=cap or None, reply_to_message_id=sent.message_id)
        except Exception:
            await bot.send_message(SUPPORT_CHAT_ID, f"⚠️ Не удалось отправить вложение к обращению #{t.ticket_id} (тип: {a.kind}).")

    # 3) ответ пользователю
    await state.clear()
    await call.message.edit_text(
        "✅ Обращение принято.\n"
        "Мы свяжемся с вами в ближайшее время.",
        reply_markup=kb_after_user()
    )
    await call.answer()

# -------------------- Админ (кнопки в группе) --------------------
async def update_group_card(bot: Bot, t: Ticket):
    if not t.group_message_id:
        return
    try:
        await bot.edit_message_text(
            chat_id=SUPPORT_CHAT_ID,
            message_id=t.group_message_id,
            text=render_ticket_text(t),
            reply_markup=kb_admin(t.ticket_id)
        )
    except Exception:
        # если нельзя отредактировать — ничего страшного (например, сообщение слишком старое)
        pass

@router.callback_query(F.data.startswith("a:work:"))
async def admin_work(call: CallbackQuery, bot: Bot):
    tid = int(call.data.split(":")[-1])
    t = tickets.get(tid)
    if not t:
        await call.answer("Тикет не найден", show_alert=True)
        return
    if t.status == "closed":
        await call.answer("Тикет уже закрыт", show_alert=True)
        return

    t.status = "in_work"
    await update_group_card(bot, t)
    await call.answer("Статус: В работе")

@router.callback_query(F.data.startswith("a:close:"))
async def admin_close(call: CallbackQuery, bot: Bot):
    tid = int(call.data.split(":")[-1])
    t = tickets.get(tid)
    if not t:
        await call.answer("Тикет не найден", show_alert=True)
        return

    t.status = "closed"
    await update_group_card(bot, t)

    # Сообщение пользователю — корректное, деловое
    try:
        await bot.send_message(
            chat_id=t.user_id,
            text=(
                "✅ Мы завершили обработку вашего обращения.\n"
                "Если потребуется помощь — создайте новое обращение."
            ),
            reply_markup=kb_after_user()
        )
    except Exception:
        pass

    await call.answer("Закрыто")

@router.callback_query(F.data.startswith("a:reply:"))
async def admin_reply(call: CallbackQuery):
    tid = int(call.data.split(":")[-1])
    t = tickets.get(tid)
    if not t:
        await call.answer("Тикет не найден", show_alert=True)
        return
    if t.status == "closed":
        await call.answer("Тикет закрыт. Ответить нельзя.", show_alert=True)
        return

    REPLY_MODE[call.from_user.id] = tid
    await call.answer()
    await call.message.reply(
        f"✉️ Ответ пользователю по обращению #{tid}\n"
        "Отправьте следующим сообщением текст или файл (фото/видео/документ)."
    )

# Ловим сообщения в группе и отправляем пользователю, если админ в режиме ответа
@router.message(F.chat.id == SUPPORT_CHAT_ID)
async def group_messages(message: Message, bot: Bot):
    admin_id = message.from_user.id
    if admin_id not in REPLY_MODE:
        return

    tid = REPLY_MODE.get(admin_id)
    t = tickets.get(tid)
    if not t:
        REPLY_MODE.pop(admin_id, None)
        await message.reply("⚠️ Тикет не найден. Режим ответа сброшен.")
        return

    try:
        header = "📩 Ответ от службы поддержки:"
        att = extract_attachment(message)

        if att:
            cap = (header + ("\n" + (message.caption or "") if (message.caption or "") else ""))
            if att.kind == "photo":
                await bot.send_photo(t.user_id, att.file_id, caption=cap, reply_markup=kb_after_user())
            elif att.kind == "video":
                await bot.send_video(t.user_id, att.file_id, caption=cap, reply_markup=kb_after_user())
            elif att.kind == "document":
                await bot.send_document(t.user_id, att.file_id, caption=cap, reply_markup=kb_after_user())
            elif att.kind == "video_note":
                await bot.send_message(t.user_id, header, reply_markup=kb_after_user())
                await bot.send_video_note(t.user_id, att.file_id)
            elif att.kind == "voice":
                await bot.send_voice(t.user_id, att.file_id, caption=cap, reply_markup=kb_after_user())
            elif att.kind == "audio":
                await bot.send_audio(t.user_id, att.file_id, caption=cap, reply_markup=kb_after_user())
        else:
            if message.text and not message.text.startswith("/"):
                await bot.send_message(
                    chat_id=t.user_id,
                    text=f"{header}\n\n{message.text}",
                    reply_markup=kb_after_user()
                )
            else:
                await message.reply("Отправьте текст или файл (не команду).")
                return

        # подтверждение в группе и сброс режима
        await message.reply("✅ Ответ отправлен пользователю.")
        REPLY_MODE.pop(admin_id, None)

        # Если уже в работе — оставляем. Если было новое — можно перевести в «В работе» автоматически (по желанию)
        if t.status == "new":
            t.status = "in_work"
            await update_group_card(bot, t)

    except Exception:
        await message.reply("⚠️ Не удалось отправить пользователю (возможно, он заблокировал бота).")
        REPLY_MODE.pop(admin_id, None)

# -------------------- MAIN --------------------
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
