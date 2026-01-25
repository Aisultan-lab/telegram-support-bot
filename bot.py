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
