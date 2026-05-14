import asyncio
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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


# ---------------- КАРТИНКА ДЛЯ ПРИВЕТСТВИЯ ----------------

WELCOME_IMAGE = "https://raw.githubusercontent.com/wolfinthenorths/vaultbybot/main/f603e39e58f392f60bad5.jpg"


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


# ---------------- ШАБЛОНЫ БЫСТРЫХ ОТВЕТОВ ----------------

TEMPLATES = {
    "booking": (
        "Здравствуйте! Поставили Вам бронь. "
        "Подскажите, имеются ли у Вас какие-то вопросы по проекту? "
        "Можем ли что-то подсказать?"
    ),
    "role_taken": (
        "Доброго времени! К сожалению, данная роль уже занята. "
        "Может, Вас интересует еще какой-нибудь персонаж?"
    ),
    "flood_question": "Желаете вступить во флуд сейчас или после написания анкеты?",
    "flood_welcome": "Добро пожаловать во флуд! х)\n\nhttps://t.me/+inO73ktQmbswNWQy",
}


# ---------------- БАЗА ДАННЫХ ----------------

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
    CREATE TABLE IF NOT EXISTS first_reply_sent (
        user_id INTEGER PRIMARY KEY,
        created_at TEXT
    )
    """
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS blocked_users (
        user_id INTEGER PRIMARY KEY,
        user_info TEXT,
        created_at TEXT
    )
    """
)

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id INTEGER PRIMARY KEY,
        user_info TEXT,
        updated_at TEXT
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


def save_user_profile(user_id: int, user_info: str):
    cursor.execute(
        """
        INSERT OR REPLACE INTO user_profiles
        (user_id, user_info, updated_at)
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            user_info,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def get_user_info(user_id: int) -> str:
    cursor.execute(
        "SELECT user_info FROM user_profiles WHERE user_id = ?",
        (user_id,),
    )
    result = cursor.fetchone()
    return result[0] if result else f"ID пользователя: {user_id}"


def should_send_first_message_reply(user_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM first_reply_sent WHERE user_id = ? LIMIT 1",
        (user_id,),
    )

    if cursor.fetchone() is not None:
        return False

    cursor.execute(
        """
        INSERT INTO first_reply_sent
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


def is_user_blocked(user_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM blocked_users WHERE user_id = ? LIMIT 1",
        (user_id,),
    )
    return cursor.fetchone() is not None


def block_user(user_id: int):
    user_info = get_user_info(user_id)

    cursor.execute(
        """
        INSERT OR REPLACE INTO blocked_users
        (user_id, user_info, created_at)
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            user_info,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def unblock_user(user_id: int):
    cursor.execute(
        "DELETE FROM blocked_users WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()


def get_blocked_users():
    cursor.execute(
        """
        SELECT user_id, user_info, created_at
        FROM blocked_users
        ORDER BY created_at DESC
        """
    )
    return cursor.fetchall()


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


# ---------------- МЕНЮ ДЛЯ ПОЛЬЗОВАТЕЛЯ ----------------

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
            [InlineKeyboardButton(text="🌍 Сеттинг", url=LINK_SETTING)],
            [InlineKeyboardButton(text="📖 Сюжет", url=LINK_PLOT)],
            [InlineKeyboardButton(text="📋 Классификация", url=LINK_CLASSIFICATION)],
            [InlineKeyboardButton(text="⚖️ Правила", url=LINK_RULES)],
            [InlineKeyboardButton(text="❓ FAQ", url=LINK_FAQ)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


def bio_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Описание бункеров", url=LINK_VAULTS)],
            [
                InlineKeyboardButton(
                    text="🏜 Описание пустоши",
                    callback_data="menu_wasteland",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


def wasteland_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📍 Миссисипи", url=LINK_MISSISSIPPI)],
            [InlineKeyboardButton(text="📍 Луизиана", url=LINK_LOUISIANA)],
            [InlineKeyboardButton(text="📍 Восточный Техас", url=LINK_EAST_TEXAS)],
            [InlineKeyboardButton(text="📍 Западный Техас", url=LINK_WEST_TEXAS)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_bio")],
        ]
    )


def guides_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📘 Гайд по проекту", url=LINK_PROJECT_GUIDE)],
            [InlineKeyboardButton(text="🎲 Гайд по ДнД", url=LINK_DND_GUIDE)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


# ---------------- КНОПКИ ДЛЯ АДМИНОВ В ЧАТЕ ПОДДЕРЖКИ ----------------

def support_actions_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Поставили бронь",
                    callback_data="tpl:booking",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Роль занята",
                    callback_data="tpl:role_taken",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Вступить во флуд",
                    callback_data="tpl:flood_question",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Добро пожаловать",
                    callback_data="tpl:flood_welcome",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать",
                    callback_data="admin:block",
                ),
                InlineKeyboardButton(
                    text="✅ Разблокировать",
                    callback_data="admin:unblock",
                ),
            ],
        ]
    )


# ---------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------

async def edit_menu_message(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
):
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=keyboard,
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
        )


def normalize_command(text: str) -> str:
    return text.split()[0].split("@")[0].lower()


# ---------------- КОМАНДЫ ----------------

@dp.message(CommandStart())
async def start(message: Message):
    try:
        await message.answer_photo(
            photo=WELCOME_IMAGE,
            caption=WELCOME_TEXT,
            reply_markup=main_menu(),
        )
    except TelegramBadRequest:
        await message.answer(
            WELCOME_TEXT,
            reply_markup=main_menu(),
        )


@dp.message(Command("info"))
async def info_command(message: Message):
    await message.answer(
        WELCOME_TEXT,
        reply_markup=main_menu(),
    )


@dp.message(Command("chatid"))
async def chat_id_command(message: Message):
    await message.answer(f"ID этого чата: {message.chat.id}")


# ---------------- НАЖАТИЯ НА КНОПКИ ПОЛЬЗОВАТЕЛЬСКОГО МЕНЮ ----------------

@dp.callback_query(F.data == "menu_main")
async def open_main_menu(callback: CallbackQuery):
    await edit_menu_message(callback, WELCOME_TEXT, main_menu())
    await callback.answer()


@dp.callback_query(F.data == "menu_info")
async def open_info_menu(callback: CallbackQuery):
    await edit_menu_message(callback, "📌 Основная информация:", info_menu())
    await callback.answer()


@dp.callback_query(F.data == "menu_bio")
async def open_bio_menu(callback: CallbackQuery):
    await edit_menu_message(
        callback,
        "📝 Документы для написания биографии:",
        bio_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_wasteland")
async def open_wasteland_menu(callback: CallbackQuery):
    await edit_menu_message(callback, "🏜 Описание пустоши:", wasteland_menu())
    await callback.answer()


@dp.callback_query(F.data == "menu_guides")
async def open_guides_menu(callback: CallbackQuery):
    await edit_menu_message(callback, "📚 Гайды:", guides_menu())
    await callback.answer()


# ---------------- НАЖАТИЯ НА АДМИНСКИЕ КНОПКИ ----------------

@dp.callback_query(F.data.startswith("tpl:"))
async def send_template_to_user(callback: CallbackQuery):
    if callback.message.chat.id != SUPPORT_CHAT_ID:
        await callback.answer("Эта кнопка работает только в чате поддержки.", show_alert=True)
        return

    user_id = get_user_id_by_support_message(callback.message.message_id)

    if not user_id:
        await callback.answer("Не удалось определить пользователя.", show_alert=True)
        return

    if is_user_blocked(user_id):
        await callback.answer("Пользователь заблокирован.", show_alert=True)
        return

    template_key = callback.data.split(":", 1)[1]
    text = TEMPLATES.get(template_key)

    if not text:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return

    try:
        await bot.send_message(chat_id=user_id, text=text)
        await callback.answer("✅ Шаблон отправлен пользователю.")
    except TelegramForbiddenError:
        await callback.answer(
            "Пользователь заблокировал бота.",
            show_alert=True,
        )


@dp.callback_query(F.data.startswith("admin:"))
async def admin_action(callback: CallbackQuery):
    if callback.message.chat.id != SUPPORT_CHAT_ID:
        await callback.answer("Эта кнопка работает только в чате поддержки.", show_alert=True)
        return

    user_id = get_user_id_by_support_message(callback.message.message_id)

    if not user_id:
        await callback.answer("Не удалось определить пользователя.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    if action == "block":
        block_user(user_id)
        await callback.answer("🚫 Пользователь заблокирован.", show_alert=True)
        return

    if action == "unblock":
        unblock_user(user_id)
        await callback.answer("✅ Пользователь разблокирован.", show_alert=True)
        return


# ---------------- ЧАТ ПОДДЕРЖКИ: РУЧНЫЕ ОТВЕТЫ И КОМАНДЫ ----------------

@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_support_chat_message(message: Message):
    if not SUPPORT_CHAT_ID:
        return

    if message.chat.id != SUPPORT_CHAT_ID:
        return

    if message.text:
        command = normalize_command(message.text)

        if command == "/blocked":
            blocked = get_blocked_users()

            if not blocked:
                await message.reply("✅ Список заблокированных пуст.")
                return

            text = "🚫 Заблокированные пользователи:\n\n"

            for user_id, user_info, created_at in blocked:
                text += f"🆔 {user_id}\n{user_info}\nДата: {created_at}\n\n"

            await message.reply(text[:4000])
            return

        if command in {"/block", "/unblock"}:
            if not message.reply_to_message:
                await message.reply(
                    "Ответьте этой командой на сообщение пользователя в чате поддержки."
                )
                return

            user_id = get_user_id_by_support_message(
                message.reply_to_message.message_id
            )

            if not user_id:
                await message.reply(
                    "Не получилось определить пользователя. "
                    "Ответьте на сообщение, которое бот переслал из лички."
                )
                return

            if command == "/block":
                block_user(user_id)
                await message.reply("🚫 Пользователь заблокирован.")
                return

            if command == "/unblock":
                unblock_user(user_id)
                await message.reply("✅ Пользователь разблокирован.")
                return

    if not message.reply_to_message:
        return

    user_id = get_user_id_by_support_message(message.reply_to_message.message_id)

    if not user_id:
        return

    if is_user_blocked(user_id):
        await message.reply(
            "🚫 Пользователь заблокирован. "
            "Чтобы снова отвечать ему, используйте /unblock ответом на его сообщение."
        )
        return

    try:
        if message.text:
            await bot.send_message(chat_id=user_id, text=message.text)
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
    user = message.from_user

    if is_user_blocked(user.id):
        return

    if not SUPPORT_CHAT_ID:
        return

    username = f"@{user.username}" if user.username else "без username"
    full_name = user.full_name or "без имени"

    user_info = (
        f"👤 Пользователь: {full_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: {user.id}"
    )

    save_user_profile(user.id, user_info)

    header = await bot.send_message(
        chat_id=SUPPORT_CHAT_ID,
        text=(
            "📩 Новое сообщение в бота\n\n"
            f"{user_info}\n\n"
            "Можно ответить вручную через Reply "
            "или нажать кнопку с готовым шаблоном ниже."
        ),
        reply_markup=support_actions_keyboard(),
    )

    save_message_map(header.message_id, user.id)

    if message.text:
        copied = await bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            text=f"💬 Сообщение пользователя:\n\n{message.text}",
            reply_markup=support_actions_keyboard(),
        )
        save_message_map(copied.message_id, user.id)
    else:
        copied = await bot.copy_message(
            chat_id=SUPPORT_CHAT_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=support_actions_keyboard(),
        )
        save_message_map(copied.message_id, user.id)

    if should_send_first_message_reply(user.id):
        await message.answer(FIRST_MESSAGE_REPLY)


# ---------------- ЗАПУСК БОТА ----------------

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
