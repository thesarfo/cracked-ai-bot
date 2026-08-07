from discord.ext import commands

from services.agent_service import get_agent_service
from utils.discord_helpers import send_long_message
from utils.logging import get_logger

logger = get_logger("commands")


def setup_ai_commands(bot: commands.Bot):
  agent_service = get_agent_service()

  @bot.command()
  async def chat(ctx, *, message: str):
    """Main AI chat command. Remembers your conversation in this channel, and
    the agent can pull in channel context, look up members, search DSA
    problems, or search the web on its own via tools."""
    if not message:
      await ctx.send("Please provide a message to chat with the AI!")
      return

    if not ctx.guild:
      await ctx.send("This command can only be used in a server.")
      return

    logger.info(f"💬 Chat from {ctx.author.display_name}: {message[:50]}...")

    async with ctx.typing():
      response = await agent_service.run(
        message, guild=ctx.guild, channel=ctx.channel, user_id=ctx.author.id
      )

    logger.info(f"💬 Response sent to {ctx.author.display_name}")
    await send_long_message(ctx, response)

  @bot.command()
  async def ai_status(ctx):
    """Check if the AI is working."""
    logger.info(f"🔧 Status check from {ctx.author.display_name}")
    async with ctx.typing():
      test_response = await agent_service.run(
        f"Hello, respond with '{agent_service.provider_name} agent is working correctly!'",
        guild=ctx.guild,
      )

    if test_response.startswith("Error"):
      await ctx.send(f"❌ {agent_service.provider_name} API Error: {test_response}")
    else:
      await ctx.send(f"✅ {agent_service.provider_name} agent is working! Response: {test_response}")
