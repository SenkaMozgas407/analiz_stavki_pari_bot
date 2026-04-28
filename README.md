# Stable MVP Telegram Bot

Минимальный и стабильный Telegram-бот без внешнего парсинга.

## Что умеет

- Команды:
  - `/start`
  - `/id`
  - `/analyze`
- `/analyze` читает только локальные mock-данные из `data/sample_matches.json`.
- Фильтр вариантов: `odds >= 1.6`.
- Для каждого варианта отправляет:
  - матч
  - куда ставить
  - рынок
  - коэффициент
  - короткую аналитику
  - риск
  - уверенность

## Что убрано

- Полностью убран PARI-парсер.
- Полностью убран автоспам/авторассылка по расписанию.

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
```
