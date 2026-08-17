import logging
import traceback
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

def setup(bot):
    @bot.slash_command(name="mia", description="Generate a Mia AI video")
    async def mia_cmd(
        ctx: discord.ApplicationContext,
        prompt: discord.Option(str, "Describe Mia's vlog scene", required=True),
    ):
        await ctx.defer(ephemeral=False)
        try:
            job_id = await bot.job_queue.add_job(
                user_id=ctx.author.id,
                username=str(ctx.author),
                channel_id=ctx.channel_id,
                prompt=prompt,
                genre="auto",
            )
            embed = discord.Embed(
                title="Mia AI Video Queued",
                description="Job ID: `" + job_id + "`",
                color=discord.Color.blurple(),
            )
            display = prompt[:500] + "..." if len(prompt) > 500 else prompt
            embed.add_field(name="Prompt", value=display, inline=False)
            embed.add_field(name="Status", value="PENDING", inline=True)
            await ctx.followup.send(embed=embed)
            await bot.job_queue.process_next()
        except Exception as e:
            logger.exception("mia error")
            await ctx.followup.send("Error: " + str(e), ephemeral=True)

    @bot.slash_command(name="miastatus", description="Check Mia job status")
    async def mia_status_cmd(
        ctx: discord.ApplicationContext,
        job_id: discord.Option(str, "Job ID to check", required=True),
    ):
        try:
            status = await bot.job_queue.get_status(job_id)
            if not status:
                return await ctx.respond("Job `" + job_id + "` not found.", ephemeral=True)
            embed = discord.Embed(title="Job: `" + job_id + "`", color=discord.Color.blue())
            embed.add_field(name="Status", value=status.get("status", "UNKNOWN"), inline=True)
            embed.add_field(name="Stage", value=status.get("stage", "-"), inline=True)
            embed.add_field(name="Progress", value=str(status.get("progress", 0)) + "%", inline=True)
            if status.get("error_message"):
                embed.add_field(name="Error", value="```" + status["error_message"][:500] + "```", inline=False)
            await ctx.respond(embed=embed, ephemeral=True)
        except Exception as e:
            logger.exception("status error")
            await ctx.respond("Error: " + str(e), ephemeral=True)

    logger.info("Registered commands: /mia, /miastatus")
