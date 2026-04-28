import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SAMPLE_DATA_PATH = Path(os.getenv("SAMPLE_DATA_PATH", "data/sample_matches.json"))
PARI_LIST_ENDPOINT = os.getenv(
    "PARI_LIST_ENDPOINT",
    "https://www.pari.ru/live/list",
)
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


def _pick(obj: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_target_game(*parts: str) -> bool:
    normalized = " ".join(parts).lower()
    return any(token in normalized for token in ["dota", "дота", "cs2", "counter-strike", "кс2"])


def _build_market_from_factor(factor: dict[str, Any]) -> tuple[str, str] | None:
    text_parts = [
        str(_pick(factor, ["selection", "name", "title", "label", "caption", "shortName", "n"], "")),
        str(_pick(factor, ["marketName", "market", "group", "factorName", "m"], "")),
    ]
    text = " ".join(text_parts).strip()
    lower = text.lower()

    if re.search(r"\bп1\b", lower):
        return "Победитель матча", "П1"
    if re.search(r"\bп2\b", lower):
        return "Победитель матча", "П2"

    total_match = re.search(r"(б|м)(?:ольше|еньше)?\s*([0-9]+(?:[.,][0-9]+)?)", lower)
    if total_match:
        side = "Больше" if total_match.group(1).startswith("б") else "Меньше"
        return "Тотал", f"{side} {total_match.group(2).replace(',', '.')}"

    handicap_match = re.search(r"(?:фора|фор[аы]?)\s*(1|2)?[^0-9+-]*([+-]?\d+(?:[.,]\d+)?)", lower)
    if handicap_match:
        team_no = handicap_match.group(1) or "1"
        value = handicap_match.group(2).replace(",", ".")
        sign = "+" if not value.startswith("-") else ""
        return "Фора", f"Фора {team_no} ({sign}{value})"

    return None


def fetch_pari_matches() -> list[dict[str, Any]]:
    response = requests.get(
        PARI_LIST_ENDPOINT,
        params={"lang": "ru", "version": int(time.time()), "scopeMarket": 2300},
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    payload = response.json()

    sports_raw = payload.get("sports", [])
    events_raw = payload.get("events", [])
    factors_raw = payload.get("customFactors", [])
    if not isinstance(sports_raw, list) or not isinstance(events_raw, list) or not isinstance(factors_raw, list):
        raise ValueError("Неверный формат PARI payload: ожидаются массивы sports/events/customFactors")

    sports_by_id: dict[str, dict[str, Any]] = {}
    for sport in sports_raw:
        if isinstance(sport, dict):
            sid = _pick(sport, ["id", "sportId", "i"])
            if sid is not None:
                sports_by_id[str(sid)] = sport

    events_by_id: dict[str, dict[str, Any]] = {}
    for event in events_raw:
        if isinstance(event, dict):
            eid = _pick(event, ["id", "eventId", "i"])
            if eid is not None:
                events_by_id[str(eid)] = event

    predictions: list[dict[str, Any]] = []
    for factor in factors_raw:
        if not isinstance(factor, dict):
            continue

        odds = _as_float(_pick(factor, ["odds", "k", "value", "v", "price"]))
        if odds is None or odds < MIN_ODDS:
            continue

        event_id = _pick(factor, ["eventId", "e", "matchId"])
        event = events_by_id.get(str(event_id))
        if not event:
            continue

        sport_id = _pick(event, ["sportId", "sid", "s"])
        sport = sports_by_id.get(str(sport_id), {})
        sport_name = str(_pick(sport, ["name", "n", "title"], ""))
        event_name = str(_pick(event, ["name", "eventName", "n", "title"], ""))

        team1 = str(_pick(event, ["team1", "home", "h"], "")).strip()
        team2 = str(_pick(event, ["team2", "away", "a"], "")).strip()
        teams = " vs ".join([team for team in [team1, team2] if team])
        match_name = teams or event_name

        if not _is_target_game(sport_name, event_name, match_name):
            continue

        market_selection = _build_market_from_factor(factor)
        if not market_selection:
            continue

        market, selection = market_selection
        predictions.append(
            {
                "game": sport_name or "Киберспорт",
                "match": match_name or "Неизвестный матч",
                "market": market,
                "selection": selection,
                "odds": odds,
            }
        )

    return predictions


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
        "/analyze — анализ mock-данных"
    )


@dp.message(Command("id"))
async def show_id(message: types.Message) -> None:
    await message.answer(f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("analyze"))
async def analyze(message: types.Message) -> None:
    await message.answer("Запускаю анализ матчей PARI...")

    try:
        predictions = fetch_pari_matches()
        source = "PARI"
    except Exception as exc:
        await message.answer("PARI временно недоступен, использую резервные данные.")
        try:
            predictions = load_sample_matches()
            source = "mock"
        except Exception as sample_exc:
            await message.answer(f"Ошибка чтения резервных данных: {sample_exc}")
            await message.answer(f"Детали ошибки PARI: {exc}")
            return

    if not predictions:
        await message.answer(f"Нет вариантов с коэффициентом >= {MIN_ODDS}.")
        return

    await message.answer(f"Источник: {source}. Найдено вариантов: {len(predictions)}")
    for item in predictions:
        await message.answer(format_prediction(item))


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
