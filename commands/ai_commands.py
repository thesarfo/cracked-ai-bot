import discord
from discord.ext import commands

from services.ai_service import get_ai_service
from utils.discord_helpers import send_long_message
from utils.logging import get_logger

logger = get_logger("commands")


def setup_ai_commands(bot: commands.Bot):
  ai_service = get_ai_service()

  @bot.command()
  async def chat(ctx, *, message: str):
    """Main AI chat command with Google Search grounding and server chat history."""
    if not message:
      await ctx.send("Please provide a message to chat with the AI!")
      return

    if not ctx.guild:
      await ctx.send("This command can only be used in a server.")
      return

    logger.info(f"💬 Chat from {ctx.author.display_name}: {message[:50]}...")

    messages_per_channel = 20
    max_total_messages = 100

    system_msg = (
      "You are professional, calm, and helpful bot in a Discord server. "
      "Keep responses SHORT and conversational - like texting a friend or a co-worker. "
      "Don't lecture, don't give unsolicited advice, don't be preachy. "
      "Just answer what's asked. Use casual language. "
      "Only use Google Search results when the question actually needs current info or historical information. "
      "The chat history is just for context - don't summarize it or reference it explicitly."
    )

    async with ctx.typing():
      context_messages = []

      # Gather messages from all text channels in the guild
      for channel in ctx.guild.text_channels:
        try:
          if not channel.permissions_for(ctx.guild.me).read_message_history:
            continue

          async for ctx_msg in channel.history(limit=messages_per_channel):
            if ctx_msg.author.bot:
              continue
            context_messages.append({
              "timestamp": ctx_msg.created_at,
              "channel": channel.name,
              "author": ctx_msg.author.display_name,
              "content": ctx_msg.content,
            })

        except discord.Forbidden:
          continue

      # Sort by timestamp and take the most recent
      context_messages.sort(key=lambda x: x["timestamp"])
      context_messages = context_messages[-max_total_messages:]

      # Format for the prompt
      chat_history = "\n".join(
        f"[#{m['channel']}] {m['author']}: {m['content']}"
        for m in context_messages
      )

      prompt = (
        f"Here is the recent message history from across the server:\n\n"
        f"--- CHAT HISTORY ---\n"
        f"{chat_history}\n"
        f"--- END HISTORY ---\n\n"
        f"User message to respond to: {message}"
      )

      response = await ai_service.call_gemini_ai(
        prompt, system_message=system_msg, use_search=True
      )

    logger.info(f"💬 Response sent to {ctx.author.display_name}")
    await send_long_message(ctx, response)

  @bot.command()
  async def ai_status(ctx):
    """Check if the AI is working."""
    logger.info(f"🔧 Status check from {ctx.author.display_name}")
    async with ctx.typing():
      test_response = await ai_service.call_gemini_ai(
        "Hello, respond with 'Gemini AI is working correctly!'",
        use_search=False,
      )

    if "Error" in test_response:
      await ctx.send(f"❌ GEMINI API Error: {test_response}")
    else:
      await ctx.send(f"✅ GEMINI API is working! Response: {test_response}")
