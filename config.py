import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3-flash-preview"

# When DEEPSEEK_API_KEY is set, it takes priority over Gemini for AI responses.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

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

# Daily DSA Problem Configuration (shuffled LeetCode + Codeforces rotation)
# 10:00 AM UTC daily
DSA_LEETCODE_DAILY_TIME_HOUR = 10
DSA_LEETCODE_DAILY_TIME_MINUTE = 0
# 3:00 PM UTC daily
DSA_CODEFORCES_DAILY_TIME_HOUR = 15
DSA_CODEFORCES_DAILY_TIME_MINUTE = 0

# Activity Ranking Configuration
ACTIVITY_CHANNEL_NAME = "chat"
# 5:00 AM UTC every Monday
WEEKLY_RANKING_HOUR = 5
WEEKLY_RANKING_MINUTE = 0
WEEKLY_MIN_MEMBER_MESSAGES = 7
WEEKLY_MIN_SERVER_MESSAGES = 50
