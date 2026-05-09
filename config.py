import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3-flash-preview"

DB_PATH = "data/messages.db"

# LeetCode Configuration
LEETCODE_API_URL = "https://leetcode.com/graphql"
LEETCODE_CHANNEL_NAME = "dsa"
# 5:00 AM UTC daily
LEETCODE_DAILY_TIME_HOUR = 5
LEETCODE_DAILY_TIME_MINUTE = 0

ED_CHANNEL_NAME = "ed"
MD_CHANNEL_NAME = "md"
WORDLE_CHANNEL_NAME = "wordle"
WELCOME_CHANNEL_NAME = "welcome"

# Activity Ranking Configuration
ACTIVITY_CHANNEL_NAME = "chat"
# 5:00 AM UTC every Monday
WEEKLY_RANKING_HOUR = 5
WEEKLY_RANKING_MINUTE = 0
WEEKLY_MIN_MEMBER_MESSAGES = 7
WEEKLY_MIN_SERVER_MESSAGES = 50
