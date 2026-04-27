import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

from pari_parser import get_pari_esports_odds

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("Заполни TELEGRAM_BOT_TOKEN в Render Environment Variables")

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Бот работает ✅\n\n"
        "Команды:\n"
        "/pari — найти матчи Dota 2/CS2 на PARI с коэффициентом выше 1.6"
    )


@dp.message(Command("pari"))
async def pari(message: types.Message):
    await message.answer("Ищу матчи Dota 2 и CS2 на PARI с кэфом выше 1.6...")

    try:
        odds = await get_pari_esports_odds(min_odds=1.6)

        if not odds:
            await message.answer(
                "Пока не нашёл подходящих матчей/коэффициентов выше 1.6.\n\n"
                "Это может значить одно из двух:\n"
                "1. Сейчас на PARI нет подходящей линии.\n"
                "2. PARI отдаёт коэффициенты через скрытый JSON, и нужно сделать более точный парсер."
            )
            return

        for item in odds[:15]:
            text = (
                f"🎮 {item['game']}\n"
                f"⚔️ {item['match']}\n\n"
                f"📌 Рынок: {item['market']}\n"
                f"💰 Коэф: {item['odds']}\n\n"
                f"📊 Анализ:\n"
                f"Пока это базовый фильтр линии PARI. Следующим шагом добавим анализ формы, карт, "
                f"последних игр и риска.\n\n"
                f"✅ Можно рассмотреть\n"
                f"⚠️ Не финансовый совет"
            )
            await message.answer(text)

    except Exception as e:
        await message.answer(f"Ошибка при парсинге PARI: {e}")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
