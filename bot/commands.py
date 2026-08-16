import discord
from discord import ApplicationContext
from discord.ext import commands

def setup_commands(bot: commands.Bot, queue):
    @bot.slash_command(name="generate", description="Generate a video from a script")
    async def generate(ctx: ApplicationContext, script: str, genre: str = "story"):
        await ctx.defer()
        job_id = await queue.add_job(ctx.author.id, ctx.channel_id, script, genre)
        embed = discord.Embed(title="🎬 Video Generation Started",
                              description="Your job has been queued.", color=discord.Color.blue())
        embed.add_field(name="Job ID", value=f"`{job_id}`", inline=True)
        embed.add_field(name="Position", value=await queue.get_position(job_id), inline=True)
        embed.add_field(name="Script Preview", value=f"{script[:100]}...", inline=False)
        await ctx.followup.send(embed=embed)

    @bot.slash_command(name="status", description="Check job status")
    async def status(ctx: ApplicationContext, job_id: str):
        info = await queue.get_status(job_id)
        if not info:
            await ctx.respond(f"Job `{job_id}` not found.", ephemeral=True)
            return
        emoji = {"COMPLETED": "✅", "FAILED": "❌", "PENDING": "⏳"}.get(info["status"], "⏳")
        embed = discord.Embed(title=f"{emoji} {info['status']}",
                            color=discord.Color.green() if info["status"] == "COMPLETED" else discord.Color.blue())
        embed.add_field(name="Progress", value=f"{info.get('progress', 0)}%", inline=True)
        if info.get("current_step"):
            embed.add_field(name="Step", value=info["current_step"], inline=False)
        if info.get("error"):
            embed.add_field(name="Error", value=f"```{info['error'][:500]}```", inline=False)
        await ctx.respond(embed=embed, ephemeral=True)

    @bot.slash_command(name="queue", description="Show pending jobs")
    async def queue_cmd(ctx: ApplicationContext):
        jobs = await queue.list_pending()
        if not jobs:
            await ctx.respond("No pending jobs.", ephemeral=True)
            return
        embed = discord.Embed(title="📋 Queue", color=discord.Color.blue())
        for i, job in enumerate(jobs[:10], 1):
            embed.add_field(name=f"{i}. {job['job_id'][:8]}",
                          value=f"{job.get('progress', 0)}% — {job.get('current_step', 'waiting')}", inline=False)
        await ctx.respond(embed=embed, ephemeral=True)

    @bot.slash_command(name="voices", description="List TTS voices")
    async def voices_cmd(ctx: ApplicationContext):
        from generator.tts_engine import TTSEngine
        voices = TTSEngine().get_female_voices()
        embed = discord.Embed(title="🎙️ Female Voices", color=discord.Color.blue())
        for v in voices:
            embed.add_field(name=f"{v['name']} (`{v['id']}`)", value=f"Quality: {v['grade']}", inline=True)
        await ctx.respond(embed=embed, ephemeral=True)
