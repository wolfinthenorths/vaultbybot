import asyncio
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)


BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if SUPPORT_CHAT_ID:
    SUPPORT_CHAT_ID = int(SUPPORT_CHAT_ID)


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ---------------- ССЫЛКИ НА ДОКУМЕНТЫ ----------------

LINK_SETTING = "https://telegra.ph/Setting-12-28-5"
LINK_PLOT = "https://telegra.ph/Main-plot-12-28"
LINK_CLASSIFICATION = "https://example.com/classification"
LINK_RULES = "https://telegra.ph/Rules-12-28-96"
LINK_FAQ = "https://telegra.ph/FAQ-08-03-25"

LINK_VAULTS = "https://example.com/vaults"

LINK_MISSISSIPPI = "https://example.com/mississippi"
LINK_LOUISIANA = "https://example.com/louisiana"
LINK_EAST_TEXAS = "https://example.com/east-texas"
LINK_WEST_TEXAS = "https://example.com/west-texas"

LINK_PROJECT_GUIDE = "https://example.com/project-guide"
LINK_DND_GUIDE = "https://example.com/dnd-guide"


# ---------------- БАЗА ДЛЯ СВЯЗИ СООБЩЕНИЙ ----------------

conn = sqlite3.connect("support_messages.db")
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS message_map (
        support_message_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT
    )
    """
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS acknowledged_users (
        user_id INTEGER PRIMARY KEY,
        created_at TEXT
    )
    """
)

conn.commit()


def save_message_map(support_message_id: int, user_id: int):
    cursor.execute(
        """
        INSERT OR REPLACE INTO message_map
        (support_message_id, user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (
            support_message_id,
            user_id,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def get_user_id_by_support_message(support_message_id: int):
    cursor.execute(
        "SELECT user_id FROM message_map WHERE support_message_id = ?",
        (support_message_id,),
    )
    result = cursor.fetchone()
    return result[0] if result else None


def load_acknowledged_users():
    cursor.execute("SELECT user_id FROM acknowledged_users")
    rows = cursor.fetchall()
    return {row[0] for row in rows}


ACKNOWLEDGED_USERS = load_acknowledged_users()


def should_send_first_message_reply(user_id: int) -> bool:
    if user_id in ACKNOWLEDGED_USERS:
        return False

    ACKNOWLEDGED_USERS.add(user_id)

    cursor.execute(
        """
        INSERT OR REPLACE INTO acknowledged_users
        (user_id, created_at)
        VALUES (?, ?)
        """,
        (
            user_id,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()

    return True


# ---------------- ТЕКСТЫ ----------------

WELCOME_TEXT = (
    "Привет! Я — Волт-Бой на Вашем наручном компьютере "
    "и по совместительству Ваш главный помощник по выживанию "
    "и построению счастливой жизни в этом мире.\n\n"
    "Чтобы забронировать роль, напишите её сообщением "
    "или задайте интересующий вопрос — я помогу не хуже "
    "синта третьего поколения!"
)


FIRST_MESSAGE_REPLY = (
    "Ваше сообщение передано Волт-Бою 🫡\n"
    "Мы ответим вам здесь, в этом чате."
)


# ---------------- МЕНЮ ----------------

def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 Основная информация",
                    callback_data="menu_info",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Документы для написания биографии",
                    callback_data="menu_bio",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Гайды",
                    callback_data="menu_guides",
                )
            ],
        ]
    )


def info_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌍 Сеттинг",
                    url=LINK_SETTING,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📖 Сюжет",
                    url=LINK_PLOT,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Классификация",
                    url=LINK_CLASSIFICATION,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚖️ Правила",
                    url=LINK_RULES,
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ FAQ",
                    url=LINK_FAQ,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu_main",
                )
            ],
        ]
    )


def bio_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Описание бункеров",
                    url=LINK_VAULTS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏜 Описание пустоши",
                    callback_data="menu_wasteland",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu_main",
                )
            ],
        ]
    )


def wasteland_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📍 Миссисипи",
                    url=LINK_MISSISSIPPI,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Луизиана",
                    url=LINK_LOUISIANA,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Восточный Техас",
                    url=LINK_EAST_TEXAS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Западный Техас",
                    url=LINK_WEST_TEXAS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu_bio",
                )
            ],
        ]
    )


def guides_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📘 Гайд по проекту",
                    url=LINK_PROJECT_GUIDE,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎲 Гайд по ДнД",
                    url=LINK_DND_GUIDE,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu_main",
                )
            ],
        ]
    )


# ---------------- КОМАНДЫ ----------------

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu())


@dp.message(Command("info"))
async def info_command(message: Message):
    await message.answer(
        "Выберите нужный раздел:",
        reply_markup=main_menu(),
    )


@dp.message(Command("chatid"))
async def chat_id_command(message: Message):
    await message.answer(f"ID этого чата: {message.chat.id}")


# ---------------- НАЖАТИЯ НА КНОПКИ МЕНЮ ----------------

@dp.callback_query(F.data == "menu_main")
async def open_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_info")
async def open_info_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📌 Основная информация:",
        reply_markup=info_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_bio")
async def open_bio_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📝 Документы для написания биографии:",
        reply_markup=bio_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_wasteland")
async def open_wasteland_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏜 Описание пустоши:",
        reply_markup=wasteland_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_guides")
async def open_guides_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📚 Гайды:",
        reply_markup=guides_menu(),
    )
    await callback.answer()


# ---------------- ОТВЕТ ИЗ ЧАТА ПОДДЕРЖКИ ПОЛЬЗОВАТЕЛЮ ----------------

@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def answer_from_support_chat(message: Message):
    if not SUPPORT_CHAT_ID:
        return

    if message.chat.id != SUPPORT_CHAT_ID:
        return

    if not message.reply_to_message:
        return

    user_id = get_user_id_by_support_message(message.reply_to_message.message_id)

    if not user_id:
        return

    try:
        if message.text:
            await bot.send_message(
                chat_id=user_id,
                text=message.text,
            )
        else:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )

        await message.reply("✅ Ответ отправлен пользователю.")

    except TelegramForbiddenError:
        await message.reply(
            "❌ Не получилось отправить ответ: пользователь заблокировал бота."
        )


# ---------------- СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ В БОТА ----------------

@dp.message(F.chat.type == ChatType.PRIVATE)
async def message_from_user(message: Message):
    if not SUPPORT_CHAT_ID:
        return

    user = message.from_user

    username = f"@{user.username}" if user.username else "без username"
    full_name = user.full_name or "без имени"

    user_info = (
        f"👤 Пользователь: {full_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: {user.id}"
    )

    header = await bot.send_message(
        chat_id=SUPPORT_CHAT_ID,
        text=(
            "📩 Новое сообщение в бота\n\n"
            f"{user_info}\n\n"
            "Ответьте на это сообщение через Reply, "
            "чтобы ответ ушёл пользователю обратно в бота."
        ),
    )

    save_message_map(header.message_id, user.id)

    if message.text:
        copied = await bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            text=f"💬 Сообщение пользователя:\n\n{message.text}",
        )
    else:
        copied = await bot.copy_message(
            chat_id=SUPPORT_CHAT_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )

    save_message_map(copied.message_id, user.id)

    if should_send_first_message_reply(user.id):
        await message.answer(FIRST_MESSAGE_REPLY)


# ---------------- ЗАПУСК БОТА ----------------

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
