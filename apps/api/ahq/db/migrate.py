from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from ahq.db.checkpointer import setup_checkpointer

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["url"] = url
    return config


def upgrade(direct_url: str) -> None:
    command.upgrade(alembic_config(direct_url), "head")
    asyncio.run(setup_checkpointer(direct_url))
