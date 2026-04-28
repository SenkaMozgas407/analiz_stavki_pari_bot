import os
import re
import time
from typing import Any

import requests

MIN_ODDS = 1.6
PARI_TIMEOUT = float(os.getenv("PARI_TIMEOUT", "8"))
PARI_LIST_URL = os.getenv(
    "PARI_LIST_URL",
    "https://www.pari.ru/sportsbookdata/api/widget/list",
)

ESPORT_KEYWORDS = (
    "dota",
    "дота",
    "counter-strike",
    "counter strike",
    "cs2",
    "cs:go",
    "кs2",
)


class PariUnavailableError(RuntimeError):
    """Raised when PARI data cannot be fetched or parsed."""


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _is_esport_title(value: str) -> bool:
    normalized = value.lower()
    return any(keyword in normalized for keyword in ESPORT_KEYWORDS)


def _extract_teams(event: dict[str, Any]) -> tuple[str, str]:
    team1 = _normalize_text(
        event.get("team1")
        or event.get("competitor1")
        or event.get("home")
        or event.get("homeName")
        or event.get("teamA")
    )
    team2 = _normalize_text(
        event.get("team2")
        or event.get("competitor2")
        or event.get("away")
        or event.get("awayName")
        or event.get("teamB")
    )

    if not team1 or not team2:
        event_name = _normalize_text(event.get("name") or event.get("eventName"))
        for delimiter in (" - ", " vs ", " v ", " — ", " / "):
            if delimiter in event_name:
                left, right = event_name.split(delimiter, maxsplit=1)
                team1 = team1 or left.strip()
                team2 = team2 or right.strip()
                break

    return team1, team2


def _parse_market_and_selection(factor_name: str) -> tuple[str, str] | None:
    name = factor_name.strip()
    lowered = name.lower()

    if re.search(r"\bп1\b", lowered):
        return "Победа", "П1"
    if re.search(r"\bп2\b", lowered):
        return "Победа", "П2"

    total_match = re.search(r"(?:тотал|тб|тм)\s*(б|м|бол|мен)?\s*([0-9]+(?:[\.,][0-9]+)?)", lowered)
    if total_match:
        kind = total_match.group(1) or ""
        number = total_match.group(2).replace(",", ".")
        if kind.startswith("б"):
            return "Тотал", f"Тотал Б {number}"
        if kind.startswith("м"):
            return "Тотал", f"Тотал М {number}"
        if "тб" in lowered:
            return "Тотал", f"Тотал Б {number}"
        if "тм" in lowered:
            return "Тотал", f"Тотал М {number}"

    handicap_match = re.search(
        r"(?:фора|ф)\s*([12])\s*([+-]?\s*[0-9]+(?:[\.,][0-9]+)?)",
        lowered,
    )
    if handicap_match:
        side = handicap_match.group(1)
        handicap = handicap_match.group(2).replace(" ", "").replace(",", ".")
        return "Фора", f"Фора {side} ({handicap})"

    return None


def fetch_pari_matches(min_odds: float = MIN_ODDS) -> list[dict[str, Any]]:
    params = {
        "lang": "ru",
        "version": str(int(time.time())),
        "scopeMarket": "2300",
    }

    try:
        response = requests.get(PARI_LIST_URL, params=params, timeout=PARI_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PariUnavailableError(f"Ошибка получения PARI: {exc}") from exc

    sports = payload.get("sports")
    if not isinstance(sports, list):
        raise PariUnavailableError("Некорректный формат PARI: нет sports")

    parsed: list[dict[str, Any]] = []

    for sport in sports:
        if not isinstance(sport, dict):
            continue
        sport_name = _normalize_text(sport.get("name") or sport.get("sportName"))
        if not _is_esport_title(sport_name):
            continue

        events = sport.get("events")
        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict):
                continue

            event_name = _normalize_text(event.get("name") or event.get("eventName"))
            if not (_is_esport_title(event_name) or _is_esport_title(sport_name)):
                continue

            team1, team2 = _extract_teams(event)
            if not (team1 and team2):
                continue

            factors = event.get("customFactors")
            if not isinstance(factors, list):
                continue

            for factor in factors:
                if not isinstance(factor, dict):
                    continue

                factor_name = _normalize_text(
                    factor.get("name") or factor.get("factorName") or factor.get("title")
                )
                if not factor_name:
                    continue

                parsed_market = _parse_market_and_selection(factor_name)
                if not parsed_market:
                    continue

                odds = _safe_float(
                    factor.get("value")
                    or factor.get("price")
                    or factor.get("odd")
                    or factor.get("odds")
                )
                if odds is None or odds < min_odds:
                    continue

                market, selection = parsed_market
                parsed.append(
                    {
                        "game": sport_name,
                        "match": f"{team1} vs {team2}",
                        "team1": team1,
                        "team2": team2,
                        "market": market,
                        "selection": selection,
                        "odds": odds,
                    }
                )

    if not parsed:
        raise PariUnavailableError("PARI не вернул подходящих матчей Dota2/CS2")

    return parsed
