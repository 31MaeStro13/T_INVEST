> 📍 Навигация: [[MOC_IT_Engineering|💻 IT & Инженерия]] | [[00_Home|🪐 Главная]] | [[Backend_Interview_Question_Bank_150k|🎯 Собеседования 150k]]

# 🏦 T-Bank (Tinkoff) Invest API v2: Архитектура, gRPC и разработка на Python

> [!ABSTRACT] О чем этот конспект
> Фундаментальное практическое руководство по работе с официальным биржевым API Т-Банка (Tinkoff Investments v2).
> Разбор протокола gRPC, Protobuf-типов денег, работы асинхронного SDK `t-tech-investments`, отказоустойчивости, архитектуры портфеля и запрета на `float` в финтехе.

---

## 🧭 Содержание
1. [[#1. Архитектура: Почему gRPC и Protobuf вместо REST/JSON|1. Архитектура: Почему gRPC и Protobuf вместо REST/JSON]]
2. [[#2. Экосистема SDK и настройка окружения (uv)|2. Экосистема SDK и настройка окружения (uv)]]
3. [[#3. Безопасность и модель токенов (Zero-Leak)|3. Безопасность и модель токенов (Zero-Leak)]]
4. [[#4. Карта сервисов API (Кто за что отвечает)|4. Карта сервисов API]]
5. [[#5. Финансовая точность: Protobuf-деньги (Zero Float Rule)|5. Финансовая точность: Protobuf-деньги]]
6. [[#6. Анатомия портфеля и счетов|6. Анатомия портфеля и счетов]]
7. [[#7. Отказоустойчивость: Rate Limits, Retry Backoff и ошибки|7. Отказоустойчивость: Rate Limits и ошибки]]
8. [[#8. Практическая шпаргалка (Production Code Snippets)|8. Практическая шпаргалка (Код)]]

---

## 1. Архитектура: Почему gRPC и Protobuf вместо REST/JSON

Т-Банк Инвестиции используют **gRPC** как основной транспорт для v2 API. 

### Сравнение протоколов:
| Критерий | REST / JSON | gRPC / Protocol Buffers |
| :--- | :--- | :--- |
| **Транспорт** | HTTP/1.1 (чаще всего) | HTTP/2 (бинарный, мультиплексирование в 1 TCP-соединении) |
| **Формат данных** | Текстовый JSON (тяжелый, парсинг строк) | Бинарный Protobuf (минимальный оверхед, сжатие байт) |
| **Контракт** | OpenAPI / Swagger (дескриптивный, часто нестрогий) | Строгие схемы `.proto` (строгая кодогенерация типов) |
| **Стриминг** | WebSocket или Long Polling (отдельные костыли) | Нативный двунаправленный стриминг (Bidirectional Streams) |
| **Задержки (Latency)** | Десятки/сотни миллисекунд | Единицы миллисекунд (критично для биржевого трейдинга) |

> [!NOTE] Как это работает под капотом
> Клиент открывает постоянное HTTP/2 соединение (Channel) с сервером `invest-public-api.tinkoff.ru:443`.
> Вместо сериализации в длинные JSON-строки `{"account_id": "216..."}`, Protobuf кодирует поля в компактные бинарные тэги и байты.

---

## 2. Экосистема SDK и настройка окружения (uv)

### Важная трансформация пакетов:
* **Старое имя (устарело / удалено с PyPI):** `tinkoff-investments`
* **Актуальное имя (официальный SDK Т-Банка):** `t-tech-investments`
* **Официальный репозиторий пакетов:** GitLab Т-Банка (`https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple`)
* **Имя модуля в коде:** `import t_tech.invest`

### Конфигурация через `uv` (`pyproject.toml`):
Чтобы `uv` автоматически находил и устанавливал SDK из репозитория Т-Банка:

```toml
[project]
name = "t-invest"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "t-tech-investments>=1.49.3",
    "environs>=15.2.0",
]

[[tool.uv.index]]
name = "tbank"
url = "https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple"
```

> [!WARNING] Версия Python
> Используйте стабильный **Python 3.12**. В слишком новых версиях (например, Python 3.14 pre-release) отсутствуют готовые бинарные сборки (`wheels`) для C-расширений `grpcio` и `protobuf`, что приводит к падению компилятора C++ при сборке.

---

## 3. Безопасность и модель токенов (Zero-Leak)

### Типы токенов:
1. **Только для чтения (Read-Only)** — идеален для аналитики, аудита портфеля, расчета налогов и алертов. Не позволяет выставлять ордера.
2. **Песочница (Sandbox)** — изолированная виртуальная среда со своими виртуальными счетами и деньгами.
3. **Полный доступ (Full Access)** — позволяет совершать торговые операции (требуется только для торговых роботов).

### Архитектурный стандарт хранения (Zero-Leak):
* Токен **никогда** не пишется в коде и не коммитится в Git.
* Хранение: файл `.env` (обязательно в `.gitignore`).
* В БД боевого бэкенда токены клиентов хранятся **только в зашифрованном виде** (симметричный шифр `AES-128-CBC` / `Fernet` из библиотеки `cryptography`).

---

## 4. Карта сервисов API (Кто за что отвечает)

SDK предоставляет доступ к сервисам через фасад `AsyncClient` (асинхронный) или `Client` (синхронный).

```
AsyncClient
 ├── client.users         # Счета, профиль, комиссии, маржинальные показатели
 ├── client.operations    # Портфель, остатки, позиции, история сделок/операций
 ├── client.instruments   # Каталог бумаг (акции, облигации, фонды), дивиденды, купоны
 ├── client.market_data   # Цены, стаканы (OrderBook), свечи (Candles), торговые статусы
 ├── client.orders        # Выставление, отмена и просмотр торговых поручений
 ├── client.stop_orders   # Стоп-лосс и тейк-профит заявки
 └── client.sandbox       # Управление виртуальными счетами песочницы
```

### Основные методы:
* `await client.users.get_accounts()` — возвращает список счетов инвестора.
* `await client.operations.get_portfolio(account_id=...)` — моментальный срез портфеля (баланс, валюты, открытые позиции).
* `await client.operations.get_positions(account_id=...)` — детальный список заблокированных и свободных бумаг.
* `await client.operations.get_operations(account_id=..., from_=..., to=...)` — история финансовых операций (пополнения, выводы, дивиденды, покупки).
* `await client.instruments.get_dividends(figi=..., from_=..., to=...)` — календарь дивидендных выплат по бумаге.
* `await client.market_data.get_candles(...)` — исторические свечи для технического анализа и расчета волатильности.

---

## 5. Финансовая точность: Protobuf-деньги (Zero Float Rule)

> [!CAUTION] Железное правило финансового бэкенда
> **Использование чисел с плавающей точкой (`float`) для хранения и расчета денег СТРОГО ЗАПРЕЩЕНО.**
> В стандарте IEEE 754: `0.1 + 0.2 = 0.30000000000000004`. В банковском учете это ведет к балансовым расхождениям и судебным искам.

### Как Protobuf передает деньги:
В protobuf-сообщениях нет float для валют. Используются два типа:
1. `MoneyValue`: сумма с указанием валюты (`currency`, `units`, `nano`).
2. `Quotation`: сумма или коэффициент без валюты (`units`, `nano`).

#### Поля структуры:
* `units` (`int64`): целая часть суммы (например, рубли или доллары).
* `nano` (`int32`): дробная часть, умноженная на $10^9$ (один миллиард). Может быть отрицательной при отрицательных величинах.

$$\text{Сумма} = \text{units} + \frac{\text{nano}}{10^9}$$

### Математический конвертер в Python `Decimal`:

```python
from decimal import Decimal
from typing import Union
from t_tech.invest.schemas import MoneyValue, Quotation

def money_to_decimal(value: Union[MoneyValue, Quotation, None]) -> Decimal:
    """Конвертирует Protobuf MoneyValue/Quotation в Decimal без потери точности."""
    if value is None:
        return Decimal("0.0")
    
    # units - целая часть, nano - миллиардные доли
    return Decimal(value.units) + Decimal(value.nano) / Decimal(1_000_000_000)

def decimal_to_quotation(d: Decimal) -> Quotation:
    """Конвертирует Decimal обратно в Protobuf Quotation (для выставления заявок)."""
    units = int(d)
    nano = int((d - Decimal(units)) * Decimal(1_000_000_000))
    return Quotation(units=units, nano=nano)
```

*(В библиотеке также есть встроенные функции: `from t_tech.invest.utils import quotation_to_decimal, money_to_decimal`).*

---

## 6. Анатомия портфеля и счетов

### 1. `Account` (Счет инвестора):
* `id` (`str`): Уникальный ID счета (например, `'2167614098'`). Требуется во всех запросах.
* `name` (`str`): Человеческое имя («Брокерский счет», «ИИС»).
* `type`: Тип аккаунта (`ACCOUNT_TYPE_TINKOFF`, `ACCOUNT_TYPE_TINKOFF_IIS` и т.д.).
* `status`: Статус (`ACCOUNT_STATUS_OPEN` = 2, активен).

### 2. `PortfolioResponse` (Срез портфеля):
При вызове `get_portfolio(account_id)` возвращается объект с агрегатами:
* `total_amount_portfolio` (`MoneyValue`): Общая оценочная стоимость всех активов счета.
* `total_amount_shares`: Сумма всех акций.
* `total_amount_bonds`: Сумма всех облигаций.
* `total_amount_etf`: Сумма фондов.
* `total_amount_currencies`: Сумма свободной валюты / кэша.
* `expected_yield` (`Quotation`): Текущая относительная доходность портфеля.
* `positions` (`list[PortfolioPosition]`): Список всех открытых бумаг.

### 3. `PortfolioPosition` (Позиция по конкретной бумаге):
* `figi` / `instrument_uid`: Международный или внутренний идентификатор инструмента.
* `instrument_type`: Тип актива (`share`, `bond`, `etf`, `currency`).
* `quantity`: Количество штук/лотов в портфеле (`Quotation`).
* `current_price`: Текущая рыночная цена за 1 бумагу (`MoneyValue`).
* `average_position_price`: Средняя цена покупки (для расчета точки безубыточности).
* `expected_yield`: Абсолютный текущий PnL (профит/убыток в валюте).

---

## 7. Отказоустойчивость: Rate Limits, Retry Backoff и ошибки

### 1. Лимиты запросов (Rate Limits)
Т-Банк жестко ограничивает число запросов в минуту (RPS):
* Превышение лимита возвращает gRPC статус: **`RESOURCE_EXHAUSTED`** (HTTP аналог: 429).
* В метаданных ответа передается заголовок `x-ratelimit-reset` — через сколько секунд лимит сбросится.

### 2. Иерархия исключений в SDK:
```
InvestError (базовое исключение)
 ├── RequestError (ошибка бизнес-логики: неверный счет, тикер, нет прав)
 └── AioRequestError (сетевая gRPC ошибка: таймаут, разрыв канала, лимиты)
```

### 3. Паттерн экспоненциального отката (Exponential Retry Backoff):

```python
import asyncio
import logging
from t_tech.invest.exceptions import AioRequestError

logger = logging.getLogger(__name__)

async def execute_with_retry(coro_func, max_retries: int = 3, initial_delay: float = 1.0):
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_func()
        except AioRequestError as exc:
            # gRPC ResourceExhausted или сетевой сбой
            if "RESOURCE_EXHAUSTED" in str(exc) or attempt < max_retries:
                logger.warning(
                    "gRPC сбой (попытка %d/%d). Ожидание %.2f сек...",
                    attempt, max_retries, delay
                )
                await asyncio.sleep(delay)
                delay *= 2  # экспоненциальное увеличение задержки (1s, 2s, 4s...)
            else:
                raise
```

---

## 8. Практическая шпаргалка (Production Code Snippets)

### Сниппет: Получение полной структуры портфеля

```python
import asyncio
from decimal import Decimal
from environs import Env
from t_tech.invest import AsyncClient
from t_tech.invest.utils import money_to_decimal, quotation_to_decimal

env = Env()
env.read_env()
TOKEN = env("T_BANK_READ_ONLY_INVEST_TOKEN")

async def inspect_portfolio():
    async with AsyncClient(TOKEN) as client:
        # 1. Получаем счета
        accounts_res = await client.users.get_accounts()
        open_accounts = [a for a in accounts_res.accounts if a.status == 2]

        for acc in open_accounts:
            print(f"\n📂 Счет: {acc.name} [ID: {acc.id}]")
            
            # 2. Запрашиваем портфель
            portfolio = await client.operations.get_portfolio(account_id=acc.id)
            total_val = money_to_decimal(portfolio.total_amount_portfolio)
            currency = portfolio.total_amount_portfolio.currency.upper()
            
            print(f"💰 Общая стоимость: {total_val:,.2f} {currency}")
            
            # 3. Доли классов активов
            shares = money_to_decimal(portfolio.total_amount_shares)
            bonds = money_to_decimal(portfolio.total_amount_bonds)
            etf = money_to_decimal(portfolio.total_amount_etf)
            cash = money_to_decimal(portfolio.total_amount_currencies)
            
            if total_val > 0:
                print(f"   ├─ Акции: {shares:,.2f} ({shares / total_val * 100:.1f}%)")
                print(f"   ├─ Облигации: {bonds:,.2f} ({bonds / total_val * 100:.1f}%)")
                print(f"   ├─ Фонды: {etf:,.2f} ({etf / total_val * 100:.1f}%)")
                print(f"   └─ Кэш: {cash:,.2f} ({cash / total_val * 100:.1f}%)")

            # 4. Список позиций
            print(f"📦 Позиций в портфеле: {len(portfolio.positions)}")
            for pos in portfolio.positions:
                qty = quotation_to_decimal(pos.quantity)
                price = money_to_decimal(pos.current_price)
                yield_val = quotation_to_decimal(pos.expected_yield)
                print(f"   • FIGI: {pos.figi} | {qty} шт. по {price} | PnL: {yield_val:+,.2f}")

if __name__ == "__main__":
    asyncio.run(inspect_portfolio())
```

---

## 🔗 Связанные заметки
* [[Backend_Interview_Question_Bank_150k|🎯 Вопросы для собеседований на Middle Backend]]
* [[Контент по UV|📘 Менеджер пакетов UV]]
* [[MOC_IT_Engineering|💻 IT & Инженерия MOC]]
