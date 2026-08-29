import datetime
import json
import os

import discord
from discord.ext import tasks

from config import (
    CSES_DAILY_TIME_HOUR,
    CSES_DAILY_TIME_MINUTE,
    DSA_SUMMARY_TIME_HOUR,
    DSA_SUMMARY_TIME_MINUTE,
    ED_CHANNEL_NAME,
    LEETCODE_CHANNEL_NAME,
    LEETCODE_DAILY_TIME_HOUR,
    LEETCODE_DAILY_TIME_MINUTE,
    MD_CHANNEL_NAME,
    PROJECT_EULER_DAILY_TIME_HOUR,
    PROJECT_EULER_DAILY_TIME_MINUTE,
)
from services.cses_service import get_cses_service
from services.leetcode_service import get_leetcode_service
from services.project_euler_service import get_project_euler_service
from utils.logging import get_logger

logger = get_logger("scheduler")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DSA_THREAD_IDS_PATH = os.path.join(DATA_DIR, "dsa_thread_ids.json")


class ScheduledTasks:
    def __init__(self, bot):
        self.bot = bot
        self.leetcode_service = get_leetcode_service()
        self.cses_service = get_cses_service()
        self.project_euler_service = get_project_euler_service()

        # Thread IDs created by the LeetCode daily / CSES posts, scheduled or
        # manually forced. The 10pm summary only reports on these, not on every
        # 🧵 thread in the channel. Persisted to disk so a restart between the
        # 10am/3pm posts and the 10pm summary doesn't lose track of them.
        self.dsa_thread_ids: dict[int, datetime.date] = self._load_dsa_thread_ids()

        # Start loops
        self.daily_task.start()
        self.daily_cses_task.start()
        self.daily_euler_task.start()
        self.daily_dsa_summary_task.start()
        self.book_club_reminder_task.start()
        self.book_club_final_reminder_task.start()
        self.coworking_reminder_task.start()
        logger.info(
            f"📅 Daily scheduler initialized — LeetCode {LEETCODE_DAILY_TIME_HOUR:02d}:{LEETCODE_DAILY_TIME_MINUTE:02d} UTC, "
            f"CSES {CSES_DAILY_TIME_HOUR:02d}:{CSES_DAILY_TIME_MINUTE:02d} UTC, "
            f"Project Euler {PROJECT_EULER_DAILY_TIME_HOUR:02d}:{PROJECT_EULER_DAILY_TIME_MINUTE:02d} UTC, "
            f"summary {DSA_SUMMARY_TIME_HOUR:02d}:{DSA_SUMMARY_TIME_MINUTE:02d} UTC"
        )

    def _load_dsa_thread_ids(self) -> dict:
        try:
            with open(DSA_THREAD_IDS_PATH, "r") as f:
                raw = json.load(f)
            return {int(tid): datetime.date.fromisoformat(d) for tid, d in raw.items()}
        except Exception:
            return {}

    def _save_dsa_thread_ids(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(DSA_THREAD_IDS_PATH, "w") as f:
                json.dump({str(tid): d.isoformat() for tid, d in self.dsa_thread_ids.items()}, f)
        except Exception as e:
            logger.warning(f"Could not persist DSA thread IDs: {e}")

    def register_dsa_thread(self, thread_id: int):
        """Mark a thread as a LeetCode daily / CSES post so the nightly summary picks it up."""
        now = datetime.datetime.now(datetime.timezone.utc)
        self.dsa_thread_ids[thread_id] = now.date()
        # Keep this from growing forever — nothing older than yesterday is ever needed.
        cutoff = now.date() - datetime.timedelta(days=1)
        self.dsa_thread_ids = {tid: d for tid, d in self.dsa_thread_ids.items() if d >= cutoff}
        self._save_dsa_thread_ids()

    def cog_unload(self):
        self.daily_task.cancel()
        self.daily_cses_task.cancel()
        self.daily_euler_task.cancel()
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
                        thread = await message.create_thread(name=thread_name, auto_archive_duration=1440)
                        self.register_dsa_thread(thread.id)

                        logger.info(f"✅ Posted LeetCode daily to {guild.name} #{target_channel.name}")
                    except discord.Forbidden:
                        logger.warning(f"❌ Missing permissions to post/thread to {guild.name} #{target_channel.name}")
                    except Exception as e:
                        logger.error(f"❌ Error posting to {guild.name}: {e}")
                else:
                    logger.debug(f"Skipping {guild.name}: No #{LEETCODE_CHANNEL_NAME} channel found")

        except Exception as e:
            logger.error(f"Error in daily LeetCode task: {e}")

    @daily_task.before_loop
    async def before_daily_task(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=CSES_DAILY_TIME_HOUR, minute=CSES_DAILY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_cses_task(self):
        """Task that runs daily to post the next CSES problem, in topic order."""
        logger.info("⏰ Running daily CSES task")
        await self.post_daily_cses()

    async def post_daily_cses(self, target_channel_id: int = None):
        """Post the next CSES problem, in official topic order."""
        try:
            problem, position, total = self.cses_service.get_next_problem()

            if not problem:
                logger.error("Failed to get daily CSES problem (no data loaded)")
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
                    embed = self.cses_service.create_cses_embed(problem, position, total)
                    message = await target_channel.send(embed=embed)
                    thread = await message.create_thread(name=f"🧵 {problem['title']}", auto_archive_duration=1440)
                    self.register_dsa_thread(thread.id)

                    logger.info(f"✅ Posted daily CSES problem to {guild.name} #{target_channel.name}")
                except discord.Forbidden:
                    logger.warning(f"❌ Missing permissions to post/thread to {guild.name} #{target_channel.name}")
                except Exception as e:
                    logger.error(f"❌ Error posting daily CSES problem to {guild.name}: {e}")

        except Exception as e:
            logger.error(f"Error in daily CSES task: {e}")

    @daily_cses_task.before_loop
    async def before_daily_cses_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=PROJECT_EULER_DAILY_TIME_HOUR, minute=PROJECT_EULER_DAILY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_euler_task(self):
        """Task that runs daily to post the next Project Euler problem, in numeric order."""
        logger.info("⏰ Running daily Project Euler task")
        await self.post_daily_project_euler()

    async def post_daily_project_euler(self, target_channel_id: int = None):
        """Post the next Project Euler problem, in numeric order."""
        try:
            problem, position, total = self.project_euler_service.get_next_problem()

            if not problem:
                logger.error("Failed to get daily Project Euler problem (no data loaded)")
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
                    embed = self.project_euler_service.create_euler_embed(problem, position, total)
                    message = await target_channel.send(embed=embed)
                    thread_name = f"🧵 Problem {problem['number']}: {problem['title']}"
                    thread = await message.create_thread(name=thread_name, auto_archive_duration=1440)
                    self.register_dsa_thread(thread.id)

                    logger.info(f"✅ Posted daily Project Euler problem to {guild.name} #{target_channel.name}")
                except discord.Forbidden:
                    logger.warning(f"❌ Missing permissions to post/thread to {guild.name} #{target_channel.name}")
                except Exception as e:
                    logger.error(f"❌ Error posting daily Project Euler problem to {guild.name}: {e}")

        except Exception as e:
            logger.error(f"Error in daily Project Euler task: {e}")

    @daily_euler_task.before_loop
    async def before_daily_euler_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[datetime.time(hour=DSA_SUMMARY_TIME_HOUR, minute=DSA_SUMMARY_TIME_MINUTE, tzinfo=datetime.timezone.utc)])
    async def daily_dsa_summary_task(self):
        """Task that runs daily to summarize who dropped a solution in today's problem threads."""
        logger.info("⏰ Running daily DSA summary task")
        await self.post_daily_dsa_summary()

    async def post_daily_dsa_summary(self, target_channel_id: int = None) -> int:
        """Summarize today's problem threads: who posted a solution (screenshot,
        code snippet, whatever) in each one. Only counts threads registered by the
        LeetCode daily / CSES posts (scheduled or manually forced), not every 🧵
        thread in the channel. Returns how many guilds got a summary."""
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
                and t.id in self.dsa_thread_ids
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


def get_scheduled_tasks() -> "ScheduledTasks | None":
    return _scheduled_tasks_instance
