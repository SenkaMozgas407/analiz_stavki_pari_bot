import asyncio
import os
from typing import Dict, List

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

from pari_parser import get_pari_report

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Заполни TELEGRAM_BOT_TOKEN в Environment Variables")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def format_item(item: Dict[str, object]) -> str:
    return (
        f"🎮 {item.get('game', 'Esports')}\n"
        f"⚔️ {item.get('match', 'Матч не распознан')}\n"
        f"📌 {item.get('market', 'Рынок')}\n"
        f"✅ {item.get('pick', 'Исход')}\n"
        f"💰 {float(item.get('odds', 0)):.2f}"
    )


def format_no_data_debug(debug: Dict[str, object]) -> str:
    preview = str(debug.get("response_preview", ""))
    return (
        "Данные PARI получены, но подходящие события/коэффициенты не найдены.\n\n"
        f"endpoint: {debug.get('endpoint', 'unknown')}\n"
        f"status code: {debug.get('status_code', 'unknown')}\n"
        f"response[0:500]:\n{preview}\n\n"
        "Найдено:\n"
        f"sports: {debug.get('sports_count', 0)}\n"
        f"events: {debug.get('events_count', 0)}\n"
        f"customFactors: {debug.get('custom_factors_count', 0)}"
    )


@dp.message(Command("start"))
async def start(message: types.Message) -> None:
    await message.answer(
        "Бот работает ✅\n\n"
        "Доступные команды:\n"
        "/start\n"
        "/id\n"
        "/pari"
    )


@dp.message(Command("id"))
async def show_id(message: types.Message) -> None:
    await message.answer(f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("pari"))
async def pari(message: types.Message) -> None:
    await message.answer("Пробую получить линию PARI...")

    try:
        report = await get_pari_report(limit=8)
    except Exception as exc:
        await message.answer(f"Внутренняя ошибка /pari: {exc}")
        return

    status = report.get("status")

    if status == "ok":
        items: List[Dict[str, object]] = report.get("items", [])  # type: ignore[assignment]
        await message.answer(f"Получено вариантов: {len(items)}")
        for item in items:
            await message.answer(format_item(item))
        return

    if status == "no_data":
        await message.answer(format_no_data_debug(report.get("debug", {})))
        return

    if status == "request_error":
        errors = report.get("errors", [])
        pretty_errors = "\n".join(f"- {line}" for line in errors) if errors else "(без деталей)"
        await message.answer(
            "Не удалось получить данные PARI.\n"
            "Проверьте доступность API/сети.\n\n"
            f"Детали:\n{pretty_errors}"
        )
        return

    await message.answer(f"Неизвестный статус ответа: {status}")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
