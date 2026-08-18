import discord
import logging

logger = logging.getLogger(__name__)

def setup(bot):
    @bot.slash_command(name="mia", description="Generate a Mia AI video from a prompt")
    async def mia(ctx, prompt: str):
        await ctx.respond("🎬 Queuing Mia video generation...")
        try:
            job_id = await bot.job_queue.add_job(
                user_id=ctx.author.id,
                username=str(ctx.author),
                channel_id=ctx.channel.id,
                prompt=prompt,
                genre="auto"
            )
            await ctx.followup.send(
                f"✅ Job queued: `{job_id}`\n"
                f"Check status with `/miastatus {job_id}`"
            )
            await bot.job_queue.process_next()
        except Exception as e:
            logger.exception("Failed to queue /mia job")
            await ctx.followup.send(f"❌ Failed to queue job: {str(e)[:500]}")

    @bot.slash_command(name="miayt", description="Generate and schedule a Mia video for YouTube")
    async def miayt(ctx, date: str, time: str, script: str):
        await ctx.respond("📅 Parsing schedule and queuing...")
        try:
            scheduled = bot.job_queue.parse_scheduled_time(date, time)
            if not scheduled:
                await ctx.followup.send(
                    "❌ Invalid date/time format. Use `YYYY-MM-DD` and `HH:MM` (24h) or `HH:MM AM/PM`"
                )
                return
            job_id = await bot.job_queue.add_yt_job(
                user_id=ctx.author.id,
                username=str(ctx.author),
                channel_id=ctx.channel.id,
                prompt=script,
                genre="auto",
                scheduled_time=scheduled
            )
            await ctx.followup.send(
                f"✅ YouTube job queued: `{job_id}`\n"
                f"Scheduled for: `{scheduled.isoformat()}`\n"
                f"Check status with `/miastatus {job_id}`"
            )
            await bot.job_queue.process_next()
        except Exception as e:
            logger.exception("Failed to queue /miayt job")
            await ctx.followup.send(f"❌ Failed to queue job: {str(e)[:500]}")

    @bot.slash_command(name="miastatus", description="Check Mia video job status")
    async def miastatus(ctx, job_id: str):
        await ctx.respond("🔍 Checking status...")
        try:
            status = await bot.job_queue.get_status(job_id)
            if not status:
                await ctx.followup.send(f"❌ Job `{job_id}` not found.")
                return

            status_str = status.get("status", "UNKNOWN")
            stage = status.get("stage", "N/A")
            progress = status.get("progress", 0)

            color = discord.Color.blurple()
            if status_str == "COMPLETED":
                color = discord.Color.green()
            elif status_str == "FAILED":
                color = discord.Color.red()

            embed = discord.Embed(title=f"Job `{job_id}`", color=color)
            embed.add_field(name="Status", value=status_str, inline=True)
            embed.add_field(name="Stage", value=stage, inline=True)
            embed.add_field(name="Progress", value=f"{progress}%", inline=True)

            if status.get("youtube_scheduled_time"):
                embed.add_field(
                    name="YouTube Schedule", value=status["youtube_scheduled_time"], inline=False
                )
            if status.get("youtube_video_id"):
                embed.add_field(
                    name="YouTube Video",
                    value=f"https://youtube.com/watch?v={status['youtube_video_id']}",
                    inline=False,
                )
            if status.get("error_message"):
                embed.add_field(
                    name="Error", value=f"```{status['error_message'][:900]}```", inline=False
                )

            await ctx.followup.send(embed=embed)
        except Exception as e:
            logger.exception("Failed to get /miastatus")
            await ctx.followup.send(f"❌ Error: {str(e)[:500]}")

    logger.info("Registered commands: /mia, /miayt, /miastatus")
