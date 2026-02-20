import os
import asyncio
import httpx
import random
import sys
import json
import time
import threading
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from flask import Flask

# ============================================================
#                    КОНФИГУРАЦИЯ
# ============================================================

TOKEN = "ВСТАВЬ_НОВЫЙ_ТОКЕН"  # ← Замени на новый токен от @BotFather
ADMIN_ID = 908015235

# ============================================================
#                    ЛОГИРОВАНИЕ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("OLX")

# ============================================================
#                    НАСТРОЙКИ ПОИСКА
# ============================================================

class Config:
    """Динамические настройки — меняются через Telegram"""
    url = (
        "https://www.olx.pl/elektronika/telefony/"
        "q-iphone-13-pro/"
        "?search%5Border%5D=created_at:desc"
        "&search%5Bfilter_float_price:from%5D=500"
        "&search%5Bfilter_float_price:to%5D=1500"
    )
    interval = 300        # Интервал проверки (сек)
    is_running = True     # Мониторинг вкл/выкл
    proxy = None          # Прокси (опционально)
    max_price = 1500      # Макс цена для фильтра
    min_price = 500       # Мин цена для фильтра

# ============================================================
#                    ВЕБ-СЕРВЕР (для Render)
# ============================================================

app = Flask('')

@app.route('/')
def home():
    status = "🟢 Работает" if Config.is_running else "🔴 Остановлен"
    return f"OLX Sniper Bot | {status} | Интервал: {Config.interval}с"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ============================================================
#                    ПАРСЕР OLX
# ============================================================

class OLXParser:
    def __init__(self):
        self.seen_ads = set()
        self.total_found = 0
        self.total_new = 0
        self.last_check = None
        self.errors = 0

    def _get_headers(self):
        """Рандомные заголовки браузера"""
        v = random.choice(["120", "121", "122", "123", "124", "125"])
        return {
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          f"AppleWebKit/537.36 (KHTML, like Gecko) "
                          f"Chrome/{v}.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": f'"Chromium";v="{v}", "Google Chrome";v="{v}"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }

    async def fetch(self):
        """Получаем объявления с OLX"""
        try:
            proxy = Config.proxy
            async with httpx.AsyncClient(
                headers=self._get_headers(),
                timeout=25.0,
                follow_redirects=True,
                http2=True,
                proxy=proxy
            ) as client:

                # Шаг 1: Главная (cookies)
                try:
                    await client.get("https://www.olx.pl/")
                    await asyncio.sleep(random.uniform(1, 3))
                except:
                    pass

                # Шаг 2: Объявления
                r = await client.get(Config.url)
                log.info(f"OLX ответ: {r.status_code}")

                if r.status_code == 403:
                    self.errors += 1
                    log.warning("403 — заблокирован")
                    return None

                if r.status_code != 200:
                    self.errors += 1
                    return None

                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")

                # Парсим
                soup = BeautifulSoup(r.text, "lxml")
                ads = []

                # Метод 1: __NEXT_DATA__
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        ads = self._parse_json(data)
                        if ads:
                            log.info(f"[NEXT_DATA] → {len(ads)} объявлений")
                            self.total_found = len(ads)
                            return ads
                    except Exception as e:
                        log.warning(f"JSON ошибка: {e}")

                # Метод 2: HTML карточки
                cards = soup.find_all("div", {"data-cy": "l-card"})
                log.info(f"[HTML] карточек: {len(cards)}")

                for card in cards:
                    link = card.find("a", href=True)
                    if link and '/d/oferta/' in link.get('href', ''):
                        href = link['href']
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url.split("#")[0].split("?")[0].rstrip('/')

                        title_el = card.find("h6") or card.find("h4") or card.find("h3")
                        title = title_el.get_text(strip=True) if title_el else "?"

                        price_el = card.find("p", {"data-testid": "ad-price"})
                        price = price_el.get_text(strip=True) if price_el else "?"

                        ads.append({"title": title, "url": clean, "price": price})

                if ads:
                    self.total_found = len(ads)
                    return ads

                # Метод 3: Ссылки
                seen = set()
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if '/d/oferta/' in href:
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url.split("#")[0].split("?")[0].rstrip('/')
                        if clean not in seen:
                            seen.add(clean)
                            ads.append({
                                "title": a.get_text(strip=True)[:80] or "?",
                                "url": clean,
                                "price": "?"
                            })

                self.total_found = len(ads)
                return ads if ads else None

        except Exception as e:
            self.errors += 1
            log.error(f"Ошибка парсера: {e}")
            return None

    def _parse_json(self, data):
        """Извлекаем объявления из JSON"""
        ads = []
        props = data.get("props", {}).get("pageProps", {})

        # Пробуем разные пути
        items = []
        for path_fn in [
            lambda: props.get("listing", {}).get("listing", {}).get("ads", []),
            lambda: props.get("listing", {}).get("ads", []),
            lambda: props.get("data", {}).get("items", []),
            lambda: props.get("ads", []),
        ]:
            try:
                result = path_fn()
                if result and isinstance(result, list) and len(result) > 0:
                    items = result
                    break
            except:
                continue

        if not items:
            # Глубокий поиск
            items = self._deep_search(data)
            if items:
                return items
            return []

        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url", "")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://www.olx.pl" + url

            clean = url.split("#")[0].split("?")[0].rstrip('/')
            title = item.get("title", "?")

            price = "?"
            pd = item.get("price", {})
            if isinstance(pd, dict):
                price = pd.get("displayValue") or pd.get("regularPrice", {}).get("displayValue", "?")
            elif pd:
                price = str(pd)

            ads.append({"title": title, "url": clean, "price": price})

        return ads

    def _deep_search(self, data, results=None, depth=0):
        """Рекурсивный поиск объявлений"""
        if results is None:
            results = []
        if depth > 12:
            return results

        if isinstance(data, dict):
            url = data.get("url", "")
            title = data.get("title", "")
            if url and title and "/d/oferta/" in str(url):
                if not url.startswith("http"):
                    url = "https://www.olx.pl" + url
                clean = url.split("#")[0].split("?")[0].rstrip('/')
                if clean not in [r["url"] for r in results]:
                    price = "?"
                    p = data.get("price", {})
                    if isinstance(p, dict):
                        price = p.get("displayValue", "?")
                    results.append({"title": title, "url": clean, "price": price})
            for v in data.values():
                self._deep_search(v, results, depth + 1)
        elif isinstance(data, list):
            for item in data:
                self._deep_search(item, results, depth + 1)

        return results

# ============================================================
#                    TELEGRAM КОМАНДЫ
# ============================================================

bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ Доступ запрещён")

    await msg.answer(
        "🎯 **OLX Sniper Bot**\n\n"
        "Команды:\n"
        "▫️ /status — статус бота\n"
        "▫️ /pause — пауза мониторинга\n"
        "▫️ /resume — продолжить\n"
        "▫️ /interval 180 — интервал (сек)\n"
        "▫️ /url <ссылка> — сменить URL\n"
        "▫️ /proxy <прокси> — установить прокси\n"
        "▫️ /noproxy — убрать прокси\n"
        "▫️ /check — проверить сейчас\n"
        "▫️ /reset — сбросить базу\n"
        "▫️ /stats — статистика",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("status"))
async def cmd_status(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return

    status = "🟢 Работает" if Config.is_running else "🔴 Пауза"
    proxy = Config.proxy or "Нет"
    last = parser.last_check or "Ещё не было"

    await msg.answer(
        f"📊 **Статус бота**\n\n"
        f"Состояние: {status}\n"
        f"Интервал: {Config.interval} сек\n"
        f"В базе: {len(parser.seen_ads)} объявлений\n"
        f"Найдено всего: {parser.total_found}\n"
        f"Новых отправлено: {parser.total_new}\n"
        f"Ошибок подряд: {parser.errors}\n"
        f"Последняя проверка: {last}\n"
        f"Прокси: {proxy}\n\n"
        f"🔗 URL:\n{Config.url}",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("pause"))
async def cmd_pause(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await msg.answer("⏸ Мониторинг на паузе. /resume чтобы продолжить")

@dp.message(Command("resume"))
async def cmd_resume(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await msg.answer("▶️ Мониторинг возобновлён!")

@dp.message(Command("interval"))
async def cmd_interval(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return await msg.answer("Использование: /interval 180")
        sec = int(parts[1])
        if sec < 60:
            return await msg.answer("⚠️ Минимум 60 секунд")
        if sec > 3600:
            return await msg.answer("⚠️ Максимум 3600 секунд")
        Config.interval = sec
        await msg.answer(f"✅ Интервал: {sec} сек ({sec // 60} мин)")
    except ValueError:
        await msg.answer("❌ Укажи число. Пример: /interval 180")

@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.answer(
            "Использование: /url <ссылка OLX>\n\n"
            "Пример:\n/url https://www.olx.pl/elektronika/telefony/q-iphone-15/"
        )
    new_url = parts[1].strip()
    if "olx.pl" not in new_url:
        return await msg.answer("❌ Это не ссылка OLX")
    Config.url = new_url
    parser.seen_ads.clear()
    await msg.answer(f"✅ URL обновлён!\n🔗 {new_url}\n\n🗑 База сброшена — начну с чистого листа")

@dp.message(Command("proxy"))
async def cmd_proxy(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.answer(
            "Использование:\n"
            "/proxy http://user:pass@ip:port\n\n"
            "Пример:\n"
            "/proxy http://nyntgqyu:2c5wo0xukywv@64.137.96.74:6641"
        )
    Config.proxy = parts[1].strip()
    await msg.answer(f"✅ Прокси установлен:\n{Config.proxy}")

@dp.message(Command("noproxy"))
async def cmd_noproxy(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.proxy = None
    await msg.answer("✅ Прокси убран, работаю напрямую")

@dp.message(Command("check"))
async def cmd_check(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer("🔍 Проверяю...")
    ads = await parser.fetch()
    if ads is None:
        return await msg.answer("❌ Не удалось получить данные. Проверь прокси")
    if not ads:
        return await msg.answer("📭 Объявлений не найдено")

    new = [a for a in ads if a['url'] not in parser.seen_ads]
    await msg.answer(
        f"📊 Результат:\n"
        f"Всего: {len(ads)}\n"
        f"В базе: {len(parser.seen_ads)}\n"
        f"Новых: {len(new)}"
    )

@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    count = len(parser.seen_ads)
    parser.seen_ads.clear()
    parser.total_new = 0
    await msg.answer(f"🗑 База очищена! Было {count} объявлений")

@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        f"📈 **Статистика**\n\n"
        f"Объявлений в базе: {len(parser.seen_ads)}\n"
        f"Последняя выдача: {parser.total_found} шт\n"
        f"Новых отправлено: {parser.total_new}\n"
        f"Ошибок подряд: {parser.errors}\n"
        f"Последняя проверка: {parser.last_check or 'нет'}",
        parse_mode=ParseMode.MARKDOWN
    )

# ============================================================
#                    ЦИКЛ МОНИТОРИНГА
# ============================================================

async def monitoring_loop():
    """Основной цикл проверки OLX"""
    await asyncio.sleep(5)

    # Приветствие
    try:
        await bot.send_message(
            ADMIN_ID,
            "🚀 **OLX Sniper запущен!**\n\n"
            "Напиши /start для списка команд",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        log.error(f"Telegram ошибка: {e}")
        return  # Если токен невалидный — не запускаем цикл

    log.info("Мониторинг запущен")

    while True:
        if Config.is_running:
            ads = await parser.fetch()

            if ads:
                if not parser.seen_ads:
                    # Первый запуск — сохраняем базу
                    parser.seen_ads.update(a['url'] for a in ads)
                    log.info(f"✅ База: {len(ads)} объявлений")
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"📡 База собрана: {len(ads)} объявлений\n"
                            f"🔍 Слежу за новыми..."
                        )
                    except:
                        pass
                else:
                    # Ищем новые
                    for ad in ads:
                        if ad['url'] not in parser.seen_ads:
                            parser.seen_ads.add(ad['url'])
                            parser.total_new += 1

                            msg = (
                                f"🆕 **НОВОЕ ОБЪЯВЛЕНИЕ!**\n\n"
                                f"📦 {ad['title']}\n"
                                f"💰 {ad['price']}\n"
                                f"🔗 [Открыть на OLX]({ad['url']})"
                            )
                            try:
                                await bot.send_message(
                                    ADMIN_ID, msg,
                                    parse_mode=ParseMode.MARKDOWN,
                                    disable_web_page_preview=True
                                )
                                log.info(f"🆕 Отправлено: {ad['title']}")
                                await asyncio.sleep(1)
                            except Exception as e:
                                log.error(f"Ошибка отправки: {e}")

            # Пауза с рандомом
            delay = Config.interval + random.randint(10, 60)
            log.info(f"⏳ Следующая через {delay // 60}м {delay % 60}с")
            await asyncio.sleep(delay)
        else:
            await asyncio.sleep(10)

# ============================================================
#                    ЗАПУСК
# ============================================================

async def main():
    # Удаляем старый webhook
    await bot.delete_webhook(drop_pending_updates=True)

    # Flask в отдельном потоке
    threading.Thread(target=run_flask, daemon=True).start()

    log.info("=" * 50)
    log.info("🚀 OLX SNIPER BOT ЗАПУЩЕН")
    log.info("=" * 50)

    # Запускаем polling + мониторинг параллельно
    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
