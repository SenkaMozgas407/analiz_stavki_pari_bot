import json
import os
from pathlib import Path
from typing import Any
from collections import Counter
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.exceptions import TelegramNetworkError
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv
import requests

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SAMPLE_DATA_PATH = Path(os.getenv("SAMPLE_DATA_PATH", "data/sample_matches.json"))
PARI_LINE_URL = os.getenv("PARI_LINE_URL")
PARI_API_TIMEOUT = int(os.getenv("PARI_API_TIMEOUT", "20"))
PARI_USER_AGENT = os.getenv(
    "PARI_USER_AGENT",
    "Mozilla/5.0 (compatible; PariLineBot/1.0; +https://t.me/)",
)
PARI_ACCEPT_LANGUAGE = os.getenv("PARI_ACCEPT_LANGUAGE", "ru-RU,ru;q=0.9,en;q=0.8")
MIN_ODDS = 1.6

if not TOKEN:
    raise RuntimeError("Заполни TELEGRAM_BOT_TOKEN в переменных окружения")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

TELEGRAM_REQUEST_TIMEOUT = int(os.getenv("TELEGRAM_REQUEST_TIMEOUT", "60"))
SEND_RETRY_ATTEMPTS = int(os.getenv("SEND_RETRY_ATTEMPTS", "3"))
SEND_RETRY_DELAY_SECONDS = float(os.getenv("SEND_RETRY_DELAY_SECONDS", "1.5"))

bot = Bot(token=TOKEN, session=AiohttpSession(timeout=TELEGRAM_REQUEST_TIMEOUT))
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


ESPORTS_KEYWORDS = (
    "dota",
    "дота",
    "counter",
    "counter-strike",
    "counter strike",
    "counterstrike",
    "cs2",
    "cs:go",
    "кибер",
    "cyber",
    "esports",
    "e-sports",
    "e sports",
)
DOTA_KEYWORDS = ("dota", "дота")
CS2_KEYWORDS = ("cs2", "counter-strike", "counter strike", "counterstrike", "cs:go", "кс")


def collect_collection(payload: Any, key: str) -> list[dict[str, Any]]:
    value = find_key(payload, key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def dict_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = item.get("id")
        if item_id is None:
            continue
        indexed[str(item_id)] = item
    return indexed


def first_non_empty(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def extract_esports_diagnostics(payload: Any) -> dict[str, Any]:
    diagnostics = {
        "total_events": 0,
        "dota2_events": 0,
        "cs2_events": 0,
        "dota2_samples": [],
        "cs2_samples": [],
        "sports_samples": [],
        "sport_kinds_samples": [],
        "tournament_esports_samples": [],
        "event_esports_samples": [],
        "top_sport_names": [],
    }
    if not isinstance(payload, dict):
        return diagnostics

    sports = collect_collection(payload, "sports")
    sport_kinds = collect_collection(payload, "sportKinds")
    tournaments = collect_collection(payload, "tournamentInfos")
    sport_categories = collect_collection(payload, "sportCategories")
    events = collect_collection(payload, "events")

    diagnostics["total_events"] = len(events)

    sport_by_id = dict_by_id(sports)
    kind_by_id = dict_by_id(sport_kinds)
    category_by_id = dict_by_id(sport_categories)
    tournament_by_id = dict_by_id(tournaments)

    diagnostics["sports_samples"] = [
        first_non_empty(item, ("name", "caption", "title")) for item in sports if first_non_empty(item, ("name", "caption", "title"))
    ][:30]
    diagnostics["sport_kinds_samples"] = [
        {
            "name": first_non_empty(item, ("name", "title")),
            "caption": first_non_empty(item, ("caption",)),
        }
        for item in sport_kinds
        if first_non_empty(item, ("name", "title")) or first_non_empty(item, ("caption",))
    ][:30]

    tournament_samples: list[dict[str, str]] = []
    for tournament in tournaments:
        name = first_non_empty(tournament, ("name", "caption", "title"))
        if contains_any_keyword(name, ESPORTS_KEYWORDS):
            tournament_samples.append(
                {
                    "id": str(tournament.get("id", "")),
                    "name": name,
                }
            )
        if len(tournament_samples) >= 30:
            break
    diagnostics["tournament_esports_samples"] = tournament_samples

    sport_counter: Counter[str] = Counter()

    for sport in sports:
        sport_name = first_non_empty(sport, ("name", "caption", "title"))
        if sport_name:
            sport_counter[sport_name] += 1

    event_keyword_samples: list[dict[str, str]] = []

    for event in events:
        event_name = first_non_empty(event, ("name", "eventName", "title", "matchName"))
        team1 = first_non_empty(event, ("team1", "team1Name", "homeTeamName"))
        team2 = first_non_empty(event, ("team2", "team2Name", "awayTeamName"))
        event_caption = first_non_empty(event, ("caption",))

        sport = sport_by_id.get(str(event.get("sportId")))
        sport_name = first_non_empty(sport or {}, ("name", "caption", "title"))

        sport_kind = kind_by_id.get(str(event.get("sportKindId")))
        sport_kind_name = first_non_empty(sport_kind or {}, ("name", "caption", "title"))

        category = category_by_id.get(str(event.get("sportCategoryId") or event.get("categoryId")))
        category_caption = first_non_empty(category or {}, ("caption", "name", "title"))

        tournament = tournament_by_id.get(str(event.get("tournamentId") or event.get("tournamentInfoId")))
        tournament_caption = first_non_empty(tournament or {}, ("caption", "name", "title"))

        haystack = " ".join(
            part
            for part in (
                event_name,
                team1,
                team2,
                event_caption,
                sport_name,
                sport_kind_name,
                category_caption,
                tournament_caption,
            )
            if part
        )

        for candidate in (sport_name, sport_kind_name):
            if candidate:
                sport_counter[candidate] += 1

        market_name = ""
        odds_value = ""
        markets = event.get("markets")
        if isinstance(markets, list) and markets:
            first_market = markets[0]
            if isinstance(first_market, dict):
                market_name = str(first_market.get("name") or first_market.get("marketName") or "")
                outcomes = first_market.get("outcomes")
                if isinstance(outcomes, list) and outcomes:
                    first_outcome = outcomes[0]
                    if isinstance(first_outcome, dict):
                        odds_value = str(
                            first_outcome.get("price")
                            or first_outcome.get("value")
                            or first_outcome.get("odds")
                            or ""
                        )

        sample = {
            "match": event_name,
            "team1": team1,
            "team2": team2,
            "competition": tournament_caption or category_caption,
            "sport": sport_name or sport_kind_name,
            "market": market_name,
            "odds": odds_value,
        }

        if contains_any_keyword(haystack, DOTA_KEYWORDS):
            diagnostics["dota2_events"] += 1
            if len(diagnostics["dota2_samples"]) < 3:
                diagnostics["dota2_samples"].append(sample)

        if contains_any_keyword(haystack, CS2_KEYWORDS):
            diagnostics["cs2_events"] += 1
            if len(diagnostics["cs2_samples"]) < 3:
                diagnostics["cs2_samples"].append(sample)

        if contains_any_keyword(" ".join((event_name, team1, team2, event_caption)), ESPORTS_KEYWORDS):
            if len(event_keyword_samples) < 30:
                event_keyword_samples.append(sample)

    diagnostics["event_esports_samples"] = event_keyword_samples
    diagnostics["top_sport_names"] = [
        {"name": name, "count": count}
        for name, count in sport_counter.most_common(50)
    ]

    return diagnostics


def compact_json(value: Any, limit: int = 2000) -> str:
    return truncate_text(json.dumps(value, ensure_ascii=False), limit)




def fetch_pari_line_debug(url: str) -> dict[str, Any]:
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": PARI_ACCEPT_LANGUAGE,
        "User-Agent": PARI_USER_AGENT,
        "Referer": "https://pari.ru/",
        "Origin": "https://pari.ru",
    }
    response = requests.get(url, timeout=PARI_API_TIMEOUT, headers=request_headers)
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
    esports_info = extract_esports_diagnostics(json_payload) if is_json else extract_esports_diagnostics(None)

    return {
        "requested_url": response.url,
        "status_code": response.status_code,
        "response_content_type": response.headers.get("Content-Type", "unknown"),
        "request_headers_used": request_headers,
        "response_preview": truncate_text(body, 1000),
        "is_json": is_json,
        "has_sports": sports_value is not None,
        "has_events": events_value is not None,
        "has_custom_factors": custom_factors_value is not None,
        "sports_count": value_count(sports_value),
        "events_count": value_count(events_value),
        "custom_factors_count": value_count(custom_factors_value),
        "esports": esports_info,
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


async def safe_send(
    message: types.Message,
    text: str,
    *,
    attempts: int = SEND_RETRY_ATTEMPTS,
    retry_delay: float = SEND_RETRY_DELAY_SECONDS,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await message.answer(text)
            return
        except TelegramNetworkError as exc:
            logger.warning(
                "Telegram timeout/network error while sending message "
                "(attempt %s/%s, chat_id=%s): %s",
                attempt,
                attempts,
                message.chat.id,
                exc,
            )
            if attempt < attempts:
                await asyncio.sleep(retry_delay)
                continue
            logger.error(
                "Failed to send message after %s attempts (chat_id=%s).",
                attempts,
                message.chat.id,
            )
        except Exception:
            logger.exception("Unexpected error while sending message (chat_id=%s).", message.chat.id)
        return


@dp.message(Command("start"))
async def start(message: types.Message) -> None:
    await safe_send(
        message,
        "Бот работает стабильно ✅\n\n"
        "Команды:\n"
        "/start — список команд\n"
        "/id — показать chat id\n"
        "/analyze — анализ mock-данных\n"
        "/debug_pari — диагностика PARI endpoint"
    )


@dp.message(Command("id"))
async def show_id(message: types.Message) -> None:
    await safe_send(message, f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("analyze"))
async def analyze(message: types.Message) -> None:
    await safe_send(message, "Запускаю анализ mock-данных...")

    try:
        predictions = load_sample_matches()
    except Exception as exc:
        await safe_send(message, f"Ошибка чтения mock-данных: {exc}")
        return

    if not predictions:
        await safe_send(message, f"Нет вариантов с коэффициентом >= {MIN_ODDS}.")
        return

    await safe_send(message, f"Найдено вариантов: {len(predictions)}")
    for item in predictions:
        await safe_send(message, format_prediction(item))


@dp.message(Command("debug_pari"))
async def debug_pari(message: types.Message) -> None:
    if not PARI_LINE_URL:
        await safe_send(
            message,
            "PARI_LINE_URL не задан в .env.\n"
            "Укажи полный URL endpoint, например:\n"
            "PARI_LINE_URL=https://clientsapi.../line/list?lang=ru&version=...&scopeMarket=2300"
        )
        return

    await safe_send(message, "Запускаю диагностику PARI endpoint...")

    try:
        debug_data = await asyncio.to_thread(fetch_pari_line_debug, PARI_LINE_URL)
    except Exception as exc:
        await safe_send(message, f"Ошибка запроса к PARI endpoint: {exc}")
        return

    await safe_send(
        message,
        "🔎 Диагностика PARI\n"
        f"URL: {debug_data['requested_url']}\n"
        f"Status code: {debug_data['status_code']}\n"
        f"Content-Type: {debug_data['response_content_type']}\n"
        f"JSON найден: {'да' if debug_data['is_json'] else 'нет'}\n"
        f"Ключ sports: {'да' if debug_data['has_sports'] else 'нет'}\n"
        f"Ключ events: {'да' if debug_data['has_events'] else 'нет'}\n"
        f"Ключ customFactors: {'да' if debug_data['has_custom_factors'] else 'нет'}\n"
        f"Количество sports: {debug_data['sports_count']}\n"
        f"Количество events: {debug_data['events_count']}\n"
        f"Количество customFactors: {debug_data['custom_factors_count']}\n"
        f"Киберспорт events всего: {debug_data['esports']['total_events']}\n"
        f"Dota 2 events: {debug_data['esports']['dota2_events']}\n"
        f"CS2 events: {debug_data['esports']['cs2_events']}\n"
        f"Использованы заголовки: {json.dumps(debug_data['request_headers_used'], ensure_ascii=False)}\n"
        f"Dota 2 samples: {compact_json(debug_data['esports']['dota2_samples'])}\n"
        f"CS2 samples: {compact_json(debug_data['esports']['cs2_samples'])}\n\n"
        f"Первые 1000 символов ответа:\n{debug_data['response_preview']}"
    )

    await safe_send(
        message,
        "🧪 Киберспорт samples (до 30):\n"
        f"sports names: {compact_json(debug_data['esports']['sports_samples'])}\n"
        f"sportKinds name/caption: {compact_json(debug_data['esports']['sport_kinds_samples'])}\n"
        f"tournamentInfos by keywords: {compact_json(debug_data['esports']['tournament_esports_samples'])}\n"
        f"events by keywords (name/team1/team2/caption): {compact_json(debug_data['esports']['event_esports_samples'])}"
    )

    await safe_send(
        message,
        "📊 Top 50 sport names/captions (temporary):\n"
        f"{compact_json(debug_data['esports']['top_sport_names'])}"
    )


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
