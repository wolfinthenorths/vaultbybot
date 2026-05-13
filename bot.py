import asyncio
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.exceptions import TelegramForbiddenError


BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if SUPPORT_CHAT_ID:
    SUPPORT_CHAT_ID = int(SUPPORT_CHAT_ID)


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ---------- База для связи сообщений ----------
conn = sqlite3.connect("support_messages.db")
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS message_map (
        support_message_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        user_info TEXT,
        created_at TEXT
    )
    """
)
conn.commit()


def save_message_map(support_message_id: int, user_id: int, user_info: str):
    cursor.execute(
        """
        INSERT OR REPLACE INTO message_map 
        (support_message_id, user_id, user_info, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            support_message_id,
            user_id,
            user_info,
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


# ---------- Кнопки ----------
def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 О проекте",
                    url="https://t.me/dawnofthed3ad",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📄 Основная информация",
                    url="https://example.com/main-info",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Документы проекта",
                    url="https://example.com/documents",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Частые вопросы",
                    url="https://example.com/faq",
                )
            ],
        ]
    )


WELCOME_TEXT = (
    "Привет! Я — Волт-Бой, Ваш главный помощник по выживанию "
    "и формированию счастливой жизни в этом мире.\n\n"
    "Можете написать желаемую роль или задать любой интересующий вопрос, "
    "а я помогу не хуже наручного Пип-Боя!\n\n"
    "Ознакомиться с самим проектом можно здесь: @dawnofthed3ad"
)


# ---------- Команды ----------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_keyboard())


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Напишите сюда желаемую роль или любой вопрос — я передам сообщение администрации проекта.\n\n"
        "Также можно открыть основную информацию по кнопкам ниже.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("info"))
async def info_command(message: Message):
    await message.answer(
        "Основная информация по проекту:",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("chatid"))
async def chat_id_command(message: Message):
    await message.answer(f"ID этого чата: {message.chat.id}")


# ---------- Ответ из чата поддержки пользователю ----------
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


# ---------- Сообщение от пользователя в бота ----------
@dp.message(F.chat.type == ChatType.PRIVATE)
async def message_from_user(message: Message):
    if not SUPPORT_CHAT_ID:
        await message.answer(
            "Сообщение принято, но чат поддержки пока не подключён."
        )
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

    save_message_map(
        support_message_id=header.message_id,
        user_id=user.id,
        user_info=user_info,
    )

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

    save_message_map(
        support_message_id=copied.message_id,
        user_id=user.id,
        user_info=user_info,
    )

    await message.answer(
        "Ваше сообщение передано Волт-Бою 🫡\n"
        "Мы ответим вам здесь, в этом чате."
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
