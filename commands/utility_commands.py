from discord.ext import commands

from utils.logging import get_logger

logger = get_logger("utility")


def setup_utility_commands(bot: commands.Bot):
  @bot.command()
  async def ping(ctx):
    await ctx.send("pong")

  @bot.command()
  async def greet_user(ctx, user: str = "everyone"):
    await ctx.send(f"@{user}, greetings!")

  @bot.command()
  async def ai_help(ctx):
    help_text = """
**Bot Commands:**

`/chat <message>` - Chat with the AI (uses Google Search for up-to-date info)
`/ai_status` - Check if the AI is working

**Message Rotation:**

`/add_message <content> | <thread title>` - Add a message to the leetcode rotation
`/list_messages` - List messages in rotation
`/remove_message <index>` - Remove a message by index
`/rotation_status` - Show rotation status

**LeetCode:**

`/force_leetcode` - Manually trigger the daily LeetCode post (Admin only)

**Utility:**

`/ping` - Check if bot is responsive
`/greet_user [username]` - Greet a user

**Auto-Features:**
- Mention or reply to the bot to chat with AI
- Daily LeetCode question posted automatically
"""
    await ctx.send(help_text)

  @bot.command()
  async def force_leetcode(ctx):
    """Manually triggers the LeetCode daily post (Admin only)."""
    # Simple check for admin permissions or specific user
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
    
    # Create thread
    question_title = question.get("question", {}).get("title", "Daily Question")
    await message.create_thread(name=f"🧵 {question_title}", auto_archive_duration=1440)
