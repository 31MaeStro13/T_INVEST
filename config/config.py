import logging
import os
from dataclasses import dataclass

from environs import Env 

logger = logging.getLogger(__name__)

@dataclass
class BotSettings:
    token: str 
    admin_ids: list[int]

@dataclass
class LoggSettings:
    level: str 
    format: str 

@dataclass
class TBank:
    token: str 

@dataclass
class Security:
    token: str 

@dataclass 
class Config:
    bot: BotSettings
    log: LoggSettings
    tbank: TBank
    sec: Security

def load_config(path: str | None = None) -> Config:
    
    env = Env()

    if path: 
        if not os.path.exists(path):
            logger.warning(".env file not found at '%s', skipping...", path)
        else:
            logger.info("Loading .env from '%s'", path)
            env.read_env(path)
    else:
        env.read_env()


    token = env("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN must not be empty")

    raw_ids = env.list("ADMIN_IDS", default=[])

    try:
        admin_ids = [int(x) for x in raw_ids]
    except ValueError as e:
        raise ValueError(f"ADMIN_IDS must be integers, got: {raw_ids}") from e 

    tbank_token = env("T_BANK_READ_ONLY_INVEST_TOKEN")

    sec_token = env("ENCRYPTION_KEY")

    logg_settings = LoggSettings(
        level=env("LOG_LEVEL", default="INFO"),
        format=env("LOG_FORMAT", default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    logger.info("Configuration loaded successfully")

    return Config(
        bot=BotSettings(token=token, admin_ids=admin_ids),
        log=logg_settings,
        tbank=TBank(token=tbank_token),
        sec=Security(token=sec_token),
    )
