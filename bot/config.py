import os
from dataclasses import dataclass
from environs import Env


@dataclass
class BotConfig:
    token: str
    admin_ids: list[int]
    backend_url: str
    telegram_proxy: str | None = None


def load_bot_config(path: str | None = None) -> BotConfig:
    env = Env()
    if path and os.path.exists(path):
        env.read_env(path)
    else:
        env.read_env()

    token = env("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN must not be empty")

    raw_ids = env.list("ADMIN_IDS", default=[])
    admin_ids = [int(x) for x in raw_ids if str(x).isdigit()]
    backend_url = env("BACKEND_URL", default="http://127.0.0.1:8000")
    raw_proxy = env("TELEGRAM_PROXY", default=None)
    telegram_proxy = raw_proxy.strip() if raw_proxy and raw_proxy.strip() else None

    return BotConfig(
        token=token,
        admin_ids=admin_ids,
        backend_url=backend_url,
        telegram_proxy=telegram_proxy,
    )
