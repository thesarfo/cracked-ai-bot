import datetime

import discord
from discord.ext import tasks

from config import (
    ACTIVITY_CHANNEL_NAME,
    LEETCODE_CHANNEL_NAME,
    LEETCODE_DAILY_TIME_HOUR,
    LEETCODE_DAILY_TIME_MINUTE,
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
        logger.info(f"📅 Daily scheduler initialized for {self.daily_time} UTC")

    def cog_unload(self):
        self.daily_task.cancel()
        self.weekly_ranking_task.cancel()

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
        if datetime.datetime.now(datetime.timezone.utc).weekday() != 0:  # 0 = Monday
            return
        logger.info("📊 Running weekly activity ranking")
        await self.post_weekly_rankings()

    @weekly_ranking_task.before_loop
    async def before_weekly_ranking_task(self):
        await self.bot.wait_until_ready()

    async def post_weekly_rankings(self, target_channel_id: int = None):
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
                    top_lines.append(f"{medals[i]} {member.display_name} — **{msgs} {label}**")
                embed.add_field(name="🏆 Most Active", value="\n".join(top_lines) or "No data", inline=False)

                bottom_lines = []
                for member in bottom5:
                    msgs = count_map.get(str(member.id), 0)
                    label = "msg" if msgs == 1 else "msgs"
                    bottom_lines.append(f"• {member.display_name} — **{msgs} {label}**")
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
                    await channel.send(
                        f"⚠️ {victim.mention} sent only **{victim_msgs} {label}** this week "
                        f"and is being purged from the server. Goodbye! 👋"
                    )
                    try:
                        await guild.kick(victim, reason="Weekly inactivity purge")
                        logger.info(f"🦵 Kicked {victim} from {guild.name} for inactivity ({victim_msgs} msgs)")
                    except discord.Forbidden:
                        logger.warning(f"❌ Missing kick permission in {guild.name}")
                    except Exception as e:
                        logger.error(f"❌ Error kicking {victim} from {guild.name}: {e}")
                else:
                    logger.info(f"No eligible kick candidates in {guild.name}")

            except Exception as e:
                logger.error(f"Error in weekly ranking for {guild.name}: {e}")


_scheduled_tasks_instance: "ScheduledTasks | None" = None


def setup_scheduled_tasks(bot):
    global _scheduled_tasks_instance
    _scheduled_tasks_instance = ScheduledTasks(bot)
    return _scheduled_tasks_instance
