import asyncio
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

import aiohttp

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


def _api_candidates() -> List[str]:
    raw = os.getenv("PARI_API_URLS", "").strip()
    if not raw:
        return DEFAULT_API_CANDIDATES
    urls = [part.strip() for part in raw.split(",") if part.strip()]
    return urls or DEFAULT_API_CANDIDATES


def _iter_nodes(payload: Any) -> Iterable[Any]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_nodes(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_nodes(item)


def _count_key(payload: Any, target: str) -> int:
    count = 0
    for node in _iter_nodes(payload):
        if isinstance(node, dict):
            for key in node.keys():
                if str(key).lower() == target.lower():
                    count += 1
    return count


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ".").strip())
        except ValueError:
            return None
    return None


def _detect_game(text: str) -> Optional[str]:
    low = text.lower()
    for game, words in GAME_KEYWORDS.items():
        if any(word in low for word in words):
            return game
    return None


def _extract_match(event: Dict[str, Any]) -> str:
    for key in ("name", "eventName", "match", "matchName", "title"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    team1 = event.get("team1") or event.get("home") or event.get("homeTeam")
    team2 = event.get("team2") or event.get("away") or event.get("awayTeam")
    if team1 and team2:
        return f"{team1} vs {team2}"

    return "Матч не распознан"


def _extract_odds_candidates(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    picks: List[Dict[str, Any]] = []

    for node in _iter_nodes(event):
        if not isinstance(node, dict):
            continue

        odd = (
            _safe_float(node.get("odd"))
            or _safe_float(node.get("odds"))
            or _safe_float(node.get("price"))
            or _safe_float(node.get("value"))
            or _safe_float(node.get("k"))
            or _safe_float(node.get("coef"))
        )
        if odd is None or odd <= 1.01:
            continue

        market = (
            node.get("marketName")
            or node.get("market")
            or node.get("type")
            or node.get("caption")
            or "Рынок"
        )
        pick = node.get("name") or node.get("label") or node.get("outcomeName") or "Исход"

        picks.append(
            {
                "market": str(market),
                "pick": str(pick),
                "odds": float(odd),
            }
        )

    unique: Dict[Tuple[str, str, float], Dict[str, Any]] = {}
    for item in picks:
        key = (item["market"], item["pick"], round(item["odds"], 3))
        if key not in unique:
            unique[key] = item

    return list(unique.values())


def _extract_items(payload: Any, limit: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    for node in _iter_nodes(payload):
        if not isinstance(node, dict):
            continue

        blob = " ".join(str(node.get(k, "")) for k in ("sport", "game", "category", "name", "eventName", "tournament"))
        game = _detect_game(blob)
        if game is None:
            continue

        match_name = _extract_match(node)
        for odd_item in _extract_odds_candidates(node):
            items.append(
                {
                    "game": game,
                    "match": match_name,
                    "market": odd_item["market"],
                    "pick": odd_item["pick"],
                    "odds": odd_item["odds"],
                }
            )

    dedup: Dict[Tuple[str, str, str, str, float], Dict[str, Any]] = {}
    for item in items:
        key = (item["game"], item["match"], item["market"], item["pick"], round(float(item["odds"]), 3))
        if key not in dedup:
            dedup[key] = item

    sorted_items = sorted(dedup.values(), key=lambda x: float(x["odds"]), reverse=True)
    return sorted_items[: max(1, limit)]


async def _fetch_endpoint(session: aiohttp.ClientSession, endpoint: str) -> Dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://pari.ru/esports",
    }

    try:
        async with session.get(endpoint, headers=headers) as response:
            text = await response.text()
            preview = text[:500]
            status_code = response.status

            json_payload = None
            if status_code < 500:
                try:
                    json_payload = await response.json(content_type=None)
                except Exception:
                    json_payload = None

            debug = {
                "endpoint": endpoint,
                "status_code": status_code,
                "response_preview": preview,
                "sports_count": _count_key(json_payload, "sports") if json_payload is not None else 0,
                "events_count": _count_key(json_payload, "events") if json_payload is not None else 0,
                "custom_factors_count": _count_key(json_payload, "customFactors") if json_payload is not None else 0,
            }

            return {
                "ok": status_code < 400 and json_payload is not None,
                "debug": debug,
                "payload": json_payload,
                "error": None if status_code < 400 else f"HTTP {status_code}",
            }

    except asyncio.TimeoutError:
        return {
            "ok": False,
            "payload": None,
            "debug": {"endpoint": endpoint},
            "error": "Request timeout",
        }
    except aiohttp.ClientError as exc:
        return {
            "ok": False,
            "payload": None,
            "debug": {"endpoint": endpoint},
            "error": f"HTTP client error: {exc}",
        }


async def get_pari_report(limit: int = 8) -> Dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=15)
    errors: List[str] = []
    last_debug: Dict[str, Any] = {}

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for endpoint in _api_candidates():
            result = await _fetch_endpoint(session, endpoint)
            last_debug = result.get("debug", {})

            if not result.get("ok"):
                errors.append(f"{endpoint}: {result.get('error', 'unknown error')}")
                continue

            payload = result.get("payload")
            items = _extract_items(payload, limit=limit)
            if items:
                return {"status": "ok", "items": items, "debug": last_debug}

            return {"status": "no_data", "debug": last_debug}

    return {"status": "request_error", "errors": errors, "debug": last_debug}
