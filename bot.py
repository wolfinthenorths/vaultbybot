import asyncio
import csv
import io
import logging
import os
import re
import sys
import time
import urllib.request
from contextlib import suppress
from pathlib import Path
from urllib.parse import quote
from weakref import WeakValueDictionary

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import (
    TelegramAPIError, TelegramBadRequest, TelegramForbiddenError,
    TelegramNetworkError, TelegramRetryAfter,
)
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from aiogram.utils.formatting import Bold, Code, Text

from storage import Database, resolve_database_path


BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not SUPPORT_CHAT_ID:
    raise RuntimeError("SUPPORT_CHAT_ID is not set")
SUPPORT_CHAT_ID = int(SUPPORT_CHAT_ID)
logging.basicConfig(level=logging.INFO, stream=sys.stdout)


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class RateLimitRetry(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        for attempt in range(3):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as exc:
                if attempt == 2 or exc.retry_after > 60:
                    raise
                await asyncio.sleep(exc.retry_after)


bot.session.middleware(RateLimitRetry())
user_locks = WeakValueDictionary()
template_locks = WeakValueDictionary()
recent_templates = {}


def get_lock(locks, key):
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


# ---------------- КАРТИНКИ ----------------

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/wolfinthenorths/vaultbybot/main"


def github_image(filename: str) -> str:
    return f"{GITHUB_RAW_BASE}/{quote(filename)}"


WELCOME_IMAGE = github_image("f603e39e58f392f60bad5.jpg")
IMAGE_INFO = github_image("Information.png")
IMAGE_ROLES = github_image("Reservation.png")
IMAGE_DOCUMENTS = github_image("Documents.png")
IMAGE_PROGRESS = github_image("Scientific and Technological Progress.png")
IMAGE_GUIDES = github_image("Guides.png")
IMAGE_TABLES = github_image("Tables.png")


# ---------------- ССЫЛКИ НА ДОКУМЕНТЫ ----------------

LINK_SETTING = "https://telegra.ph/Setting-12-28-5"
LINK_PLOT = "https://telegra.ph/Main-plot-12-28"
LINK_CLASSIFICATION = "https://telegra.ph/Classification-05-14-8"
LINK_RULES = "https://telegra.ph/Rules-12-28-96"
LINK_FAQ = "https://dotdossier.com/p/faq-07-10-2026"

LINK_ORGANIZATIONS = "https://dotdossier.com/p/organizations-07-10-2026"
LINK_VAULTS = "https://dotdossier.com/p/list-of-bunkers-07-10-2026"

LINK_MISSISSIPPI = "https://dotdossier.com/p/wasteland-mississippi-07-10-2026"
LINK_LOUISIANA = "https://dotdossier.com/p/wasteland-louisiana-06-10-2026"
LINK_EAST_TEXAS = "https://dotdossier.com/p/wasteland-east-texas-06-10-2026"
LINK_WEST_TEXAS = "https://dotdossier.com/p/wasteland-west-texas-06-10-2026"

LINK_TECHNOLOGIES = "https://dotdossier.com/p/technologies-10-10-2026"
LINK_ROBOTS = "https://dotdossier.com/p/robots-10-10-2026"
LINK_MEDICINE = "https://dotdossier.com/p/medicine-10-10-2026"
LINK_CULTURE = "https://dotdossier.com/p/culture-08-10-2026"
LINK_BESTIARY = "https://telegra.ph/Bestiary-05-23"
LINK_WEAPONS_MAIN = "https://dotdossier.com/p/weapons-firearms-energy-melee-10-10-2026"
LINK_WEAPONS_CHEMICAL = "https://dotdossier.com/p/weapons-chemical-raider-s-defensive-systems-10-10-2026"
LINK_ARMOR = "https://dotdossier.com/p/armor-10-10-2026"

LINK_PROJECT_GUIDE = "https://telegra.ph/Guide-06-01-3"
LINK_DND_GUIDE = "https://telegra.ph/DD-Guide-09-04"

LINK_DEADLINES_RESTS = "https://docs.google.com/spreadsheets/d/10LewYnGJlR2BjWXj7mFiuBraQYppn9yBbJMXwcbT6HA/edit?usp=sharing"
LINK_CAPS = "https://docs.google.com/spreadsheets/d/1iuFkiLPEaA770-iBCLJKuHaLkCY-_43GpY4xcrcwaX4/edit?usp=sharing"
LINK_CHARACTER_STATS = "https://docs.google.com/spreadsheets/d/1cYEfxasIAu61BtAQEZBHV4yV5Ghm7_-BL_SsSFoiBG8/edit?usp=sharing"


# ---------------- ТАБЛИЦА ЗАНЯТЫХ РОЛЕЙ ----------------

ROLES_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1_U-WBDUNpM1OCos0x0PTiv544Qk2W8oCDHYPqCZsIDc"
    "/export?format=csv&gid=0"
)


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

database = Database(
    resolve_database_path(), SUPPORT_CHAT_ID,
    legacy_path=Path(__file__).resolve().parent / "support_messages.db",
)


def save_message_map(support_message_id: int, user_id: int):
    database.save_message_map(support_message_id, user_id)


def get_user_id_by_support_message(support_message_id: int):
    return database.get_user_id(support_message_id)


def find_support_user_id(message: Message):
    """Trust stored routes and bot-authored metadata, never user-supplied IDs."""
    if not message or message.chat.id != SUPPORT_CHAT_ID:
        return None

    stored_id = get_user_id_by_support_message(message.message_id)
    if stored_id:
        return stored_id

    if not message.from_user or message.from_user.id != bot.id:
        if message.reply_to_message:
            user_id = find_support_user_id(message.reply_to_message)
            if user_id:
                save_message_map(message.message_id, user_id)
                return user_id
        return None

    markup = message.reply_markup
    if markup:
        for row in markup.inline_keyboard:
            for button in row:
                parts = (button.callback_data or "").split(":")
                if (len(parts) == 3 and parts[0] in {"tpl", "admin"}
                        and parts[2].isdigit() and int(parts[2]) > 0):
                    user_id = int(parts[2])
                    save_message_map(message.message_id, user_id)
                    return user_id

    # Previous bot versions used a footer or a separate author card.
    text = message.text or message.caption or ""
    ids = re.findall(r"^🆔[ \t]*ID:[ \t]*(\d+)[ \t]*$", text, re.MULTILINE)
    if ids:
        user_id = int(ids[-1])
        save_message_map(message.message_id, user_id)
        if text.startswith("📩 Новое сообщение в бота") and "\n\n" in text:
            profile = text.split("\n\n")[1]
            save_user_profile(user_id, profile)
        return user_id

    # Recover replies to the old "Delivered" messages through their reply.
    if message.reply_to_message:
        user_id = find_support_user_id(message.reply_to_message)
        if user_id:
            save_message_map(message.message_id, user_id)
            return user_id
    return None


def find_callback_user_id(callback: CallbackQuery):
    if not callback.message or callback.message.chat.id != SUPPORT_CHAT_ID:
        return None
    return find_support_user_id(callback.message)


def save_user_profile(user_id: int, user_info: str):
    database.save_user_profile(user_id, user_info)


def get_user_info(user_id: int) -> str:
    return database.get_user_info(user_id)


def should_show_contact_hint(user_id: int) -> bool:
    return not database.first_reply_sent(user_id)


def is_user_blocked(user_id: int) -> bool:
    return database.is_blocked(user_id)


def block_user(user_id: int):
    database.block(user_id)


def unblock_user(user_id: int):
    database.unblock(user_id)


def get_blocked_users():
    return database.blocked_users()


# ---------------- ЗАНЯТЫЕ РОЛИ ----------------

def normalize_category(category: str) -> str:
    return category.strip().lower().replace("ё", "е")


def canonical_category(category: str) -> str:
    value = normalize_category(category)

    if value in {"житель", "жители"}:
        return "житель"

    if value in {"гуль", "гули"}:
        return "гуль"

    if value in {"райдер", "райдеры"}:
        return "райдер"

    if value in {"бронь", "брони", "забронировано"}:
        return "бронь"

    return value


def get_taken_roles_text() -> str:
    groups = {
        "житель": [],
        "гуль": [],
        "райдер": [],
        "бронь": [],
    }

    group_titles = {
        "житель": "🪬 Жители",
        "гуль": "🧫 Гули",
        "райдер": "⛓️‍💥 Райдеры",
        "бронь": "🌐 Бронь",
    }

    try:
        with urllib.request.urlopen(ROLES_CSV_URL, timeout=15) as response:
            raw_data = response.read().decode("utf-8-sig")

        reader = csv.reader(io.StringIO(raw_data))
        rows = list(reader)

        for row in rows[1:]:
            if len(row) < 2:
                continue

            category = canonical_category(row[0])
            character = row[1].strip()

            if not category or not character:
                continue

            if category not in groups:
                groups[category] = []

            groups[category].append(character)

    except Exception:
        return (
            "Не получилось загрузить таблицу. "
            "Попробуйте немного позже."
        )

    lines = [
        "Ниже представлен список уже занятых ролей. "
        "Сверьтесь с ним перед бронированием — система учёта, конечно, "
        "пережила ядерный апокалипсис, но дубликаты всё ещё не любит.",
    ]

    has_any_roles = False

    for category in ["житель", "гуль", "райдер", "бронь"]:
        characters = groups.get(category, [])

        if not characters:
            continue

        has_any_roles = True
        lines.append("")
        lines.append(f"{group_titles[category]}:")

        for character in characters:
            lines.append(f"✧ {character}")

    extra_categories = [
        category for category in groups.keys()
        if category not in {"житель", "гуль", "райдер", "бронь"}
    ]

    for category in extra_categories:
        characters = groups.get(category, [])

        if not characters:
            continue

        has_any_roles = True
        lines.append("")
        lines.append(f"{category.capitalize()}:")

        for character in characters:
            lines.append(f"✧ {character}")

    if not has_any_roles:
        lines.append("")
        lines.append("Пока список пуст.")

    return "\n".join(lines)


# ---------------- ТЕКСТЫ ----------------

WELCOME_TEXT = (
    "Привет! Я — Волт-Бой на Вашем наручном компьютере "
    "и по совместительству Ваш главный помощник по выживанию "
    "и построению счастливой жизни в этом мире.\n\n"
    "Чтобы забронировать роль, напишите её сообщением "
    "или задайте интересующий вопрос — я помогу не хуже "
    "синта третьего поколения!"
)


INFO_TEXT = (
    "Здесь собраны основные сведения о проекте: всё, что нужно знать "
    "перед тем, как открыть гермодверь и шагнуть в наше Убежище."
)


BIO_TEXT = (
    "Не знаете, как написать биографию? Сейчас поможем. Волт-Бой "
    "гарантирует, что приведенные ниже документы помогут Вам при ее написании."
)


PROGRESS_TEXT = (
    "Чтобы лучше понять мир, окружающий Ваших героев, ознакомьтесь "
    "с «Атомными Хрониками»: здесь собраны сведения о технологиях, "
    "медицине, культуре и прочих чудесах прогресса, которые каким-то "
    "образом пережили второй конец света."
)


GUIDES_TEXT = (
    "Здесь собраны путеводители по проекту: от основных правил до "
    "полезных подсказок, которые помогут не заблудиться в коридорах "
    "бункера и не погибнуть от бюрократии раньше времени."
)


TABLES_TEXT = (
    "Не можете вспомнить, когда писать пост, сколько крышек осталось "
    "на счету и где вообще всё это посмотреть? Вам сюда — учетные "
    "терминалы уже прогреты."
)


WASTELAND_TEXT = "Выберите регион Южной Пустоши:"
ARSENAL_TEXT = "Выберите раздел арсенала:"
WEAPONS_TEXT = "Выберите тип оружия:"


CONTACT_HINT = (
    "Чтобы связаться с Волт-Боем, отправьте сообщение 🫡\n"
    "Мы ответим вам здесь, в этом чате."
)


# ---------------- МЕНЮ ДЛЯ ПОЛЬЗОВАТЕЛЯ ----------------

def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="☢️ Основная информация",
                    callback_data="menu_info",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💠 Занятые роли",
                    callback_data="menu_roles",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏷️ Документы для написания биографии",
                    callback_data="menu_bio",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗺️ Научно-технический прогресс мира",
                    callback_data="menu_progress",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📺 Гайды",
                    callback_data="menu_guides",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 Таблицы для игроков",
                    callback_data="menu_tables",
                )
            ],
        ]
    )


def info_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📟 Сеттинг", url=LINK_SETTING)],
            [InlineKeyboardButton(text="🧶 Сюжет", url=LINK_PLOT)],
            [InlineKeyboardButton(text="🧟‍♂️ Классификация", url=LINK_CLASSIFICATION)],
            [InlineKeyboardButton(text="⚖️ Правила", url=LINK_RULES)],
            [InlineKeyboardButton(text="📖 FAQ", url=LINK_FAQ)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


def roles_menu(page: int = 0, total: int = 1):
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️", callback_data=f"menu_roles:{page - 1}"))
    if page + 1 < total:
        navigation.append(InlineKeyboardButton(text="➡️", callback_data=f"menu_roles:{page + 1}"))
    return InlineKeyboardMarkup(
        inline_keyboard=([navigation] if navigation else []) + [
            [InlineKeyboardButton(text="🔄 Обновить список", callback_data="menu_roles")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


def bio_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Организации", url=LINK_ORGANIZATIONS)],
            [InlineKeyboardButton(text="🪴 Описание Бункеров", url=LINK_VAULTS)],
            [
                InlineKeyboardButton(
                    text="🏜 Описание Пустоши",
                    callback_data="menu_wasteland",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


def wasteland_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛤️ Миссисипи", url=LINK_MISSISSIPPI)],
            [InlineKeyboardButton(text="🪸 Луизиана", url=LINK_LOUISIANA)],
            [InlineKeyboardButton(text="🗻 Восточный Техас", url=LINK_EAST_TEXAS)],
            [InlineKeyboardButton(text="🦂 Западный Техас", url=LINK_WEST_TEXAS)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_bio")],
        ]
    )


def progress_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗜️ Технологии", url=LINK_TECHNOLOGIES)],
            [InlineKeyboardButton(text="👾 Роботы", url=LINK_ROBOTS)],
            [InlineKeyboardButton(text="⛑️ Медицина", url=LINK_MEDICINE)],
            [InlineKeyboardButton(text="🎏 Культура", url=LINK_CULTURE)],
            [
                InlineKeyboardButton(
                    text="⚔️ Арсенал",
                    callback_data="menu_arsenal",
                )
            ],
            [InlineKeyboardButton(text="🧌 Бестиарий", url=LINK_BESTIARY)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


def arsenal_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💣 Оружие",
                    callback_data="menu_weapons",
                )
            ],
            [InlineKeyboardButton(text="🛡️ Броня", url=LINK_ARMOR)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_progress")],
        ]
    )


def weapons_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪓 Огнестрельное, энергетическое и холодное оружие",
                    url=LINK_WEAPONS_MAIN,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧪 Химическое и райдерское оружие, оборонительные комплексы",
                    url=LINK_WEAPONS_CHEMICAL,
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_arsenal")],
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


def tables_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗓️ Таблица дедлайнов и рестов",
                    url=LINK_DEADLINES_RESTS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪙 Таблица Крышек",
                    url=LINK_CAPS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧮 Сводка характеристик персонажей",
                    url=LINK_CHARACTER_STATS,
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
        ]
    )


# ---------------- КНОПКИ ДЛЯ АДМИНОВ В ЧАТЕ ПОДДЕРЖКИ ----------------

def clean_name(name: str) -> str:
    return " ".join(name.split()) or "без имени"


def support_actions_keyboard(user_id: int, identity: str = None, status: str = None):
    if not identity:
        profile = get_user_info(user_id)
        match = re.search(r"^👤 Пользователь: (.+)$", profile, re.MULTILINE)
        identity = match.group(1) if match else f"Пользователь {user_id}"
    rows = [
        [InlineKeyboardButton(text=f"👤 {clean_name(identity)[:60]}",
                              callback_data=f"admin:profile:{user_id}")],
        [InlineKeyboardButton(text="💬 Поставили бронь", callback_data=f"tpl:booking:{user_id}"),
         InlineKeyboardButton(text="💬 Роль занята", callback_data=f"tpl:role_taken:{user_id}")],
        [InlineKeyboardButton(text="💬 Вступить во флуд", callback_data=f"tpl:flood_question:{user_id}"),
         InlineKeyboardButton(text="💬 Добро пожаловать", callback_data=f"tpl:flood_welcome:{user_id}")],
        [InlineKeyboardButton(
            text="✅ Разблокировать" if is_user_blocked(user_id) else "🚫 Заблокировать",
            callback_data=f"admin:{'unblock' if is_user_blocked(user_id) else 'block'}:{user_id}")],
    ]
    if status:
        rows.append([InlineKeyboardButton(text=status[:64],
                                          callback_data=f"admin:status:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------

def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def split_text(text: str, limit: int = 3900):
    pages = []
    while utf16_length(text) > limit:
        prefix = text.encode("utf-16-le")[:limit * 2].decode("utf-16-le", errors="ignore")
        newline = prefix.rfind("\n")
        cut = newline + 1 if newline > len(prefix) // 2 else len(prefix)
        pages.append(text[:cut])
        text = text[cut:]
    if text:
        pages.append(text)
    return pages or [""]


async def answer_callback(callback: CallbackQuery, *args, **kwargs):
    with suppress(TelegramBadRequest):
        await callback.answer(*args, **kwargs)


async def send_photo_menu(message, image_url, text, keyboard):
    if utf16_length(text) <= 1024:
        try:
            return await message.answer_photo(photo=image_url, caption=text, reply_markup=keyboard)
        except TelegramBadRequest:
            logging.warning("Menu image could not be loaded; showing text instead")
    return await message.answer(text, reply_markup=keyboard)


async def edit_photo_menu(callback, image_url, text, keyboard):
    message = callback.message
    if not isinstance(message, Message):
        return
    if message.photo and utf16_length(text) <= 1024:
        try:
            await message.edit_media(
                media=InputMediaPhoto(media=image_url, caption=text), reply_markup=keyboard)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            logging.warning("Menu image edit failed; using text fallback")
            sent = await message.answer(text, reply_markup=keyboard)
    elif not message.photo and utf16_length(text) > 1024:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            sent = await message.answer(text, reply_markup=keyboard)
    else:
        sent = await send_photo_menu(message, image_url, text, keyboard)
    # Keep the previous menu until its replacement was successfully sent.
    if sent:
        with suppress(TelegramBadRequest):
            await message.delete()


def normalize_command(text: str) -> str:
    parts = text.split()
    return parts[0].split("@")[0].lower() if parts else ""


async def update_card_status(message, user_id, status):
    try:
        identity = None
        if message.reply_markup:
            first = message.reply_markup.inline_keyboard[0][0]
            if first.callback_data == f"admin:profile:{user_id}":
                identity = first.text.removeprefix("👤 ")
        markup = support_actions_keyboard(user_id, identity=identity, status=status)
        await bot.edit_message_reply_markup(
            chat_id=SUPPORT_CHAT_ID, message_id=message.message_id, reply_markup=markup)
    except TelegramAPIError:
        # Delivery already succeeded. A missing/deleted card must not cause another send.
        logging.warning("Could not update the support card status", exc_info=True)


async def copy_incoming_message(message, user):
    full_name = clean_name(user.full_name)
    identity = full_name + (f" · @{user.username}" if user.username else "")
    header = Text(Bold("👤 ", full_name),
                  f" · @{user.username}" if user.username else "",
                  "\n🆔 ID: ", Code(str(user.id)), "\n\n")
    markup = support_actions_keyboard(user.id, identity=identity)
    if message.text:
        body = Text.from_entities(message.text, message.entities or [])
        card = Text(header, body)
        if len(card) <= 4096:
            return await bot.send_message(
                chat_id=SUPPORT_CHAT_ID, reply_markup=markup,
                disable_web_page_preview=True, **card.as_kwargs())
        # A full-length Telegram message still fits unchanged; author is on its keyboard.
        return await bot.copy_message(
            chat_id=SUPPORT_CHAT_ID, from_chat_id=message.chat.id,
            message_id=message.message_id, reply_markup=markup)
    options = {}
    if (message.photo or message.video or message.document or message.audio
            or message.animation or message.voice):
        caption = Text(header, Text.from_entities(message.caption or "", message.caption_entities or []))
        if len(caption) <= 1024:
            options = caption.as_kwargs(text_key="caption", entities_key="caption_entities")
        # If the caption is already long, keep all of it and show author on the keyboard.
    return await bot.copy_message(
        chat_id=SUPPORT_CHAT_ID, from_chat_id=message.chat.id,
        message_id=message.message_id, reply_markup=markup, **options)


def delivery_error(exc):
    if isinstance(exc, TelegramForbiddenError):
        return "❌ Пользователь заблокировал бота или больше недоступен."
    if isinstance(exc, (TelegramNetworkError, TelegramRetryAfter)):
        return "❌ Не удалось подтвердить доставку. Проверьте переписку перед повторной отправкой."
    return "❌ Не удалось доставить это сообщение. Попробуйте текст или другое вложение."


# ---------------- КОМАНДЫ ----------------

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def start(message: Message):
    user = message.from_user
    if not user or user.is_bot:
        return
    async with get_lock(user_locks, user.id):
        if is_user_blocked(user.id):
            return
        show_hint = should_show_contact_hint(user.id)
        text = WELCOME_TEXT + (f"\n\n{CONTACT_HINT}" if show_hint else "")
        await send_photo_menu(
            message=message,
            image_url=WELCOME_IMAGE,
            text=text,
            keyboard=main_menu(),
        )
        if show_hint:
            database.mark_first_reply_sent(user.id)


@dp.message(Command("info"), F.chat.type == ChatType.PRIVATE)
async def info_command(message: Message):
    await send_photo_menu(
        message=message,
        image_url=WELCOME_IMAGE,
        text=WELCOME_TEXT,
        keyboard=main_menu(),
    )


@dp.message(Command("menu"), F.chat.type == ChatType.PRIVATE)
async def menu_command(message: Message):
    await send_photo_menu(
        message=message,
        image_url=WELCOME_IMAGE,
        text=WELCOME_TEXT,
        keyboard=main_menu(),
    )


@dp.message(Command("chatid"))
async def chat_id_command(message: Message):
    await message.answer(f"ID этого чата: {message.chat.id}")


# ---------------- НАЖАТИЯ НА КНОПКИ ПОЛЬЗОВАТЕЛЬСКОГО МЕНЮ ----------------

@dp.callback_query(F.data == "menu_main")
async def open_main_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(callback, WELCOME_IMAGE, WELCOME_TEXT, main_menu())


@dp.callback_query(F.data == "menu_info")
async def open_info_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(callback, IMAGE_INFO, INFO_TEXT, info_menu())


@dp.callback_query(F.data == "menu_roles")
@dp.callback_query(F.data.startswith("menu_roles:"))
async def open_roles_menu(callback: CallbackQuery):
    await answer_callback(callback)
    roles_text = await asyncio.to_thread(get_taken_roles_text)
    pages = split_text(roles_text)
    try:
        page = int(callback.data.split(":")[1]) if ":" in callback.data else 0
    except (ValueError, IndexError):
        page = 0
    page = max(0, min(page, len(pages) - 1))
    text = pages[page]
    if len(pages) > 1:
        text += f"\n\nСтраница {page + 1}/{len(pages)}"
    await edit_photo_menu(callback, IMAGE_ROLES, text, roles_menu(page, len(pages)))


@dp.callback_query(F.data == "menu_bio")
async def open_bio_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(callback, IMAGE_DOCUMENTS, BIO_TEXT, bio_menu())


@dp.callback_query(F.data == "menu_wasteland")
async def open_wasteland_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(
        callback,
        IMAGE_DOCUMENTS,
        WASTELAND_TEXT,
        wasteland_menu(),
    )


@dp.callback_query(F.data == "menu_progress")
async def open_progress_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(callback, IMAGE_PROGRESS, PROGRESS_TEXT, progress_menu())


@dp.callback_query(F.data == "menu_arsenal")
async def open_arsenal_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(
        callback,
        IMAGE_PROGRESS,
        ARSENAL_TEXT,
        arsenal_menu(),
    )


@dp.callback_query(F.data == "menu_weapons")
async def open_weapons_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(
        callback,
        IMAGE_PROGRESS,
        WEAPONS_TEXT,
        weapons_menu(),
    )


@dp.callback_query(F.data == "menu_guides")
async def open_guides_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(callback, IMAGE_GUIDES, GUIDES_TEXT, guides_menu())


@dp.callback_query(F.data == "menu_tables")
async def open_tables_menu(callback: CallbackQuery):
    await answer_callback(callback)
    await edit_photo_menu(callback, IMAGE_TABLES, TABLES_TEXT, tables_menu())


# ---------------- НАЖАТИЯ НА АДМИНСКИЕ КНОПКИ ----------------

@dp.callback_query(F.data.startswith("tpl:"))
async def send_template_to_user(callback: CallbackQuery):
    if not callback.message or callback.message.chat.id != SUPPORT_CHAT_ID:
        await answer_callback(callback, "Эта кнопка работает только в чате поддержки.", show_alert=True)
        return
    user_id = find_callback_user_id(callback)
    if not user_id:
        await answer_callback(callback, "Не удалось определить пользователя.", show_alert=True)
        return
    if is_user_blocked(user_id):
        await answer_callback(callback, "Пользователь заблокирован.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    template_key = parts[1] if len(parts) == 3 else ""
    text = TEMPLATES.get(template_key)
    if not text:
        await answer_callback(callback, "Шаблон не найден.", show_alert=True)
        return
    key = (callback.message.message_id, template_key)
    async with get_lock(template_locks, key):
        if time.monotonic() - recent_templates.get(key, -60) < 10:
            await answer_callback(callback, "Этот ответ уже отправлен.", show_alert=True)
            return
        await answer_callback(callback, "Отправляю ответ…")
        try:
            await bot.send_message(chat_id=user_id, text=text)
        except TelegramAPIError as exc:
            logging.warning("Template delivery failed", exc_info=True)
            await update_card_status(callback.message, user_id, delivery_error(exc))
            return
        recent_templates[key] = time.monotonic()
        for stale in list(recent_templates):
            if time.monotonic() - recent_templates[stale] > 60:
                del recent_templates[stale]
        labels = {"booking": "бронь", "role_taken": "роль занята",
                  "flood_question": "вопрос о флуде", "flood_welcome": "приглашение"}
        name = clean_name(callback.from_user.first_name)
        await update_card_status(callback.message, user_id, f"✅ {name}: {labels[template_key]}")


@dp.callback_query(F.data.startswith("admin:"))
async def admin_action(callback: CallbackQuery):
    if not callback.message or callback.message.chat.id != SUPPORT_CHAT_ID:
        await answer_callback(callback, "Эта кнопка работает только в чате поддержки.", show_alert=True)
        return
    user_id = find_callback_user_id(callback)
    if not user_id:
        await answer_callback(callback, "Не удалось определить пользователя.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    action = parts[1] if len(parts) == 3 else ""
    if action == "profile":
        text = f"🆔 ID: {user_id}\n{get_user_info(user_id)}"
        await answer_callback(callback, split_text(text, 200)[0], show_alert=True)
    elif action == "status":
        rows = callback.message.reply_markup.inline_keyboard
        await answer_callback(callback, rows[-1][0].text, show_alert=True)
    elif action in {"block", "unblock"}:
        if action == "block":
            block_user(user_id)
        else:
            unblock_user(user_id)
        status = "🚫 Пользователь заблокирован." if action == "block" else "✅ Пользователь разблокирован."
        await answer_callback(callback, status, show_alert=True)
        await update_card_status(callback.message, user_id, status)
    else:
        await answer_callback(callback)


# ---------------- ЧАТ ПОДДЕРЖКИ: РУЧНЫЕ ОТВЕТЫ И КОМАНДЫ ----------------

@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_support_chat_message(message: Message):
    if message.chat.id != SUPPORT_CHAT_ID or (message.from_user and message.from_user.is_bot):
        return
    command = normalize_command(message.text or "")
    if command == "/dbstats":
        stats = database.stats()
        backups = sorted(database.backup_dir.glob("support-*.db"))
        await message.reply(
            "🗄 Состояние базы\n\n"
            f"Пользователей: {stats['user_profiles']}\n"
            f"Связей для ответов: {stats['message_routes']}\n"
            f"Заблокировано: {stats['blocked_users']}\n"
            f"Резервных копий: {len(backups)}\n"
            f"Постоянный диск: {'подключён' if os.getenv('RAILWAY_VOLUME_MOUNT_PATH') else 'локальный запуск'}"
        )
        return
    if command == "/backupdb":
        path = await asyncio.to_thread(database.backup)
        await message.reply_document(
            FSInputFile(path), caption="Резервная копия базы. Храните её в закрытом доступе.")
        return
    if command == "/recover":
        user_id = find_support_user_id(message.reply_to_message) if message.reply_to_message else None
        if user_id:
            await update_card_status(message.reply_to_message, user_id, "✅ Связь с пользователем восстановлена")
        else:
            await message.reply("Ответьте командой на старую карточку бота, где указан ID пользователя.")
        return
    if command == "/blocked":
        blocked = get_blocked_users()
        if not blocked:
            await message.reply("✅ Список заблокированных пуст.")
            return
        text = "🚫 Заблокированные пользователи:\n\n" + "\n\n".join(
            f"🆔 {user_id}\n{user_info}\nДата: {created_at}"
            for user_id, user_info, created_at in blocked)
        for page in split_text(text):
            await message.reply(page)
        return
    if command in {"/block", "/unblock"}:
        parts = (message.text or "").split()
        user_id = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else (
            find_support_user_id(message.reply_to_message) if message.reply_to_message else None)
        if not user_id or user_id <= 0:
            await message.reply("Ответьте командой на карточку пользователя или укажите /block ID / /unblock ID.")
            return
        if command == "/block":
            block_user(user_id)
        else:
            unblock_user(user_id)
        status = "🚫 Пользователь заблокирован." if command == "/block" else "✅ Пользователь разблокирован."
        if message.reply_to_message:
            await update_card_status(message.reply_to_message, user_id, status)
        else:
            await message.reply(status)
        return
    if command == "/reply":
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) <= 0:
            await message.reply("Формат: /reply ID текст.")
            return
        user_id = int(parts[1])
        if is_user_blocked(user_id):
            await message.reply("🚫 Этот пользователь заблокирован.")
            return
        try:
            await bot.send_message(chat_id=user_id, text=parts[2])
        except TelegramAPIError as exc:
            logging.warning("Manual /reply failed", exc_info=True)
            await message.reply(delivery_error(exc))
            return
        save_message_map(message.message_id, user_id)
        await message.reply("✅ Ответ отправлен пользователю.")
        return
    if command.startswith("/"):
        return
    if not message.reply_to_message:
        return
    user_id = find_support_user_id(message.reply_to_message)
    if not user_id:
        if message.reply_to_message.from_user and message.reply_to_message.from_user.id == bot.id:
            await message.reply(
                "Не удалось определить получателя. Ответьте на старую карточку с ID "
                "или используйте /reply ID текст."
            )
        return
    if is_user_blocked(user_id):
        await message.reply("🚫 Пользователь заблокирован. Используйте /unblock ответом на карточку.")
        return
    try:
        # Copy preserves text formatting and all supported attachments.
        await bot.copy_message(
            chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
    except TelegramAPIError as exc:
        logging.warning("Admin reply delivery failed", exc_info=True)
        await message.reply(delivery_error(exc))
        return
    save_message_map(message.message_id, user_id)
    name = clean_name(message.from_user.first_name) if message.from_user else "Администратор"
    await update_card_status(message.reply_to_message, user_id, f"✅ {name}: ответ отправлен")


# ---------------- СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ В БОТА ----------------

@dp.message(F.chat.type == ChatType.PRIVATE)
async def message_from_user(message: Message):
    if message.text and message.text.startswith("/"):
        await message.answer("Чтобы открыть меню, используйте /menu. Вопрос или бронь можно отправить обычным сообщением.")
        return
    user = message.from_user
    if not user or user.is_bot:
        return
    async with get_lock(user_locks, user.id):
        if is_user_blocked(user.id):
            return
        username = f"@{user.username}" if user.username else "без username"
        user_info = f"👤 Пользователь: {clean_name(user.full_name)}\n🔗 Username: {username}\n🆔 ID: {user.id}"
        save_user_profile(user.id, user_info)
        if not database.incoming_delivered(user.id, message.message_id):
            try:
                copied = await copy_incoming_message(message, user)
            except TelegramAPIError:
                logging.warning("Could not forward incoming message", exc_info=True)
                await message.answer(
                    "Не удалось подтвердить передачу сообщения администраторам. "
                    "Попробуйте немного позже; для необычного вложения можно отправить текст."
                )
                return
            save_message_map(copied.message_id, user.id)
            database.mark_incoming_delivered(user.id, message.message_id, copied.message_id)


# ---------------- ЗАПУСК БОТА ----------------

async def backup_loop():
    while True:
        await asyncio.sleep(6 * 60 * 60)
        try:
            await asyncio.to_thread(database.backup)
        except Exception:
            logging.exception("Scheduled database backup failed")


@dp.error()
async def on_error(event: ErrorEvent):
    exc = event.exception
    logging.error("Update processing failed", exc_info=(type(exc), exc, exc.__traceback__))
    callback = event.update.callback_query
    message = event.update.message
    if callback:
        await answer_callback(callback, "Не удалось выполнить действие. Попробуйте ещё раз.", show_alert=True)
    elif message and (message.chat.id == SUPPORT_CHAT_ID or message.chat.type == ChatType.PRIVATE):
        with suppress(TelegramAPIError):
            await message.answer("Не удалось завершить действие. Попробуйте ещё раз немного позже.")
    return True


async def main():
    backup_task = None
    try:
        await asyncio.to_thread(database.backup)
        logging.info("Database ready: path=%s counts=%s", database.path, database.stats())
        backup_task = asyncio.create_task(backup_loop())
        await dp.start_polling(bot)
    finally:
        if backup_task:
            backup_task.cancel()
            with suppress(asyncio.CancelledError):
                await backup_task
        try:
            await asyncio.to_thread(database.backup)
        except Exception:
            logging.exception("Shutdown database backup failed")
        database.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

