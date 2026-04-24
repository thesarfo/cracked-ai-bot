import asyncio
import datetime

import discord
from discord.ext import tasks

from config import (
    ACTIVITY_CHANNEL_NAME,
    ED_CHANNEL_NAME,
    LEETCODE_CHANNEL_NAME,
    LEETCODE_DAILY_TIME_HOUR,
    LEETCODE_DAILY_TIME_MINUTE,
    MD_CHANNEL_NAME,
    WEEKLY_MIN_MEMBER_MESSAGES,
    WEEKLY_MIN_SERVER_MESSAGES,
    WEEKLY_RANKING_HOUR,
    WEEKLY_RANKING_MINUTE,
)
from db.message_db import get_weekly_message_counts
from services.leetcode_service import get_leetcode_service
from services.neetcode_service import get_neetcode_service
from utils.logging import get_logger

logger = get_logger("scheduler")


class ScheduledTasks:
    def __init__(self, bot):
        self.bot = bot
        self.leetcode_service = get_leetcode_service()
        self.neetcode_service = get_neetcode_service()
        
        # Calculate time for the loop
        self.daily_time = datetime.time(
            hour=LEETCODE_DAILY_TIME_HOUR,
            minute=LEETCODE_DAILY_TIME_MINUTE,
            tzinfo=datetime.timezone.utc
        )
        
        # Start loops
        self.daily_task.start()
        self.weekly_ranking_task.start()
        self.book_club_reminder_task.start()
        self.book_club_final_reminder_task.start()
        self.coworking_reminder_task.start()
        logger.info(f"📅 Daily scheduler initialized for {self.daily_time} UTC")

    def cog_unload(self):
        self.daily_task.cancel()
        self.weekly_ranking_task.cancel()
        self.book_club_reminder_task.cancel()
        self.book_club_final_reminder_task.cancel()
        self.coworking_reminder_task.cancel()

    @tasks.loop(time=[datetime.time(hour=LEETCODE_DAILY_TIME_HOUR, minute=LEETCODE_DAILY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_task(self):
        """Task that runs daily to post LeetCode daily + NeetCode 150."""
        logger.info("⏰ Running daily tasks")
        await self.post_daily_leetcode()
        await self.post_daily_neetcode()

    async def post_daily_leetcode(self, target_channel_id: int = None):
        """Fetch and post the LeetCode daily question."""
        try:
            question = await self.leetcode_service.fetch_daily_question()
            if not question:
                logger.error("Failed to fetch daily LeetCode question")
                return

            embed = self.leetcode_service.create_daily_embed(question)
            
            for guild in self.bot.guilds:
                target_channel = None
                
                if target_channel_id:
                    target_channel = guild.get_channel(target_channel_id)
                else:
                    target_channel = discord.utils.get(guild.text_channels, name=LEETCODE_CHANNEL_NAME)

                if target_channel:
                    try:
                        message = await target_channel.send(embed=embed)
                        
                        question_title = question.get("question", {}).get("title", "Daily Question")
                        thread_name = f"🧵 {question_title}"
                        await message.create_thread(name=thread_name, auto_archive_duration=1440)
                        
                        logger.info(f"✅ Posted LeetCode daily to {guild.name} #{target_channel.name}")
                    except discord.Forbidden:
                        logger.warning(f"❌ Missing permissions to post/thread to {guild.name} #{target_channel.name}")
                    except Exception as e:
                        logger.error(f"❌ Error posting to {guild.name}: {e}")
                else:
                    logger.debug(f"Skipping {guild.name}: No #{LEETCODE_CHANNEL_NAME} channel found")

        except Exception as e:
            logger.error(f"Error in daily LeetCode task: {e}")

    async def post_daily_neetcode(self, target_channel_id: int = None):
        """Post the next NeetCode 150 problem."""
        try:
            problem, current, total = self.neetcode_service.get_next_problem()
            if not problem:
                logger.error("Failed to get next NeetCode 150 problem")
                return

            embed = self.neetcode_service.create_neetcode_embed(problem, current, total)

            for guild in self.bot.guilds:
                target_channel = None

                if target_channel_id:
                    target_channel = guild.get_channel(target_channel_id)
                else:
                    target_channel = discord.utils.get(guild.text_channels, name=LEETCODE_CHANNEL_NAME)

                if target_channel:
                    try:
                        message = await target_channel.send(embed=embed)

                        thread_name = f"🧵 NC150: {problem['title']}"
                        await message.create_thread(name=thread_name, auto_archive_duration=1440)

                        logger.info(f"✅ Posted NeetCode 150 [{current}/{total}] to {guild.name} #{target_channel.name}")
                    except discord.Forbidden:
                        logger.warning(f"❌ Missing permissions in {guild.name} #{target_channel.name}")
                    except Exception as e:
                        logger.error(f"❌ Error posting NeetCode to {guild.name}: {e}")
                else:
                    logger.debug(f"Skipping {guild.name}: No #{LEETCODE_CHANNEL_NAME} channel found")

        except Exception as e:
            logger.error(f"Error in daily NeetCode task: {e}")

    @daily_task.before_loop
    async def before_daily_task(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=WEEKLY_RANKING_HOUR, minute=WEEKLY_RANKING_MINUTE, tzinfo=datetime.timezone.utc)])
    async def weekly_ranking_task(self):
        """Runs daily but only executes the ranking logic on Mondays."""
        now = datetime.datetime.now(datetime.timezone.utc)
        if now.weekday() != 0:  # 0 = Monday
            return
        if now.date() == datetime.date(2026, 4, 13):
            logger.info("⏭️ Skipping weekly ranking for Apr 13 (excluded date)")
            return
        logger.info("📊 Running weekly activity ranking")
        await self.post_weekly_rankings()

    @weekly_ranking_task.before_loop
    async def before_weekly_ranking_task(self):
        await self.bot.wait_until_ready()

    async def post_weekly_rankings(self, target_channel_id: int = None, dry_run: bool = False):
        """Build and post the weekly activity leaderboard, then kick the least active member."""
        now = datetime.datetime.now(datetime.timezone.utc)
        week_start = (now - datetime.timedelta(days=7)).strftime("%b %d")
        week_end = now.strftime("%b %d, %Y")

        for guild in self.bot.guilds:
            try:
                # Determine the target channel
                channel = None
                if target_channel_id:
                    channel = guild.get_channel(target_channel_id)
                else:
                    channel = discord.utils.get(guild.text_channels, name=ACTIVITY_CHANNEL_NAME)

                if not channel:
                    logger.debug(f"Skipping {guild.name}: No #{ACTIVITY_CHANNEL_NAME} channel found")
                    continue

                # Fetch message counts from DB
                db_counts = await get_weekly_message_counts(str(guild.id))
                count_map = {entry["author_id"]: entry["count"] for entry in db_counts}

                # Build ranked list of all non-bot members
                members = [m for m in guild.members if not m.bot]
                ranked = sorted(
                    members,
                    key=lambda m: (count_map.get(str(m.id), 0), -(m.joined_at.timestamp() if m.joined_at else 0)),
                    reverse=True,
                )

                top5 = ranked[:5]
                bottom5 = list(reversed(ranked[-5:])) if len(ranked) >= 5 else list(reversed(ranked))

                # Build embed
                embed = discord.Embed(
                    title=f"📊 Weekly Activity Report — {week_start}–{week_end}",
                    color=discord.Color.blurple(),
                )

                top_lines = []
                medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                for i, member in enumerate(top5):
                    msgs = count_map.get(str(member.id), 0)
                    label = "msg" if msgs == 1 else "msgs"
                    top_lines.append(f"{medals[i]} {member.mention} — **{msgs} {label}**")
                embed.add_field(name="🏆 Most Active", value="\n".join(top_lines) or "No data", inline=False)

                bottom_lines = []
                for member in bottom5:
                    msgs = count_map.get(str(member.id), 0)
                    label = "msg" if msgs == 1 else "msgs"
                    bottom_lines.append(f"• {member.mention} — **{msgs} {label}**")
                embed.add_field(name="💤 Least Active", value="\n".join(bottom_lines) or "No data", inline=False)

                await channel.send(embed=embed)

                # Check server-wide baseline before running the purge
                server_total = sum(count_map.values())
                if server_total < WEEKLY_MIN_SERVER_MESSAGES:
                    await channel.send(
                        f"📭 Server only had **{server_total} messages** this week "
                        f"(minimum {WEEKLY_MIN_SERVER_MESSAGES} required). No purge this week."
                    )
                    logger.info(f"Skipping purge for {guild.name}: server total {server_total} < {WEEKLY_MIN_SERVER_MESSAGES}")
                    continue

                # Find kick candidate: least active non-bot, non-owner, non-admin
                kick_candidates = [
                    m for m in reversed(ranked)
                    if not m.bot
                    and m != guild.owner
                    and not m.guild_permissions.administrator
                ]

                if kick_candidates:
                    victim = kick_candidates[0]
                    victim_msgs = count_map.get(str(victim.id), 0)

                    # Check member baseline — everyone pulled their weight
                    if victim_msgs >= WEEKLY_MIN_MEMBER_MESSAGES:
                        await channel.send(
                            f"✅ Everyone met the activity baseline this week "
                            f"(**{WEEKLY_MIN_MEMBER_MESSAGES}+ messages**). No purge. Keep it up!"
                        )
                        logger.info(f"Skipping purge for {guild.name}: least active member has {victim_msgs} msgs")
                        continue

                    label = "message" if victim_msgs == 1 else "messages"
                    if dry_run:
                        await channel.send(
                            f"👀 {victim.mention} you only sent **{victim_msgs} {label}** this week. "
                            f"You need to up your game — next time this is for real. 😤"
                        )
                        logger.info(f"[dry run] Would have kicked {victim} from {guild.name} ({victim_msgs} msgs)")
                    else:
                        await channel.send(
                            f"⚠️ {victim.mention} you sent only **{victim_msgs} {label}** this week. "
                            f"You are being **purged from the server in 1 hour**. "
                            f"This is your only warning. 🕐"
                        )
                        logger.info(f"⏳ Purge warning sent to {victim} in {guild.name}. Kick in 1 hour.")
                        await asyncio.sleep(3600)
                        try:
                            await guild.kick(victim, reason="Weekly inactivity purge")
                            await channel.send(f"🦵 {victim.mention} has been purged. See you never.")
                            logger.info(f"🦵 Kicked {victim} from {guild.name} for inactivity ({victim_msgs} msgs)")
                        except discord.Forbidden:
                            logger.warning(f"❌ Missing kick permission in {guild.name}")
                        except Exception as e:
                            logger.error(f"❌ Error kicking {victim} from {guild.name}: {e}")
                else:
                    logger.info(f"No eligible kick candidates in {guild.name}")

            except Exception as e:
                logger.error(f"Error in weekly ranking for {guild.name}: {e}")


    @tasks.loop(time=[datetime.time(hour=20, minute=45, tzinfo=datetime.timezone.utc)])
    async def book_club_reminder_task(self):
        """Tuesdays and Wednesdays at 8:45 PM UTC — book club first reminder."""
        if datetime.datetime.now(datetime.timezone.utc).weekday() not in (1, 2):  # 1=Tue, 2=Wed
            return
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=ED_CHANNEL_NAME)
            if channel:
                await channel.send(
                    "📚 Hey everyone! Our **Book Club meeting** starts in 15 minutes. "
                    "The link to join is in your emails — see you there! 🕘"
                )

    @book_club_reminder_task.before_loop
    async def before_book_club_reminder_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=21, minute=0, tzinfo=datetime.timezone.utc)])
    async def book_club_final_reminder_task(self):
        """Tuesdays and Wednesdays at 9:00 PM UTC — book club final reminder."""
        if datetime.datetime.now(datetime.timezone.utc).weekday() not in (1, 2):  # 1=Tue, 2=Wed
            return
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=ED_CHANNEL_NAME)
            if channel:
                await channel.send(
                    "📚 **Book Club is starting NOW!** Check your emails for the link and jump in. 🚀"
                )

    @book_club_final_reminder_task.before_loop
    async def before_book_club_final_reminder_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=8, minute=45, tzinfo=datetime.timezone.utc)])
    async def coworking_reminder_task(self):
        """Fridays at 8:45 AM UTC — coworking session reminder."""
        if datetime.datetime.now(datetime.timezone.utc).weekday() != 4:  # 4=Fri
            return
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=MD_CHANNEL_NAME)
            if channel:
                voice_channel = discord.utils.get(guild.voice_channels, name="co-work")
                vc_ref = voice_channel.mention if voice_channel else "**co-work**"
                await channel.send(
                    f"💻 Good morning! Our **Coworking Session** is starting soon. "
                    f"Pass through the {vc_ref} voice channel and let's get it. 🙌"
                )

    @coworking_reminder_task.before_loop
    async def before_coworking_reminder_task(self):
        await self.bot.wait_until_ready()


_scheduled_tasks_instance: "ScheduledTasks | None" = None


def setup_scheduled_tasks(bot):
    global _scheduled_tasks_instance
    if _scheduled_tasks_instance is not None:
        logger.info("Scheduled tasks already running — skipping re-initialization")
        return _scheduled_tasks_instance
    _scheduled_tasks_instance = ScheduledTasks(bot)
    return _scheduled_tasks_instance
