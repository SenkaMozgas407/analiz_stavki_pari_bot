# PARI Telegram Bot

Telegram-бот для анализа ставок Dota 2 / CS2 по данным PARI JSON/API.

## Что умеет

- Забирает реальные данные матчей и коэффициентов из JSON endpoint'ов PARI.
- Находит только Dota 2 и CS2 события.
- Классифицирует рынки: победитель, тоталы, форы, карты.
- Фильтрует ставки с коэффициентом от `1.6`.
- Строит прогноз: ставка, причина, вероятность, уверенность, риск.
- Поддерживает ручной запуск и авто-проверку каждые 30 минут.

## Файлы

- `bot.py` — Telegram-бот и планировщик авто-проверки.
- `pari_parser.py` — production-ready JSON/API парсер PARI + аналитика.
- `requirements.txt` — зависимости.

## Render

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
python bot.py
```

Environment Variables:

```text
TELEGRAM_BOT_TOKEN=твой_токен_бота
AUTO_CHECK_INTERVAL_MINUTES=30
CHAT_STORAGE_PATH=chat_ids.json
# опционально: свои endpoint'ы через запятую
PARI_API_URLS=https://api.pari.ru/v2/sports/esports/events,https://api.pari.ru/v1/sports/esports/events
```

## Команды

```text
/start
/id
/pari
```
