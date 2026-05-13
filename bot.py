import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message


BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Я бот VaultByBot 🤖\n\n"
        "Пока я умею отвечать на /start и /help."
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Команды бота:\n\n"
        "/start — запустить бота\n"
        "/help — помощь"
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
