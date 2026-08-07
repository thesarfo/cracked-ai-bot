import datetime

import discord
from discord.ext import tasks

from config import (
    DSA_CODEFORCES_DAILY_TIME_HOUR,
    DSA_CODEFORCES_DAILY_TIME_MINUTE,
    DSA_LEETCODE_DAILY_TIME_HOUR,
    DSA_LEETCODE_DAILY_TIME_MINUTE,
    DSA_SUMMARY_TIME_HOUR,
    DSA_SUMMARY_TIME_MINUTE,
    ED_CHANNEL_NAME,
    LEETCODE_CHANNEL_NAME,
    LEETCODE_DAILY_TIME_HOUR,
    LEETCODE_DAILY_TIME_MINUTE,
    MD_CHANNEL_NAME,
)
from services.dsa_daily_service import get_dsa_daily_service
from services.leetcode_service import get_leetcode_service
from services.neetcode_service import get_neetcode_service
from utils.logging import get_logger

logger = get_logger("scheduler")


class ScheduledTasks:
    def __init__(self, bot):
        self.bot = bot
        self.leetcode_service = get_leetcode_service()
        self.neetcode_service = get_neetcode_service()
        self.dsa_daily_service = get_dsa_daily_service()

        # Calculate time for the loop
        self.daily_time = datetime.time(
            hour=LEETCODE_DAILY_TIME_HOUR,
            minute=LEETCODE_DAILY_TIME_MINUTE,
            tzinfo=datetime.timezone.utc
        )

        # Start loops
        self.daily_task.start()
        self.daily_dsa_leetcode_task.start()
        # self.daily_dsa_codeforces_task.start()  # disabled for now
        self.daily_dsa_summary_task.start()
        self.book_club_reminder_task.start()
        self.book_club_final_reminder_task.start()
        self.coworking_reminder_task.start()
        logger.info(f"📅 Daily scheduler initialized for {self.daily_time} UTC")

    def cog_unload(self):
        self.daily_task.cancel()
        self.daily_dsa_leetcode_task.cancel()
        # self.daily_dsa_codeforces_task.cancel()  # disabled for now
        self.daily_dsa_summary_task.cancel()
        self.book_club_reminder_task.cancel()
        self.book_club_final_reminder_task.cancel()
        self.coworking_reminder_task.cancel()

    @tasks.loop(time=[datetime.time(hour=LEETCODE_DAILY_TIME_HOUR, minute=LEETCODE_DAILY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_task(self):
        """Task that runs daily to post LeetCode daily."""
        logger.info("⏰ Running daily tasks")
        await self.post_daily_leetcode()

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

    @tasks.loop(time=[datetime.time(hour=DSA_LEETCODE_DAILY_TIME_HOUR, minute=DSA_LEETCODE_DAILY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_dsa_leetcode_task(self):
        """Task that runs daily to post one shuffled LeetCode problem."""
        logger.info("⏰ Running daily DSA LeetCode task")
        await self.post_daily_dsa_leetcode()

    async def post_daily_dsa_leetcode(self, target_channel_id: int = None):
        """Post one shuffled LeetCode problem."""
        try:
            lc_problem, lc_pos, lc_total = self.dsa_daily_service.get_next_leetcode()

            if not lc_problem:
                logger.error("Failed to get daily DSA LeetCode problem (no data loaded)")
                return

            for guild in self.bot.guilds:
                target_channel = None

                if target_channel_id:
                    target_channel = guild.get_channel(target_channel_id)
                else:
                    target_channel = discord.utils.get(guild.text_channels, name=LEETCODE_CHANNEL_NAME)

                if not target_channel:
                    logger.debug(f"Skipping {guild.name}: No #{LEETCODE_CHANNEL_NAME} channel found")
                    continue

                try:
                    embed = self.dsa_daily_service.create_leetcode_embed(lc_problem, lc_pos, lc_total)
                    message = await target_channel.send(embed=embed)
                    await message.create_thread(name=f"🧵 {lc_problem['title']}", auto_archive_duration=1440)

                    logger.info(f"✅ Posted daily DSA LeetCode problem to {guild.name} #{target_channel.name}")
                except discord.Forbidden:
                    logger.warning(f"❌ Missing permissions to post/thread to {guild.name} #{target_channel.name}")
                except Exception as e:
                    logger.error(f"❌ Error posting daily DSA LeetCode problem to {guild.name}: {e}")

        except Exception as e:
            logger.error(f"Error in daily DSA LeetCode task: {e}")

    @daily_dsa_leetcode_task.before_loop
    async def before_daily_dsa_leetcode_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=DSA_CODEFORCES_DAILY_TIME_HOUR, minute=DSA_CODEFORCES_DAILY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_dsa_codeforces_task(self):
        """Task that runs daily to post one shuffled Codeforces problem."""
        logger.info("⏰ Running daily DSA Codeforces task")
        await self.post_daily_dsa_codeforces()

    async def post_daily_dsa_codeforces(self, target_channel_id: int = None):
        """Post one shuffled Codeforces problem."""
        try:
            cf_problem, cf_pos, cf_total = self.dsa_daily_service.get_next_codeforces()

            if not cf_problem:
                logger.error("Failed to get daily DSA Codeforces problem (no data loaded)")
                return

            for guild in self.bot.guilds:
                target_channel = None

                if target_channel_id:
                    target_channel = guild.get_channel(target_channel_id)
                else:
                    target_channel = discord.utils.get(guild.text_channels, name=LEETCODE_CHANNEL_NAME)

                if not target_channel:
                    logger.debug(f"Skipping {guild.name}: No #{LEETCODE_CHANNEL_NAME} channel found")
                    continue

                try:
                    embed = self.dsa_daily_service.create_codeforces_embed(cf_problem, cf_pos, cf_total)
                    message = await target_channel.send(embed=embed)
                    await message.create_thread(name=f"🧵 {cf_problem['title']}", auto_archive_duration=1440)

                    logger.info(f"✅ Posted daily DSA Codeforces problem to {guild.name} #{target_channel.name}")
                except discord.Forbidden:
                    logger.warning(f"❌ Missing permissions to post/thread to {guild.name} #{target_channel.name}")
                except Exception as e:
                    logger.error(f"❌ Error posting daily DSA Codeforces problem to {guild.name}: {e}")

        except Exception as e:
            logger.error(f"Error in daily DSA Codeforces task: {e}")

    @daily_dsa_codeforces_task.before_loop
    async def before_daily_dsa_codeforces_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=DSA_SUMMARY_TIME_HOUR, minute=DSA_SUMMARY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_dsa_summary_task(self):
        """Task that runs daily to summarize who dropped a solution in today's DSA threads."""
        logger.info("⏰ Running daily DSA summary task")
        await self.post_daily_dsa_summary()

    async def post_daily_dsa_summary(self, target_channel_id: int = None) -> int:
        """Summarize today's DSA problem threads: who posted a solution (screenshot,
        code snippet, whatever) in each one. Returns how many guilds got a summary."""
        now = datetime.datetime.now(datetime.timezone.utc)
        today = now.date()
        posted = 0

        for guild in self.bot.guilds:
            target_channel = None

            if target_channel_id:
                target_channel = guild.get_channel(target_channel_id)
            else:
                target_channel = discord.utils.get(guild.text_channels, name=LEETCODE_CHANNEL_NAME)

            if not target_channel:
                logger.debug(f"Skipping {guild.name}: No #{LEETCODE_CHANNEL_NAME} channel found")
                continue

            try:
                active_threads = await guild.active_threads()
            except Exception as e:
                logger.warning(f"Could not fetch active threads for {guild.name}: {e}")
                continue

            todays_threads = [
                t for t in active_threads
                if t.parent_id == target_channel.id
                and t.name.startswith("🧵")
                and t.created_at is not None
                and t.created_at.astimezone(datetime.timezone.utc).date() == today
            ]

            if not todays_threads:
                logger.debug(f"No DSA threads today in {guild.name} #{target_channel.name}")
                continue

            try:
                lines = []
                all_participants = set()

                for thread in sorted(todays_threads, key=lambda t: t.created_at):
                    participants = set()
                    try:
                        async for msg in thread.history(limit=200):
                            if not msg.author.bot:
                                participants.add(msg.author)
                    except discord.Forbidden:
                        logger.debug(f"Missing history permission for thread {thread.name}")
                        continue

                    problem_name = thread.name.lstrip("🧵").strip()
                    all_participants |= participants

                    if participants:
                        mentions = ", ".join(m.mention for m in participants)
                        lines.append(f"✅ **{problem_name}** — {mentions}")
                    else:
                        lines.append(f"💤 **{problem_name}** — no one's dropped a solution yet")

                embed = discord.Embed(
                    title=f"📊 Daily DSA Wrap-Up — {now.strftime('%b %d, %Y')}",
                    description="\n".join(lines),
                    color=discord.Color.blurple(),
                )

                if all_participants:
                    count = len(all_participants)
                    label = "person" if count == 1 else "people"
                    embed.set_footer(text=f"{count} {label} put in work today. Nice. 🔥")
                else:
                    embed.set_footer(text="Nobody dropped a solution today — tomorrow's a new day 💪")

                await target_channel.send(embed=embed)
                posted += 1
                logger.info(f"✅ Posted DSA summary to {guild.name} #{target_channel.name}")
            except discord.Forbidden:
                logger.warning(f"❌ Missing permissions to post summary in {guild.name} #{target_channel.name}")
            except Exception as e:
                logger.error(f"❌ Error posting DSA summary to {guild.name}: {e}")

        return posted

    @daily_dsa_summary_task.before_loop
    async def before_daily_dsa_summary_task(self):
        await self.bot.wait_until_ready()

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
