import discord
from discord.ext import commands

from utils.logging import get_logger

logger = get_logger("utility")


def setup_utility_commands(bot: commands.Bot):
  @bot.command()
  async def ping(ctx):
    await ctx.send("pong")

  @bot.command()
  async def greet_user(ctx, user: discord.Member = None):
    if user:
      await ctx.send(f"{user.mention}, greetings!")
    else:
      await ctx.send("Hey everyone, greetings!")

  @bot.command()
  async def ai_help(ctx):
    help_text = """
**Bot Commands:**

`/chat <message>` - Chat with the AI agent (can look up members, channel context, DSA problems, and the web on its own)
`/ai_status` - Check if the AI is working

**Message Rotation:**

`/add_message <content> | <thread title>` - Add a message to the leetcode rotation
`/list_messages` - List messages in rotation
`/remove_message <index>` - Remove a message by index
`/rotation_status` - Show rotation status

**LeetCode Daily:**

`/force_leetcode` - Manually trigger the daily LeetCode post (Admin only)

**CSES Problem Set (in topic order, never shuffled):**

`/force_cses` - Manually trigger today's CSES problem (Admin only)
`/cses_progress` - Show progress through the CSES Problem Set

**Utility:**

`/ping` - Check if bot is responsive
`/greet_user [@user]` - Greet a user
`/force_dsa_summary` - Manually trigger today's problem-thread wrap-up (Admin only)

**Auto-Features:**
- Mention or reply to the bot to chat with AI
- LeetCode Daily Challenge posted automatically at 10:00 AM UTC
- CSES problem posted automatically at 3:00 PM UTC, one at a time in topic order
- Nightly wrap-up posted automatically at 10:00 PM UTC (who dropped a solution in today's threads)
"""
    await ctx.send(help_text)

  @bot.command()
  async def force_leetcode(ctx):
    """Manually triggers the LeetCode daily post (Admin only)."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return

    await ctx.send("⏳ Fetching LeetCode daily question...")

    from services.leetcode_service import get_leetcode_service
    leetcode_service = get_leetcode_service()

    question = await leetcode_service.fetch_daily_question()
    if not question:
        await ctx.send("❌ Failed to fetch daily question. Check logs.")
        return

    embed = leetcode_service.create_daily_embed(question)
    message = await ctx.send(embed=embed)

    question_title = question.get("question", {}).get("title", "Daily Question")
    await message.create_thread(name=f"🧵 {question_title}", auto_archive_duration=1440)

  @bot.command()
  async def force_dsa_summary(ctx):
    """Manually triggers today's problem-thread wrap-up (Admin only)."""
    if ctx.guild is None:
      await ctx.send("❌ This command only works inside a server.")
      return

    if not ctx.author.guild_permissions.administrator:
      await ctx.send("❌ You need administrator permissions to use this command.")
      return

    await ctx.send("📊 Building today's DSA wrap-up...")

    from services.scheduled_tasks import _scheduled_tasks_instance
    if _scheduled_tasks_instance is None:
      await ctx.send("❌ Scheduled tasks not initialized. Try again after the bot is fully ready.")
      return

    posted = await _scheduled_tasks_instance.post_daily_dsa_summary(
      target_channel_id=ctx.channel.id
    )
    if not posted:
      await ctx.send("No problem threads found for today in this channel.")

  @bot.command()
  async def force_cses(ctx):
    """Manually triggers today's CSES problem (Admin only)."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return

    await ctx.send("⏳ Getting today's CSES problem...")

    from services.cses_service import get_cses_service
    cses_service = get_cses_service()

    problem, position, total = cses_service.get_next_problem()
    if not problem:
        await ctx.send("❌ Failed to get CSES problem. Check logs.")
        return

    embed = cses_service.create_cses_embed(problem, position, total)
    message = await ctx.send(embed=embed)

    await message.create_thread(name=f"🧵 {problem['title']}", auto_archive_duration=1440)

  @bot.command()
  async def cses_progress(ctx):
    """Show the current CSES Problem Set progress."""
    from services.cses_service import get_cses_service
    cses_service = get_cses_service()

    current, total = cses_service.get_progress()

    if cses_service.problems:
        index = current - 1
        if index >= total:
            index = 0
        next_problem = cses_service.problems[index]
        category = next_problem.get("category", "Unknown")
        title = next_problem.get("title", "Unknown")

        await ctx.send(
            f"📘 **CSES Progress:** {current}/{total}\n"
            f"**Next up:** {title} — {category}"
        )
    else:
        await ctx.send("❌ CSES data not loaded.")
