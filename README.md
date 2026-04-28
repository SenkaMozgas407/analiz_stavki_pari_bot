# PARI Telegram Bot (минимальная стабильная версия)

Минимальный Telegram-бот для ручной проверки линии PARI по команде `/pari`.

## Что делает

- Только 3 команды: `/start`, `/id`, `/pari`.
- Нет авто-проверок и фоновых циклов.
- `/pari` делает HTTP-запрос к API PARI через `aiohttp`.
- Если запрос не удался — бот показывает понятную ошибку.
- Если ответ получен, но данные не найдены — бот показывает debug:
  - endpoint
  - status code
  - первые 500 символов ответа
  - сколько найдено `sports/events/customFactors`

## Файлы

- `bot.py` — Telegram-команды и ответы пользователю.
- `pari_parser.py` — запрос к API PARI, разбор JSON, debug-диагностика.
- `requirements.txt` — минимальные зависимости.

## Запуск

```bash
pip install -r requirements.txt
python bot.py
```

## Переменные окружения

```text
TELEGRAM_BOT_TOKEN=твой_токен
# опционально: список endpoint'ов через запятую
PARI_API_URLS=https://api.pari.ru/v2/sports/esports/events,https://api.pari.ru/v1/sports/esports/events
```
