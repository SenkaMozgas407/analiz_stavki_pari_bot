from playwright.async_api import async_playwright

PARI_ESPORTS_URL = "https://pari.ru/esports"


async def get_pari_esports_odds(min_odds: float = 1.6):
    """
    MVP-парсер PARI.
    Берёт текст со страницы esports и пытается найти Dota 2 / CS2 коэффициенты выше min_odds.

    Важно: если PARI отдаёт данные через скрытые JSON-запросы или защищает страницу,
    этот файл потом нужно будет заменить на более точный парсер API-запросов.
    """
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        page = await browser.new_page()
        await page.goto(PARI_ESPORTS_URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(7000)

        text = await page.inner_text("body")
        await browser.close()

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    current_game = None
    current_match = None

    for i, line in enumerate(lines):
        low = line.lower()

        if "dota" in low:
            current_game = "Dota 2"

        if "counter-strike" in low or "cs2" in low or "cs:go" in low or "counter strike" in low:
            current_game = "CS2"

        # Примерный поиск строки матча
        if current_game and ("—" in line or " - " in line or " vs " in low):
            current_match = line

        # Примерный поиск коэффициентов
        try:
            odds = float(line.replace(",", "."))
            if odds > min_odds and current_game and current_match:
                market = lines[i - 1] if i > 0 else "Неизвестный рынок"
                results.append({
                    "game": current_game,
                    "match": current_match,
                    "market": market,
                    "odds": odds
                })
        except ValueError:
            continue

    # Убираем дубли
    unique = []
    seen = set()
    for item in results:
        key = (item["game"], item["match"], item["market"], item["odds"])
        if key not in seen:
            unique.append(item)
            seen.add(key)

    return unique
