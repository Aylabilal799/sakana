import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
env_path = PROJECT_ROOT / "config" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    # ONE-SHOT GUARD: Discord reconnects re-fire on_ready().
    # Without this guard, every reconnect re-creates JobQueue and re-syncs commands,
    # eventually corrupting the command registry and killing the bot.
    if getattr(bot, "_mia_ready", False):
        logger.info("on_ready re-fired (Discord reconnect) — skipping setup.")
        return
    bot._mia_ready = True

    logger.info("Bot logged in as %s (ID: %s)", bot.user, bot.user.id)

    from bot.queue_worker import JobQueue
    bot.job_queue = JobQueue(bot)
    logger.info("JobQueue attached")

    from bot.commands import setup as setup_commands
    setup_commands(bot)
    logger.info("Commands registered")

    try:
        if GUILD_ID:
            await bot.sync_commands(guild_ids=[GUILD_ID])
            logger.info("Synced commands to guild %s", GUILD_ID)
        else:
            await bot.sync_commands()
            logger.info("Synced global commands")
    except Exception as e:
        logger.exception("sync_commands failed: %s", e)

    logger.info("Bot is fully ready")

bot.run(TOKEN)
