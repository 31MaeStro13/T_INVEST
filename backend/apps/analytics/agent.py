"""
AI-агент финансового аудита на базе фреймворка Agno и Google Gemini API.
Реализует паттерн Tool Calling (Function Calling) поверх аналитического ядра NumPy.
Строго соответствует ст. 6.1 Федерального закона № 39-ФЗ (Zero-Recommendation Policy).
"""
import os
import logging
from typing import Any
from dotenv import load_dotenv

from agno.agent import Agent
from agno.models.google import Gemini

load_dotenv()
logger = logging.getLogger(__name__)

def _detect_proxy() -> str | None:
    custom_proxy = os.getenv("GEMINI_PROXY") or os.getenv("HTTPS_PROXY")
    if custom_proxy and "127.0.0.1" not in custom_proxy:
        return custom_proxy

    # Внутри Docker 127.0.0.1 хоста доступен через IP шлюза контейнера
    if os.path.exists("/.dockerenv"):
        import socket, struct
        try:
            with open("/proc/net/route") as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 3 and fields[1] == "00000000":
                        gw_ip = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
                        return f"http://{gw_ip}:10808"
        except Exception:
            return "http://172.19.0.1:10808"
        return "http://172.19.0.1:10808"

    return os.getenv("TELEGRAM_PROXY") or "http://127.0.0.1:10808"


_proxy = _detect_proxy()
if _proxy:
    os.environ["HTTPS_PROXY"] = _proxy
    os.environ["HTTP_PROXY"] = _proxy




def make_portfolio_tools(telegram_id: int):
    """
    Фабрика инструментов (Tools) для Agno.
    Замыкает telegram_id пользователя, чтобы агент не запрашивал ID у пользователя.
    """
    from users.models import InvestorUser
    from analytics.service import get_consolidated_analytics
    from portfolio.services import get_consolidated_snapshot

    def get_portfolio_risk_metrics() -> dict[str, Any]:
        """
        Возвращает точные математические риск-метрики портфеля инвестора.
        Используй этот инструмент при вопросах о рисках, волатильности, просадке,
        коэффициенте Шарпа и перекосах в концентрации активов.

        Returns:
            dict: Словарь с метриками:
                - total_value (float): текущая стоимость всех активов в рублях.
                - sharpe_ratio (float | None): коэффициент Шарпа относительно ставки ЦБ.
                - volatility_annual (float | None): годовая волатильность в процентах.
                - max_drawdown (float | None): максимальная историческая просадка в процентах.
                - high_concentration (list): активы, доля которых превышает безопасные 25%.
                - is_diversified (bool): флаг сбалансированности портфеля.
        """
        user = InvestorUser.objects.filter(telegram_id=telegram_id).first()
        if not user:
            return {"error": "Пользователь не найден в системе"}

        analytics = get_consolidated_analytics(user)
        if not analytics:
            return {"error": "Нет данных для расчета рисков портфеля"}

        return {
            "total_value": round(float(analytics.get("total_value") or 0), 2),
            "sharpe_ratio": round(analytics["sharpe_ratio"], 2) if analytics.get("sharpe_ratio") is not None else None,
            "volatility_annual": round(analytics["volatility_annual"] * 100, 2) if analytics.get("volatility_annual") is not None else None,
            "max_drawdown": round(analytics["max_drawdown"] * 100, 2) if analytics.get("max_drawdown") is not None else None,
            "high_concentration": analytics.get("concentration_risk", []),
            "is_diversified": analytics.get("is_diversified", True),
            "verdict": analytics.get("verdict", ""),
        }

    def get_asset_allocation() -> dict[str, Any]:
        """
        Возвращает текущую структуру распределения капитала по классам активов.
        Используй этот инструмент при вопросах о долях акций, облигаций, фондов (ETF) и валюты.

        Returns:
            dict: Суммы и процентные доли классов активов (акции, облигации, фонды, кэш).
        """
        user = InvestorUser.objects.filter(telegram_id=telegram_id).first()
        if not user:
            return {"error": "Пользователь не найден в системе"}

        snap = get_consolidated_snapshot(user)
        if not snap:
            return {"error": "Снимок портфеля пуст или недоступен"}

        tot = float(snap.get("total_amount_portfolio") or 1.0)
        shares = float(snap.get("total_amount_shares") or 0.0)
        bonds = float(snap.get("total_amount_bonds") or 0.0)
        etf = float(snap.get("total_amount_etf") or 0.0)
        currencies = float(snap.get("total_amount_currencies") or 0.0)

        return {
            "total_rub": round(tot, 2),
            "shares": {"amount_rub": round(shares, 2), "percent": round((shares / tot) * 100, 1)},
            "bonds": {"amount_rub": round(bonds, 2), "percent": round((bonds / tot) * 100, 1)},
            "etf": {"amount_rub": round(etf, 2), "percent": round((etf / tot) * 100, 1)},
            "currencies": {"amount_rub": round(currencies, 2), "percent": round((currencies / tot) * 100, 1)},
        }

    return [get_portfolio_risk_metrics, get_asset_allocation]


def get_portfolio_auditor_agent(telegram_id: int) -> Agent:
    """
    Инициализирует и возвращает агента Agno для конкретного пользователя Telegram.
    """
    api_key = os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API key is not configured in environment")

    tools = make_portfolio_tools(telegram_id)

    agent = Agent(
        model=Gemini(
            id="gemini-3.1-flash-lite-preview",
            api_key=api_key,
        ),
        description=(
            "Ты — независимый цифровой аудитор портфелей частных инвесторов. "
            "Твоя задача — анализировать риски и переводить финансовую математику на человеческий язык."
        ),
        instructions=[
            "1. ОБЯЗАТЕЛЬНО используй инструменты (tools) для получения фактических данных о портфеле пользователя.",
            "2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать шаблонные вводные фразы: не пиши 'Я проанализировал ваш портфель', "
            "'Как робот-аудитор...', 'Здравствуйте' и т.д. Юридический дисклеймер ст. 6.1 39-ФЗ автоматически добавляется в конце сообщения. "
            "Сразу начинай ответ строго по существу с фактов и цифр.",
            "3. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕН Markdown: никаких решеток (#, ##, ###), никаких звездочек (**, *), никаких бэктиков (`). "
            "Пиши чистым текстом. Для заголовков блоков используй эмодзи и заглавные буквы (например, '📊 СТРУКТУРА АКТИВОВ:', '⚠️ РИСКИ:'). "
            "Для списков используй символ точки '• '.",
            "4. Соблюдай ст. 6.1 39-ФЗ: запрещено использовать слова 'купи', 'продай', 'рекомендую', 'советую приобрести', 'избавься'. "
            "Запрещено предлагать конкретные тикеры акций или облигаций для открытия сделок.",
            "5. Если пользователь просит инвестиционный совет ('Что купить?', 'Куда вложить 50к?'), коротко ответь: "
            "'Я не даю инвестиционных рекомендаций по закону 39-ФЗ, но готов разобрать текущие риски твоего портфеля'.",
            "6. Объясняй физический смысл метрик: что значит коэффициент Шарпа, почему опасна концентрация (>25%) "
            "и как историческая просадка соотносится с волатильностью.",
            "7. Отвечай емко, структурированно, без воды.",
        ],
        tools=tools,
        markdown=False,
    )
    return agent



def ask_auditor(telegram_id: int, user_query: str) -> str:
    """
    Точка входа для выполнения запроса пользователя к AI-агенту.
    """
    try:
        agent = get_portfolio_auditor_agent(telegram_id)
        response = agent.run(user_query, stream=False)
        return response.content or "Не удалось сформировать ответ аудитора."
    except Exception as e:
        logger.exception("Ошибка при обращении к AI-агенту: %s", e)
        return (
            "⚠️ Сервис AI-аудита временно недоступен. "
            "Пожалуйста, используйте стандартные отчеты и графики портфеля."
        )
