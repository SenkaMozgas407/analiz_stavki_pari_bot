# PARI Telegram Bot MVP

Telegram-бот для поиска матчей Dota 2 / CS2 на PARI с коэффициентами выше 1.6.

## Файлы

- `bot.py` — Telegram-бот
- `pari_parser.py` — MVP-парсер PARI
- `requirements.txt` — зависимости

## Render настройки

Build Command:

```bash
pip install -r requirements.txt && playwright install chromium
```

Start Command:

```bash
python bot.py
```

Environment Variables:

```text
TELEGRAM_BOT_TOKEN=твой_токен_бота
```

## Команды в Telegram

```text
/start
/pari
```
