import asyncio
import json
import os
from pathlib import Path
from typing import Set

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

from pari_parser import get_pari_esports_odds

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTO_CHECK_INTERVAL_MINUTES = int(os.getenv("AUTO_CHECK_INTERVAL_MINUTES", "30"))
CHAT_STORAGE_PATH = Path(os.getenv("CHAT_STORAGE_PATH", "chat_ids.json"))

if not TOKEN:
    raise RuntimeError("Заполни TELEGRAM_BOT_TOKEN в Render Environment Variables")

bot = Bot(token=TOKEN)
dp = Dispatcher()


class ChatRegistry:
    def __init__(self, path: Path):
        self.path = path
        self.chat_ids: Set[int] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.chat_ids = {int(chat_id) for chat_id in data}
        except Exception:
            self.chat_ids = set()

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(sorted(self.chat_ids), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def register(self, chat_id: int) -> None:
        before = len(self.chat_ids)
        self.chat_ids.add(int(chat_id))
        if len(self.chat_ids) != before:
            self._save()


registry = ChatRegistry(CHAT_STORAGE_PATH)


def format_prediction(item: dict) -> str:
    start = f"\n🕒 Старт: {item['start_time']}" if item.get("start_time") else ""
    return (
        f"🎮 {item['game']}\n"
        f"⚔️ {item['match']}{start}\n\n"
        f"📌 Рынок: {item['market']}\n"
        f"✅ Ставка: {item['pick']}\n"
        f"💰 Коэффициент: {item['odds']:.2f}\n"
        f"📈 Вероятность: ~{item['probability'] * 100:.1f}%\n"
        f"🎯 Уверенность: {item['confidence']}\n"
        f"⚠️ Риск: {item['risk']}\n\n"
        f"🧠 Почему эта ставка:\n{item['reason']}\n\n"
        f"⚠️ Не финансовый совет"
    )


async def send_pari_predictions(chat_id: int) -> None:
    odds = await get_pari_esports_odds(min_odds=1.6, limit=10)

    if not odds:
        await bot.send_message(
            chat_id,
            "Подходящих вариантов с коэффициентом от 1.6 сейчас нет. "
            "Проверю снова по расписанию.",
        )
        return

    await bot.send_message(
        chat_id,
        f"Нашёл {len(odds)} подходящих вариантов. Отправляю лучшие прогнозы:",
    )
    for item in odds[:5]:
        await bot.send_message(chat_id, format_prediction(item))


@dp.message(Command("start"))
async def start(message: types.Message) -> None:
    registry.register(message.chat.id)
    await message.answer(
        "Бот работает ✅\n\n"
        "Команды:\n"
        "/pari — найти прогнозы по Dota 2 / CS2\n"
        "/id — показать chat id"
    )


@dp.message(Command("id"))
async def show_id(message: types.Message) -> None:
    registry.register(message.chat.id)
    await message.answer(f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("pari"))
async def pari(message: types.Message) -> None:
    registry.register(message.chat.id)
    await message.answer("Проверяю линию PARI по Dota 2/CS2 и считаю лучшие ставки...")
    try:
        await send_pari_predictions(message.chat.id)
    except Exception as exc:
        await message.answer(f"Ошибка при парсинге PARI: {exc}")


async def periodic_check_task() -> None:
    while True:
        if registry.chat_ids:
            for chat_id in sorted(registry.chat_ids):
                try:
                    await send_pari_predictions(chat_id)
                except Exception as exc:
                    await bot.send_message(chat_id, f"Ошибка авто-проверки: {exc}")
        await asyncio.sleep(max(1, AUTO_CHECK_INTERVAL_MINUTES) * 60)


async def main() -> None:
    asyncio.create_task(periodic_check_task())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
