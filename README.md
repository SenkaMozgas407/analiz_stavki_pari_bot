# Stable MVP Telegram Bot

Минимальный и стабильный Telegram-бот с приоритетом реальных данных PARI и безопасным fallback.

## Что умеет

- Команды:
  - `/start`
  - `/id`
  - `/analyze`
- `/analyze` сначала запрашивает реальные данные PARI через endpoint `list?...&scopeMarket=2300`.
- При недоступности PARI автоматически использует локальные mock-данные из `data/sample_matches.json`.
- Фильтр вариантов: `odds >= 1.6`.
- Реальные данные ограничены играми Dota2 / CS2 и рынками:
  - П1 / П2
  - Тотал Б / М
  - Фора 1 / 2
- Для каждого варианта отправляет:
  - матч
  - куда ставить
  - рынок
  - коэффициент
  - короткую аналитику
  - риск
  - уверенность

## Надежность

- Если PARI недоступен, бот пишет:
  - `PARI временно недоступен, использую резервные данные.`
- После этого анализ продолжается без падения на mock-данных.

## Файлы

- `bot.py` — Telegram-бот (MVP).
- `data/sample_matches.json` — mock-данные для команды `/analyze`.
- `requirements.txt` — зависимости.

## Запуск

```bash
pip install -r requirements.txt
python bot.py
```

## Переменные окружения

```text
TELEGRAM_BOT_TOKEN=ваш_токен
# опционально
SAMPLE_DATA_PATH=data/sample_matches.json
# опционально: переопределить PARI endpoint
PARI_LIST_ENDPOINT=https://www.pari.ru/live/list
```
