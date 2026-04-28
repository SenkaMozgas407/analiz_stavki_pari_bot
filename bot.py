import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SAMPLE_DATA_PATH = Path(os.getenv("SAMPLE_DATA_PATH", "data/sample_matches.json"))
MIN_ODDS = 1.6

if not TOKEN:
    raise RuntimeError("Заполни TELEGRAM_BOT_TOKEN в переменных окружения")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def load_sample_matches() -> list[dict[str, Any]]:
    raw = json.loads(SAMPLE_DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("sample_matches.json должен содержать JSON-массив")

    validated: list[dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Элемент #{idx} не является объектом")

        required = ["game", "match", "market", "selection", "odds"]
        missing = [field for field in required if field not in item]
        if missing:
            raise ValueError(f"Элемент #{idx}: отсутствуют поля: {', '.join(missing)}")

        odds = float(item["odds"])
        if odds < MIN_ODDS:
            continue

        validated.append(
            {
                "game": str(item["game"]),
                "match": str(item["match"]),
                "market": str(item["market"]),
                "selection": str(item["selection"]),
                "odds": odds,
            }
        )

    return validated


def build_short_analytics(item: dict[str, Any]) -> str:
    market = item["market"].lower()
    if "побед" in market:
        return "Ставка на исход: линия обычно стабильнее и проще для контроля риска."
    if "тотал" in market:
        return "Тотал подходит для сценария с темповой/затяжной серией без привязки к победителю."
    if "фора" in market:
        return "Фора дает запас при равной игре и снижает зависимость от одного исхода."
    return "Рынок прошел фильтр по коэффициенту и подходит для аккуратного тестового MVP."


def risk_level(odds: float) -> str:
    if odds <= 1.75:
        return "Низкий"
    if odds <= 2.00:
        return "Средний"
    return "Повышенный"


def confidence_level(odds: float) -> str:
    if odds <= 1.75:
        return "Высокая"
    if odds <= 2.00:
        return "Средняя"
    return "Умеренная"


def format_prediction(item: dict[str, Any]) -> str:
    odds = item["odds"]
    return (
        f"🎮 Матч: {item['match']} ({item['game']})\n"
        f"📍 Куда ставить: {item['selection']}\n"
        f"📌 Рынок: {item['market']}\n"
        f"💰 Коэффициент: {odds:.2f}\n"
        f"🧠 Короткая аналитика: {build_short_analytics(item)}\n"
        f"⚠️ Риск: {risk_level(odds)}\n"
        f"🎯 Уверенность: {confidence_level(odds)}"
    )


@dp.message(Command("start"))
async def start(message: types.Message) -> None:
    await message.answer(
        "Бот работает стабильно ✅\n\n"
        "Команды:\n"
        "/start — список команд\n"
        "/id — показать chat id\n"
        "/analyze — анализ из sample_matches.json"
    )


@dp.message(Command("id"))
async def show_id(message: types.Message) -> None:
    await message.answer(f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("analyze"))
async def analyze(message: types.Message) -> None:
    await message.answer("Начинаю анализ ставок...")
    progress_task = asyncio.create_task(send_analyze_progress(message))

    try:
        predictions = load_sample_matches()
    except Exception as exc:
        await message.answer(f"Ошибка чтения mock-данных: {exc}")
        return
    finally:
        progress_task.cancel()
        with suppress(asyncio.CancelledError):
            await progress_task

    if not predictions:
        await message.answer(f"Нет вариантов с коэффициентом >= {MIN_ODDS}.")
        return

    await message.answer(f"Найдено вариантов: {len(predictions)}")
    for item in predictions:
        await message.answer(format_prediction(item))


async def send_analyze_progress(message: types.Message, timeout_seconds: int = 10) -> None:
    await asyncio.sleep(timeout_seconds)
    await message.answer("Анализ ещё выполняется...")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
