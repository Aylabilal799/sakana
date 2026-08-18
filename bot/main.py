import asyncio
import logging
import math
import os
import sys
import time
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

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    heartbeat_timeout=120,
    guild_subscriptions=False,
    activity=discord.Game(name="Use /mia for Mia AI"),
    status=discord.Status.online,
)

# WATCHDOG FIX: 10 minutes instead of 2. Heavy CPU load from worker
# subprocess can delay asyncio event loop scheduling, causing
# on_socket_raw_receive to not fire even though the connection is healthy.
GATEWAY_WATCHDOG_TIMEOUT = 600
GATEWAY_WATCHDOG_CHECK_INTERVAL = 30
bot._last_gateway_activity = time.monotonic()

@bot.event
async def on_socket_raw_receive(msg):
    bot._last_gateway_activity = time.monotonic()

async def _gateway_watchdog():
    await bot.wait_until_ready()
    logger.info("Gateway watchdog started (timeout=%ss)", GATEWAY_WATCHDOG_TIMEOUT)
    while True:
        await asyncio.sleep(GATEWAY_WATCHDOG_CHECK_INTERVAL)
        idle = time.monotonic() - bot._last_gateway_activity

        # SECONDARY CHECK: if Discord latency is healthy, don't kill.
        # Under heavy CPU load, raw socket events may not fire promptly
        # even though heartbeats are being ACKed normally.
        lat = bot.latency
        if not (math.isnan(lat) or lat > 60.0):
            if idle > 90:
                logger.info("Watchdog: raw idle %.0fs but latency healthy (%.3fs) — staying alive", idle, lat)
            bot._last_gateway_activity = time.monotonic()
            continue

        if idle > GATEWAY_WATCHDOG_TIMEOUT:
            logger.critical("No gateway traffic for %.0fs — forcing exit", idle)
            os._exit(1)

@bot.event
async def on_ready():
    logger.info("Bot logged in as %s (ID: %s)", bot.user, bot.user.id)
    bot._last_gateway_activity = time.monotonic()

    if not hasattr(bot, "job_queue") or bot.job_queue is None:
        from bot.queue_worker import JobQueue
        bot.job_queue = JobQueue(bot)
        logger.info("JobQueue attached")

    if not getattr(bot, "_watchdog_task", None) or bot._watchdog_task.done():
        bot._watchdog_task = asyncio.create_task(_gateway_watchdog())

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
    except discord.HTTPException as e:
        if e.status == 429:
            logger.warning("sync_commands rate limited")
        else:
            logger.exception("sync_commands failed: %s", e)

    logger.info("Bot is fully ready")

@bot.event
async def on_disconnect():
    logger.warning("Discord gateway disconnected")
    bot._last_gateway_activity = time.monotonic()

@bot.event
async def on_resumed():
    logger.info("Discord gateway reconnected")
    bot._last_gateway_activity = time.monotonic()

bot.run(TOKEN, reconnect=True)
