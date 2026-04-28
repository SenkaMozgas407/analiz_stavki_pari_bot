import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests

PARI_ESPORTS_URL = "https://pari.ru/esports"

# Основные JSON endpoint'ы, которые обычно используются фронтендом PARI.
DEFAULT_API_CANDIDATES = [
    "https://api.pari.ru/v2/sports/esports/events",
    "https://api.pari.ru/v1/sports/esports/events",
    "https://api.pari.ru/v2/events?category=esports",
    "https://api.pari.ru/events?category=esports",
]

GAME_KEYWORDS = {
    "Dota 2": ["dota 2", "dota2", "дота", "dota"],
    "CS2": ["cs2", "counter-strike 2", "counter strike 2", "counter-strike", "cs:go", "csgo", "кс"],
}

MARKET_PATTERNS = {
    "winner": ["winner", "победитель", "исход", "match winner", "п1", "п2", "moneyline"],
    "totals": ["total", "тотал", "over", "under", "больше", "меньше"],
    "handicap": ["handicap", "spread", "фора"],
    "maps": ["map", "карта", "maps", "round"],
}


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.replace(",", ".").strip()
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _iter_dicts(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_dicts(item)


def _detect_game(text: str) -> Optional[str]:
    low = text.lower()
    for game, words in GAME_KEYWORDS.items():
        if any(word in low for word in words):
            return game
    return None


def _normalize_market_type(raw_market: str, raw_outcome: str = "") -> str:
    text = f"{raw_market} {raw_outcome}".lower()
    for market_type, patterns in MARKET_PATTERNS.items():
        if any(p in text for p in patterns):
            return market_type
    return "other"


def _extract_match_name(event: Dict[str, Any]) -> Optional[str]:
    candidates = [
        event.get("match"),
        event.get("matchName"),
        event.get("name"),
        event.get("eventName"),
        event.get("title"),
    ]
    team1 = event.get("team1") or event.get("home") or event.get("homeTeam")
    team2 = event.get("team2") or event.get("away") or event.get("awayTeam")
    if team1 and team2:
        candidates.insert(0, f"{team1} vs {team2}")

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_start_time(event: Dict[str, Any]) -> Optional[str]:
    for key in ("startTime", "startsAt", "date", "time", "start"):
        value = event.get(key)
        if not value:
            continue
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
            return dt.isoformat()
        if isinstance(value, str):
            return value.strip()
    return None


def _extract_outcomes(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    markets = event.get("markets") or event.get("betOffers") or event.get("odds") or []
    extracted: List[Dict[str, Any]] = []

    if isinstance(markets, dict):
        markets = [markets]

    for market in markets:
        if not isinstance(market, dict):
            continue

        market_name = (
            market.get("name")
            or market.get("marketName")
            or market.get("caption")
            or market.get("type")
            or "Рынок"
        )
        outcomes = market.get("outcomes") or market.get("selections") or market.get("bets") or []

        if isinstance(outcomes, dict):
            outcomes = [outcomes]

        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue

            odd = (
                _safe_float(outcome.get("odd"))
                or _safe_float(outcome.get("odds"))
                or _safe_float(outcome.get("price"))
                or _safe_float(outcome.get("value"))
                or _safe_float(outcome.get("k"))
            )
            if odd is None:
                continue

            outcome_name = (
                outcome.get("name")
                or outcome.get("label")
                or outcome.get("outcomeName")
                or outcome.get("runner")
                or "Ставка"
            )

            extracted.append(
                {
                    "market": str(market_name),
                    "outcome": str(outcome_name),
                    "odds": odd,
                    "market_type": _normalize_market_type(str(market_name), str(outcome_name)),
                }
            )

    return extracted


def _estimate_probability(odds: float, market_type: str) -> float:
    # Базовая implied probability с небольшой корректировкой для разных рынков.
    base = min(0.95, max(0.05, 1.0 / odds))
    adjustment = {
        "winner": 0.02,
        "maps": 0.0,
        "totals": -0.01,
        "handicap": -0.02,
        "other": -0.03,
    }.get(market_type, -0.03)
    return min(0.95, max(0.05, base + adjustment))


def _risk_level(probability: float, odds: float) -> str:
    score = probability * odds
    if score >= 1.18:
        return "Низкий"
    if score >= 1.05:
        return "Средний"
    return "Высокий"


def _confidence(probability: float, market_type: str) -> str:
    market_bonus = {"winner": 0.05, "maps": 0.03, "totals": 0.0, "handicap": -0.02}.get(market_type, -0.03)
    score = probability + market_bonus
    if score >= 0.63:
        return "Высокая"
    if score >= 0.52:
        return "Средняя"
    return "Умеренная"


def _build_reason(item: Dict[str, Any]) -> str:
    market_explain = {
        "winner": "рынок на победителя обычно самый ликвидный и стабильный",
        "totals": "тоталы часто дают value при смещении линии",
        "handicap": "фора покрывает сценарий с ожидаемым перевесом по раундам/картам",
        "maps": "рынок карт лучше отражает стиль команд в bo-сериях",
        "other": "рынок прошёл фильтрацию по коэффициенту и вероятности",
    }
    return (
        f"Коэффициент {item['odds']:.2f} выше порога, а {market_explain.get(item['market_type'], market_explain['other'])}. "
        f"Оценка вероятности ~{item['probability'] * 100:.1f}% при риске '{item['risk']}'."
    )


def _event_to_predictions(event: Dict[str, Any], min_odds: float) -> List[Dict[str, Any]]:
    text_blob = " ".join(str(event.get(k, "")) for k in ("sport", "game", "name", "eventName", "category", "tournament"))
    game = _detect_game(text_blob)
    if not game:
        match_candidate = _extract_match_name(event)
        if match_candidate:
            game = _detect_game(match_candidate)
    if game not in {"Dota 2", "CS2"}:
        return []

    match_name = _extract_match_name(event)
    if not match_name:
        return []

    start_time = _extract_start_time(event)
    outcomes = _extract_outcomes(event)

    predictions: List[Dict[str, Any]] = []
    for outcome in outcomes:
        odd = outcome["odds"]
        if odd < min_odds:
            continue

        probability = _estimate_probability(odd, outcome["market_type"])
        risk = _risk_level(probability, odd)
        confidence = _confidence(probability, outcome["market_type"])

        item = {
            "game": game,
            "match": match_name,
            "start_time": start_time,
            "market": outcome["market"],
            "market_type": outcome["market_type"],
            "pick": outcome["outcome"],
            "odds": odd,
            "probability": probability,
            "risk": risk,
            "confidence": confidence,
        }
        item["reason"] = _build_reason(item)
        predictions.append(item)

    return predictions


def _api_candidates() -> List[str]:
    raw = os.getenv("PARI_API_URLS", "").strip()
    if not raw:
        return DEFAULT_API_CANDIDATES
    urls = [part.strip() for part in raw.split(",") if part.strip()]
    return urls or DEFAULT_API_CANDIDATES


def _fetch_json(url: str, timeout_sec: int = 20) -> Any:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": PARI_ESPORTS_URL,
    }
    response = requests.get(url, headers=headers, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


async def get_pari_esports_odds(min_odds: float = 1.6, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Production parser:
    - забирает реальные JSON-данные из API PARI (через список candidate endpoint'ов),
    - находит только Dota 2 / CS2,
    - выделяет рынки (победитель/тотал/фора/карты),
    - фильтрует коэффициенты >= min_odds,
    - возвращает готовую аналитику для бота.

    Если часть endpoint'ов недоступна, продолжаем работать с тем, что удалось получить.
    """
    collected: List[Dict[str, Any]] = []
    errors: List[str] = []

    for url in _api_candidates():
        try:
            payload = _fetch_json(url)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

        for obj in _iter_dicts(payload):
            # Считаем словарь событием, если в нём есть признаки матча и рынков.
            if not any(key in obj for key in ("markets", "betOffers", "odds", "team1", "team2", "homeTeam", "awayTeam")):
                continue
            collected.extend(_event_to_predictions(obj, min_odds=min_odds))

    # Дедупликация и сортировка по value-score (probability * odds)
    unique: Dict[str, Dict[str, Any]] = {}
    for item in collected:
        key = "|".join(
            [
                item["game"],
                item["match"],
                item["market"],
                item["pick"],
                f"{item['odds']:.3f}",
            ]
        )
        if key not in unique:
            unique[key] = item

    ranked = sorted(
        unique.values(),
        key=lambda x: (x["probability"] * x["odds"], x["odds"]),
        reverse=True,
    )

    if not ranked and errors:
        # Не падаем в проде: отдаём пустой список, а диагностику логируем через stderr.
        print("[pari_parser] Все API endpoint'ы недоступны:")
        for err in errors:
            print(f"[pari_parser] {err}")

    return ranked[: max(1, limit)]
