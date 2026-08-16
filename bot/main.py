import os, logging
from pathlib import Path
import discord
from discord.ext import tasks, commands
from bot.queue_worker import JobQueue

Path("/root/sakana/logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("/root/sakana/logs/bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
queue = JobQueue(bot)

@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user}")
    if not worker.is_running():
        worker.start()

@tasks.loop(seconds=10)
async def worker():
    await queue.process_next()

@worker.before_loop
async def before_worker():
    await bot.wait_until_ready()

from bot.commands import setup_commands
setup_commands(bot, queue)

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN not set!")
        exit(1)
    bot.run(token)
