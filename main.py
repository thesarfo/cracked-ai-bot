import hashlib
import json
import random
from pathlib import Path

import discord
from discord.ext import commands

from commands import ai_commands, message_commands, utility_commands
from config import GEMINI_API_KEY, TOKEN, WELCOME_CHANNEL_NAME, WORDLE_CHANNEL_NAME
from db import message_db
from utils.logging import get_logger, setup_logging

# Initialize logging
setup_logging()
logger = get_logger("main")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)

# Load the easy problems once at startup for new-member welcomes
_NEETCODE_PATH = Path(__file__).parent / "data" / "neetcode150.json"
try:
  with _NEETCODE_PATH.open() as f:
    _ALL_PROBLEMS = json.load(f)
  EASY_PROBLEMS = [p for p in _ALL_PROBLEMS if p.get("difficulty") == "Easy"]
except (FileNotFoundError, json.JSONDecodeError) as e:
  logger.warning(f"Could not load neetcode problems for welcome: {e}")
  EASY_PROBLEMS = []


@bot.event
async def on_ready():
  logger.info(f"Bot connected as {bot.user}")

  await message_db.init_db()
  logger.info("Database initialized")

  # Initialize scheduled tasks
  from services.scheduled_tasks import setup_scheduled_tasks

  scheduled_tasks = setup_scheduled_tasks(bot)
  await scheduled_tasks.hydrate_missing_weekly_activity()


@bot.event
async def on_member_join(member: discord.Member):
  channel = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL_NAME)
  if not channel:
    logger.debug(f"No #{WELCOME_CHANNEL_NAME} in {member.guild.name}; skipping welcome")
    return

  embed = discord.Embed(
    title=f"👋 Welcome, {member.display_name}!",
    description=f"Glad to have you in **{member.guild.name}**. Grab a chair and get grinding.",
    color=discord.Color.green(),
  )

  if EASY_PROBLEMS:
    problem = random.choice(EASY_PROBLEMS)
    embed.add_field(
      name="🧩 Warm-up problem",
      value=f"[{problem['title']}]({problem['link']}) — *{problem['category']}*",
      inline=False,
    )

  try:
    await channel.send(content=member.mention, embed=embed)
    logger.info(f"👋 Welcomed {member} to {member.guild.name}")
  except discord.Forbidden:
    logger.warning(
      f"❌ Missing send permission in #{WELCOME_CHANNEL_NAME} ({member.guild.name})"
    )


@bot.event
async def on_member_remove(member: discord.Member):
  channel = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL_NAME)
  if not channel:
    return
  try:
    await channel.send(
      f"👋 **{member.display_name}** has left the server. See you on the leaderboard."
    )
    logger.info(f"👋 {member} left {member.guild.name}")
  except discord.Forbidden:
    logger.warning(
      f"❌ Missing send permission in #{WELCOME_CHANNEL_NAME} ({member.guild.name})"
    )


@bot.event
async def on_message(message: discord.Message):
  # Credit Wordle players — slash command interactions don't fire on_message for the user,
  # but the Wordle bot's response message contains interaction metadata for the user.
  if (
    message.author.bot
    and message.guild
    and message.interaction_metadata
    and hasattr(message.channel, "name")
    and message.channel.name == WORDLE_CHANNEL_NAME
  ):
    interaction = message.interaction_metadata
    content_hash = hashlib.sha256(str(interaction.id).encode()).hexdigest()
    await message_db.insert_message(
      message_id=str(interaction.id),
      channel_id=str(message.channel.id),
      guild_id=str(message.guild.id),
      author_id=str(interaction.user.id),
      content="[wordle]",
      content_hash=content_hash,
      message_url=message.jump_url,
      created_at=message.created_at,
    )

  # Ignore bot messages
  if message.author.bot:
    return

  # Track message for activity rankings
  if message.guild:
    content_hash = hashlib.sha256(str(message.id).encode()).hexdigest()
    await message_db.insert_message(
      message_id=str(message.id),
      channel_id=str(message.channel.id),
      guild_id=str(message.guild.id),
      author_id=str(message.author.id),
      content=message.content[:500] if message.content else "[attachment]",
      content_hash=content_hash,
      message_url=message.jump_url,
      created_at=message.created_at,
    )

  # Check if this is a reply to the bot's message
  is_reply_to_bot = False
  reply_chain = []

  if message.reference and message.reference.message_id:
    try:
      # Recursively fetch up to 5 previous messages in the chain to build context
      curr_msg = message
      for _ in range(5):
        if not curr_msg.reference or not curr_msg.reference.message_id:
          break

        prev_msg = await message.channel.fetch_message(curr_msg.reference.message_id)
        reply_chain.append(prev_msg)
        curr_msg = prev_msg

        # Check if the original message was replying to the bot
        if curr_msg.author == bot.user and curr_msg.id == message.reference.message_id:
          is_reply_to_bot = True

      reply_chain.reverse()  # Oldest to newest
    except discord.NotFound:
      pass

  # Check if bot was mentioned OR if it's a reply to the bot
  should_respond = (
    bot.user and bot.user.mentioned_in(message) and not message.mention_everyone
  ) or is_reply_to_bot

  if should_respond:
    content = message.content
    if bot.user:
      content = (
        content.replace(f"<@{bot.user.id}>", "")
        .replace(f"<@!{bot.user.id}>", "")
        .strip()
      )

    if content:
      logger.info(
        f"💬 {'Reply' if is_reply_to_bot else 'Mention'} from {message.author.display_name}: {content[:50]}..."
      )

      ctx = await bot.get_context(message)
      if ctx.guild:
        from services.ai_service import get_ai_service

        ai_service = get_ai_service()

        async with message.channel.typing():
          system_msg = (
            "You are professional, calm, and helpful bot in a Discord server."
            "Keep responses SHORT and conversational - like texting a friend or co-worker. "
            "Don't lecture, don't give unsolicited advice, don't be preachy. "
            "Just answer what's asked. Use casual language."
          )

          prompt = content

          # Build thread history string
          if reply_chain:
            thread_history = "\n".join(
              [f"{m.author.display_name}: {m.content}" for m in reply_chain]
            )
            prompt = f"--- CONVERSATION HISTORY ---\n{thread_history}\n--- END HISTORY ---\n\nUser's new message: {content}"

          response = await ai_service.call_gemini_ai(
            prompt, system_message=system_msg, use_search=True
          )

        # Send response as a reply to maintain the thread
        if len(response) > 2000:
          chunks = [response[i : i + 2000] for i in range(0, len(response), 2000)]
          for i, chunk in enumerate(chunks):
            if i == 0:
              await message.reply(chunk)
            else:
              await message.channel.send(chunk)
        else:
          await message.reply(response)

        logger.info(f"💬 Replied to {message.author.display_name}")
    return

  await bot.process_commands(message)


# Setup commands directly without unnecessary re-assignment
ai_commands.setup_ai_commands(bot)
message_commands.setup_message_commands(bot)
utility_commands.setup_utility_commands(bot)


if __name__ == "__main__":
  if not TOKEN:
    raise ValueError("Missing DISCORD_BOT_TOKEN in environment variables")
  if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY in environment variables")

  logger.info("Starting bot...")
  try:
    bot.run(TOKEN, log_handler=None)  # Disable default discord.py logging
  except KeyboardInterrupt:
    logger.info("Bot shutting down...")
