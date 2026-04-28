import json
import os
from pathlib import Path
from typing import Any
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv
import requests

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SAMPLE_DATA_PATH = Path(os.getenv("SAMPLE_DATA_PATH", "data/sample_matches.json"))
PARI_LINE_URL = os.getenv("PARI_LINE_URL")
MIN_ODDS = 1.6

if not TOKEN:
    raise RuntimeError("Заполни TELEGRAM_BOT_TOKEN в переменных окружения")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def truncate_text(value: str, limit: int = 1000) -> str:
    return value if len(value) <= limit else f"{value[:limit]}..."


def find_key(data: Any, target_key: str) -> Any | None:
    if isinstance(data, dict):
        if target_key in data:
            return data[target_key]
        for value in data.values():
            found = find_key(value, target_key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_key(item, target_key)
            if found is not None:
                return found
    return None


def value_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 1


def fetch_pari_line_debug(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=20)
    body = response.text
    json_payload: Any | None = None

    try:
        json_payload = response.json()
        is_json = True
    except ValueError:
        is_json = False

    sports_value = find_key(json_payload, "sports") if is_json else None
    events_value = find_key(json_payload, "events") if is_json else None
    custom_factors_value = find_key(json_payload, "customFactors") if is_json else None

    return {
        "requested_url": response.url,
        "status_code": response.status_code,
        "response_preview": truncate_text(body, 1000),
        "is_json": is_json,
        "has_sports": sports_value is not None,
        "has_events": events_value is not None,
        "has_custom_factors": custom_factors_value is not None,
        "sports_count": value_count(sports_value),
        "events_count": value_count(events_value),
        "custom_factors_count": value_count(custom_factors_value),
    }


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
        "/analyze — анализ mock-данных\n"
        "/debug_pari — диагностика PARI endpoint"
    )


@dp.message(Command("id"))
async def show_id(message: types.Message) -> None:
    await message.answer(f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("analyze"))
async def analyze(message: types.Message) -> None:
    await message.answer("Запускаю анализ mock-данных...")

    try:
        predictions = load_sample_matches()
    except Exception as exc:
        await message.answer(f"Ошибка чтения mock-данных: {exc}")
        return

    if not predictions:
        await message.answer(f"Нет вариантов с коэффициентом >= {MIN_ODDS}.")
        return

    await message.answer(f"Найдено вариантов: {len(predictions)}")
    for item in predictions:
        await message.answer(format_prediction(item))


@dp.message(Command("debug_pari"))
async def debug_pari(message: types.Message) -> None:
    if not PARI_LINE_URL:
        await message.answer(
            "PARI_LINE_URL не задан в .env.\n"
            "Укажи полный URL endpoint, например:\n"
            "PARI_LINE_URL=https://clientsapi.../line/list?lang=ru&version=...&scopeMarket=2300"
        )
        return

    await message.answer("Запускаю диагностику PARI endpoint...")

    try:
        debug_data = await asyncio.to_thread(fetch_pari_line_debug, PARI_LINE_URL)
    except Exception as exc:
        await message.answer(f"Ошибка запроса к PARI endpoint: {exc}")
        return

    await message.answer(
        "🔎 Диагностика PARI\n"
        f"URL: {debug_data['requested_url']}\n"
        f"Status code: {debug_data['status_code']}\n"
        f"JSON найден: {'да' if debug_data['is_json'] else 'нет'}\n"
        f"Ключ sports: {'да' if debug_data['has_sports'] else 'нет'}\n"
        f"Ключ events: {'да' if debug_data['has_events'] else 'нет'}\n"
        f"Ключ customFactors: {'да' if debug_data['has_custom_factors'] else 'нет'}\n"
        f"Количество sports: {debug_data['sports_count']}\n"
        f"Количество events: {debug_data['events_count']}\n"
        f"Количество customFactors: {debug_data['custom_factors_count']}\n\n"
        f"Первые 1000 символов ответа:\n{debug_data['response_preview']}"
    )


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
