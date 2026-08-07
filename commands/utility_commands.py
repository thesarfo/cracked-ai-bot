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

**LeetCode & NeetCode:**

`/force_leetcode` - Manually trigger the daily LeetCode post (Admin only)
`/force_neetcode` - Manually trigger the next NeetCode 150 problem (Admin only)
`/neetcode_progress` - Show NeetCode 150 progress

**Daily DSA (shuffled LeetCode + Codeforces):**

`/force_dsa_leetcode` - Manually trigger today's shuffled LeetCode problem (Admin only)
`/force_dsa_codeforces` - Manually trigger today's shuffled Codeforces problem (Admin only)
`/dsa_progress` - Show progress through the shuffled LeetCode + Codeforces rotations
`/force_dsa_summary` - Manually trigger today's DSA thread wrap-up (Admin only)

**Utility:**

`/ping` - Check if bot is responsive
`/greet_user [@user]` - Greet a user

**Auto-Features:**
- Mention or reply to the bot to chat with AI
- Daily LeetCode question posted automatically
- Shuffled LeetCode problem posted automatically at 10:00 AM UTC
- Shuffled Codeforces problem auto-post is currently disabled (use `/force_dsa_codeforces`)
- Nightly DSA wrap-up posted automatically at 10:00 PM UTC (who dropped a solution in today's threads)
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
  async def force_neetcode(ctx):
    """Manually triggers the next NeetCode 150 problem (Admin only)."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return

    await ctx.send("⏳ Getting next NeetCode 150 problem...")
    
    from services.neetcode_service import get_neetcode_service
    neetcode_service = get_neetcode_service()
    
    problem, current, total = neetcode_service.get_next_problem()
    if not problem:
        await ctx.send("❌ Failed to get NeetCode problem. Check logs.")
        return
        
    embed = neetcode_service.create_neetcode_embed(problem, current, total)
    message = await ctx.send(embed=embed)
    
    await message.create_thread(name=f"🧵 NC150: {problem['title']}", auto_archive_duration=1440)

  @bot.command()
  async def force_dsa_leetcode(ctx):
    """Manually triggers today's shuffled LeetCode problem (Admin only)."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return

    await ctx.send("⏳ Getting today's shuffled LeetCode problem...")

    from services.dsa_daily_service import get_dsa_daily_service
    dsa_daily_service = get_dsa_daily_service()

    lc_problem, lc_pos, lc_total = dsa_daily_service.get_next_leetcode()
    if not lc_problem:
        await ctx.send("❌ Failed to get LeetCode problem. Check logs.")
        return

    embed = dsa_daily_service.create_leetcode_embed(lc_problem, lc_pos, lc_total)
    message = await ctx.send(embed=embed)
    await message.create_thread(name=f"🧵 {lc_problem['title']}", auto_archive_duration=1440)

  @bot.command()
  async def force_dsa_codeforces(ctx):
    """Manually triggers today's shuffled Codeforces problem (Admin only)."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return

    await ctx.send("⏳ Getting today's shuffled Codeforces problem...")

    from services.dsa_daily_service import get_dsa_daily_service
    dsa_daily_service = get_dsa_daily_service()

    cf_problem, cf_pos, cf_total = dsa_daily_service.get_next_codeforces()
    if not cf_problem:
        await ctx.send("❌ Failed to get Codeforces problem. Check logs.")
        return

    embed = dsa_daily_service.create_codeforces_embed(cf_problem, cf_pos, cf_total)
    message = await ctx.send(embed=embed)
    await message.create_thread(name=f"🧵 {cf_problem['title']}", auto_archive_duration=1440)

  @bot.command()
  async def dsa_progress(ctx):
    """Show progress through the shuffled LeetCode + Codeforces rotations."""
    from services.dsa_daily_service import get_dsa_daily_service
    dsa_daily_service = get_dsa_daily_service()

    (lc_next, lc_total), (cf_next, cf_total) = dsa_daily_service.get_progress()

    await ctx.send(
        f"📋 **Daily DSA Progress:**\n"
        f"LeetCode: {lc_next}/{lc_total}\n"
        f"Codeforces: {cf_next}/{cf_total}"
    )

  @bot.command()
  async def force_dsa_summary(ctx):
    """Manually triggers today's DSA thread wrap-up (Admin only)."""
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
      await ctx.send("No DSA threads found for today in this channel.")

  @bot.command()
  async def neetcode_progress(ctx):
    """Show the current NeetCode 150 progress."""
    from services.neetcode_service import get_neetcode_service
    neetcode_service = get_neetcode_service()
    
    current, total = neetcode_service.get_progress()
    
    # Get the next problem info without advancing
    if neetcode_service.problems:
        index = current - 1
        if index >= total:
            index = 0
        next_problem = neetcode_service.problems[index]
        category = next_problem.get("category", "Unknown")
        title = next_problem.get("title", "Unknown")
        difficulty = next_problem.get("difficulty", "Unknown")
        
        await ctx.send(
            f"📋 **NeetCode 150 Progress:** {current}/{total}\n"
            f"**Next up:** {title} ({difficulty}) — {category}"
        )
    else:
        await ctx.send("❌ NeetCode 150 data not loaded.")
