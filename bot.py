import os
import json
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from dotenv import load_dotenv


# =========================
# CONFIG
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID_RAW = os.getenv("SUPPORT_CHAT_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Добавь BOT_TOKEN в Environment Variables на Render.")

if not SUPPORT_CHAT_ID_RAW:
    raise RuntimeError("Не задан SUPPORT_CHAT_ID. Добавь SUPPORT_CHAT_ID (ID группы) в Environment Variables на Render.")

try:
    SUPPORT_CHAT_ID = int(SUPPORT_CHAT_ID_RAW)
except ValueError:
    raise RuntimeError("SUPPORT_CHAT_ID должен быть числом, например -1001234567890")

MAX_ATTACHMENTS = 5

DB_FILE = "tickets_db.json"  # простая база в файле (для Render обычно хватает; при новом деплое может сброситься)


# =========================
# CATEGORIES (настройка)
# =========================
CATEGORIES = [
    ("bug", "🐞 Баг"),
    ("question", "❓ Вопрос"),
    ("suggestion", "💡 Предложение"),
    ("payment", "💳 Оплата"),
    ("login", "🔐 Вход"),
    ("other", "🧩 Другое"),
]

CATEGORY_MAP = {k: v for k, v in CATEGORIES}


# =========================
# STATES
# =========================
class TicketStates(StatesGroup):
    category = State()
    details = State()


class SupportStates(StatesGroup):
    waiting_reply = State()


# =========================
# SIMPLE DB
# =========================
def _db_load() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        return {"seq": 0, "tickets": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seq": 0, "tickets": {}}


def _db_save(db: Dict[str, Any]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def db_new_ticket(payload: Dict[str, Any]) -> int:
    db = _db_load()
    db["seq"] += 1
    ticket_id = db["seq"]
    db["tickets"][str(ticket_id)] = payload
    _db_save(db)
    return ticket_id


def db_get_ticket(ticket_id: int) -> Optional[Dict[str, Any]]:
    db = _db_load()
    return db["tickets"].get(str(ticket_id))


def db_update_ticket(ticket_id: int, patch: Dict[str, Any]) -> None:
    db = _db_load()
    t = db["tickets"].get(str(ticket_id))
    if not t:
        return
    t.update(patch)
    db["tickets"][str(ticket_id)] = t
    _db_save(db)


# =========================
# KEYBOARDS
# =========================
def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новое обращение", callback_data="ticket:new")],
        [InlineKeyboardButton(text="🏠 В начало", callback_data="ticket:home")],
    ])


def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать обращение", callback_data="ticket:new")],
    ])


def kb_categories() -> InlineKeyboardMarkup:
    rows = []
    for k, title in CATEGORIES:
        rows.append([InlineKeyboardButton(text=title, callback_data=f"ticket:cat:{k}")])
    rows.append([InlineKeyboardButton(text="🏠 В начало", callback_data="ticket:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_details_actions(can_submit: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_submit:
        rows.append([InlineKeyboardButton(text="✅ Отправить обращение", callback_data="ticket:submit")])
    rows.append([InlineKeyboardButton(text="📎 Добавить файл (скрин/видео)", callback_data="ticket:addfile")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад (выбор темы)", callback_data="ticket:back")])
    rows.append([InlineKeyboardButton(text="🏠 В начало", callback_data="ticket:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_support_actions(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 В работе", callback_data=f"support:inwork:{ticket_id}"),
            InlineKeyboardButton(text="✉️ Ответить", callback_data=f"support:reply:{ticket_id}"),
        ],
        [
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"support:close:{ticket_id}")
        ]
    ])


# =========================
# HELPERS
# =========================
def user_contact_block(user: Message) -> str:
    u = user.from_user
    username = f"@{u.username}" if u.username else "нет"
    tg_link = f"https://t.me/{u.username}" if u.username else f"tg://user?id={u.id}"
    return (
        f"👤 Пользователь: {u.full_name}\n"
        f"🆔 Telegram ID: {u.id}\n"
        f"👤 Username: {username}\n"
        f"🔗 Написать: {tg_link}"
    )


async def add_attachment(state: FSMContext, att_type: str, file_id: str) -> bool:
    data = await state.get_data()
    attachments = data.get("attachments", [])
    if len(attachments) >= MAX_ATTACHMENTS:
        return False
    attachments.append({"type": att_type, "file_id": file_id})
    await state.update_data(attachments=attachments)
    return True


def attachments_count(data: Dict[str, Any]) -> int:
    return len(data.get("attachments", []))


# =========================
# ROUTER
# =========================
router = Router()


# -------------------------
# START / HOME
# -------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 Здравствуйте.\n\n"
        "Это служба поддержки. Здесь можно быстро создать обращение по приложению.\n"
        "Нажмите кнопку ниже, чтобы начать."
    )
    await message.answer(text, reply_markup=kb_start())


@router.callback_query(F.data == "ticket:home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🏠 Главное меню\n\nНажмите «Создать обращение», чтобы написать в поддержку.",
        reply_markup=kb_start()
    )
    await call.answer()


@router.callback_query(F.data == "ticket:new")
async def cb_new(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TicketStates.category)
    await call.message.edit_text(
        "📌 Выберите тему обращения:",
        reply_markup=kb_categories()
    )
    await call.answer()


# -------------------------
# CATEGORY CHOICE
# -------------------------
@router.callback_query(TicketStates.category, F.data.startswith("ticket:cat:"))
async def cb_category(call: CallbackQuery, state: FSMContext):
    cat_key = call.data.split(":")[-1]
    if cat_key not in CATEGORY_MAP:
        await call.answer("Неизвестная категория", show_alert=True)
        return

    await state.update_data(category=cat_key, details=None, attachments=[])
    await state.set_state(TicketStates.details)

    await call.message.edit_text(
        f"✅ Тема: {CATEGORY_MAP[cat_key]}\n\n"
        "Опишите ситуацию одним сообщением.\n"
        "Если есть скрин/видео — можете отправить сразу (можно до 5 файлов).",
        reply_markup=kb_details_actions(can_submit=False)
    )
    await call.answer()


@router.callback_query(TicketStates.details, F.data == "ticket:back")
async def cb_back(call: CallbackQuery, state: FSMContext):
    # Разрешаем сменить категорию только через "Назад"
    await state.update_data(category=None, details=None, attachments=[])
    await state.set_state(TicketStates.category)
    await call.message.edit_text("📌 Выберите тему обращения:", reply_markup=kb_categories())
    await call.answer()


# -------------------------
# DETAILS: "add file" button (подсказка)
# -------------------------
@router.callback_query(TicketStates.details, F.data == "ticket:addfile")
async def cb_add_file(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("📎 Пришлите файл (скриншот / видео / документ). Можно до 5 файлов.")


# -------------------------
# DETAILS: attachments handlers (фикс твоей проблемы)
# Принимаем файлы в любой момент, пока собираем обращение
# -------------------------
@router.message(TicketStates.details, F.photo)
async def details_photo(message: Message, state: FSMContext):
    ok = await add_attachment(state, "photo", message.photo[-1].file_id)
    if not ok:
        await message.answer("⚠️ Можно прикрепить не более 5 файлов.")
        return

    data = await state.get_data()
    can_submit = bool(data.get("details"))
    if can_submit:
        await message.answer("📎 Файл добавлен. Можно отправить обращение или добавить ещё.", reply_markup=kb_details_actions(True))
    else:
        await message.answer("📎 Файл получен. Теперь опишите ситуацию текстом.", reply_markup=kb_details_actions(False))


@router.message(TicketStates.details, F.video)
async def details_video(message: Message, state: FSMContext):
    ok = await add_attachment(state, "video", message.video.file_id)
    if not ok:
        await message.answer("⚠️ Можно прикрепить не более 5 файлов.")
        return

    data = await state.get_data()
    can_submit = bool(data.get("details"))
    if can_submit:
        await message.answer("📎 Видео добавлено. Можно отправить обращение или добавить ещё.", reply_markup=kb_details_actions(True))
    else:
        await message.answer("📎 Видео получено. Теперь опишите ситуацию текстом.", reply_markup=kb_details_actions(False))


@router.message(TicketStates.details, F.document)
async def details_document(message: Message, state: FSMContext):
    ok = await add_attachment(state, "document", message.document.file_id)
    if not ok:
        await message.answer("⚠️ Можно прикрепить не более 5 файлов.")
        return

    data = await state.get_data()
    can_submit = bool(data.get("details"))
    if can_submit:
        await message.answer("📎 Файл добавлен. Можно отправить обращение или добавить ещё.", reply_markup=kb_details_actions(True))
    else:
        await message.answer("📎 Файл получен. Теперь опишите ситуацию текстом.", reply_markup=kb_details_actions(False))


# -------------------------
# DETAILS: text handler
# -------------------------
@router.message(TicketStates.details, F.text)
async def details_text(message: Message, state: FSMContext):
    txt = message.text.strip()
    if not txt:
        await message.answer("Пожалуйста, напишите описание текстом.")
        return

    await state.update_data(details=txt)
    data = await state.get_data()

    att_cnt = attachments_count(data)
    if att_cnt > 0:
        msg = f"✅ Текст сохранён. Прикреплено файлов: {att_cnt}.\n\nМожете отправить обращение."
    else:
        msg = "✅ Текст сохранён.\n\nЕсли нужно — прикрепите скрин/видео, либо сразу отправьте обращение."

    await message.answer(msg, reply_markup=kb_details_actions(can_submit=True))


# -------------------------
# SUBMIT TICKET
# -------------------------
@router.callback_query(TicketStates.details, F.data == "ticket:submit")
async def cb_submit(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()

    cat_key = data.get("category")
    details = data.get("details")
    if not cat_key or not details:
        await call.answer("Нужно выбрать тему и написать описание.", show_alert=True)
        return

    now = datetime.utcnow().isoformat()

    # создаём тикет
    ticket_payload = {
        "created_at": now,
        "status": "new",
        "category": cat_key,
        "details": details,
        "attachments": data.get("attachments", []),
        "user_id": call.from_user.id,
        "username": call.from_user.username,
        "full_name": call.from_user.full_name,
        "support_msg_id": None,
    }
    ticket_id = db_new_ticket(ticket_payload)

    # 1) сообщение в поддержку (группу)
    username = f"@{call.from_user.username}" if call.from_user.username else "нет"
    tg_link = f"https://t.me/{call.from_user.username}" if call.from_user.username else f"tg://user?id={call.from_user.id}"

    support_text = (
        f"📩 ОБРАЩЕНИЕ #{ticket_id}\n"
        f"Статус: 🔵 Новое\n\n"
        f"{user_contact_block(call.message)}\n\n"
        f"📌 Тема: {CATEGORY_MAP.get(cat_key, cat_key)}\n\n"
        f"💬 Сообщение:\n{details}\n\n"
        f"👤 Username: {username}\n"
        f"🔗 Ссылка: {tg_link}"
    )

    sent = await bot.send_message(
        chat_id=SUPPORT_CHAT_ID,
        text=support_text,
        reply_markup=kb_support_actions(ticket_id)
    )

    # 2) отправка вложений в поддержку
    attachments = data.get("attachments", [])
    if attachments:
        for att in attachments:
            at = att.get("type")
            fid = att.get("file_id")
            caption = f"📎 Вложение к обращению #{ticket_id}"
            try:
                if at == "photo":
                    await bot.send_photo(SUPPORT_CHAT_ID, fid, caption=caption)
                elif at == "video":
                    await bot.send_video(SUPPORT_CHAT_ID, fid, caption=caption)
                elif at == "document":
                    await bot.send_document(SUPPORT_CHAT_ID, fid, caption=caption)
            except Exception:
                # если файл не отправился — не ломаем процесс
                await bot.send_message(SUPPORT_CHAT_ID, f"⚠️ Не удалось отправить вложение к обращению #{ticket_id} (тип: {at}).")

    db_update_ticket(ticket_id, {"support_msg_id": sent.message_id})

    # 3) ответ пользователю (нормально, делово)
    await call.message.edit_text(
        "✅ Обращение принято.\n"
        "Мы свяжемся с вами в ближайшее время в этом чате.",
        reply_markup=kb_home()
    )

    await state.clear()
    await call.answer()


# =========================
# SUPPORT SIDE (GROUP)
# =========================
# Вариант управления в группе:
# - 🟡 В работе: меняем статус, редактируем сообщение в группе
# - ✉️ Ответить: бот попросит текст ответа (следующее сообщение поддержки станет ответом)
# - ✅ Закрыть: уведомляем пользователя и закрываем тикет
#
# ВАЖНО: Чтобы бот работал в группе, добавь его как администратора и /setprivacy -> Disable


def _render_support_text(ticket_id: int, ticket: Dict[str, Any]) -> str:
    status = ticket.get("status", "new")
    status_label = {
        "new": "🔵 Новое",
        "in_work": "🟡 В работе",
        "closed": "✅ Закрыто",
    }.get(status, status)

    cat = ticket.get("category", "other")
    details = ticket.get("details", "")

    username = f"@{ticket.get('username')}" if ticket.get("username") else "нет"
    user_id = ticket.get("user_id")
    tg_link = f"https://t.me/{ticket.get('username')}" if ticket.get("username") else f"tg://user?id={user_id}"

    return (
        f"📩 ОБРАЩЕНИЕ #{ticket_id}\n"
        f"Статус: {status_label}\n\n"
        f"👤 Пользователь: {ticket.get('full_name','')}\n"
        f"🆔 Telegram ID: {user_id}\n"
        f"👤 Username: {username}\n"
        f"🔗 Написать: {tg_link}\n\n"
        f"📌 Тема: {CATEGORY_MAP.get(cat, cat)}\n\n"
        f"💬 Сообщение:\n{details}"
    )


@router.callback_query(F.data.startswith("support:inwork:"))
async def support_in_work(call: CallbackQuery, bot: Bot):
    ticket_id = int(call.data.split(":")[-1])
    ticket = db_get_ticket(ticket_id)
    if not ticket:
        await call.answer("Тикет не найден", show_alert=True)
        return

    if ticket.get("status") == "closed":
        await call.answer("Тикет уже закрыт", show_alert=True)
        return

    db_update_ticket(ticket_id, {"status": "in_work"})
    ticket = db_get_ticket(ticket_id)

    # редактируем сообщение в группе
    try:
        await call.message.edit_text(_render_support_text(ticket_id, ticket), reply_markup=kb_support_actions(ticket_id))
    except Exception:
        pass

    await call.answer("Статус: В работе")


@router.callback_query(F.data.startswith("support:reply:"))
async def support_reply_start(call: CallbackQuery, state: FSMContext):
    ticket_id = int(call.data.split(":")[-1])
    ticket = db_get_ticket(ticket_id)
    if not ticket:
        await call.answer("Тикет не найден", show_alert=True)
        return

    if ticket.get("status") == "closed":
        await call.answer("Тикет закрыт. Ответить нельзя.", show_alert=True)
        return

    # Ставим состояние для сотрудника (кто нажал кнопку)
    await state.set_state(SupportStates.waiting_reply)
    await state.update_data(reply_ticket_id=ticket_id)

    await call.message.answer(
        f"✉️ Ответ пользователю по обращению #{ticket_id}\n"
        "Напишите текст ответа одним сообщением."
    )
    await call.answer()


@router.message(SupportStates.waiting_reply, F.text)
async def support_reply_send(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    if not ticket_id:
        await state.clear()
        return

    ticket = db_get_ticket(int(ticket_id))
    if not ticket:
        await message.answer("Тикет не найден.")
        await state.clear()
        return

    user_id = ticket.get("user_id")
    if not user_id:
        await message.answer("Не найден user_id у тикета.")
        await state.clear()
        return

    text = message.text.strip()
    if not text:
        await message.answer("Пустой ответ. Напишите текст.")
        return

    # сообщение пользователю (не сырое)
    user_msg = (
        f"📬 Ответ по вашему обращению #{ticket_id}:\n"
        f"{text}\n\n"
        "Если вопрос ещё актуален — можете создать новое обращение."
    )

    try:
        await bot.send_message(chat_id=int(user_id), text=user_msg, reply_markup=kb_home())
    except Exception:
        await message.answer("⚠️ Не удалось отправить пользователю (возможно, он заблокировал бота).")
        await state.clear()
        return

    # фиксируем статус
    db_update_ticket(int(ticket_id), {"status": "in_work", "last_reply_at": datetime.utcnow().isoformat()})

    await message.answer(f"✅ Ответ отправлен пользователю по обращению #{ticket_id}.")
    await state.clear()


@router.callback_query(F.data.startswith("support:close:"))
async def support_close(call: CallbackQuery, bot: Bot):
    ticket_id = int(call.data.split(":")[-1])
    ticket = db_get_ticket(ticket_id)
    if not ticket:
        await call.answer("Тикет не найден", show_alert=True)
        return

    if ticket.get("status") == "closed":
        await call.answer("Тикет уже закрыт", show_alert=True)
        return

    db_update_ticket(ticket_id, {"status": "closed", "closed_at": datetime.utcnow().isoformat()})
    ticket = db_get_ticket(ticket_id)

    # уведомляем пользователя (нормально, без “обращение закрыто” как ошибка)
    user_id = ticket.get("user_id")
    if user_id:
        try:
            await bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"✅ Мы завершили обработку обращения #{ticket_id}.\n"
                    "Если потребуется дополнительная помощь — создайте новое обращение."
                ),
                reply_markup=kb_home()
            )
        except Exception:
            pass

    # редактируем сообщение в группе
    try:
        await call.message.edit_text(_render_support_text(ticket_id, ticket), reply_markup=kb_support_actions(ticket_id))
    except Exception:
        pass

    await call.answer("Тикет закрыт")


# =========================
# OPTIONAL: Команда /set_support для группы (можно удалить потом)
# =========================
# Если ты хочешь НЕ через SUPPORT_CHAT_ID, а установить чат автоматически:
# 1) Включи Privacy Disable (BotFather)
# 2) Добавь бота в группу, напиши /set_support
# 3) Бот покажет ID группы (можно потом вставить в SUPPORT_CHAT_ID)
#
# --- ПОСЛЕ НАСТРОЙКИ МОЖЕШЬ УДАЛИТЬ ВЕСЬ БЛОК НИЖЕ ---
@router.message(Command("set_support"))
async def cmd_set_support(message: Message):
    # Работает только в группах
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в группе поддержки.")
        return

    await message.answer(
        f"✅ Группа поддержки установлена.\n"
        f"ID этой группы: `{message.chat.id}`\n\n"
        f"Добавь это число в Render → SUPPORT_CHAT_ID",
        parse_mode="Markdown"
    )
# --- КОНЕЦ БЛОКА /set_support ---


# =========================
# MAIN
# =========================
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    print("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
