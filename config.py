import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# AI is powered by DeepSeek via the OpenAI Agents SDK (DeepSeek exposes an
# OpenAI-compatible Chat Completions API at DEEPSEEK_BASE_URL).
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

DB_PATH = "data/messages.db"
AGENT_SESSIONS_DB_PATH = "data/agent_sessions.db"
# Max turns of conversation history the agent keeps per (channel, user) session.
AGENT_SESSION_HISTORY_LIMIT = 20
# Hard cap on a single prompt's length, to bound cost/abuse.
AGENT_MAX_INPUT_LENGTH = 4000

# LeetCode Configuration
LEETCODE_API_URL = "https://leetcode.com/graphql"
LEETCODE_CHANNEL_NAME = "dsa"
# 5:00 AM UTC daily
LEETCODE_DAILY_TIME_HOUR = 5
LEETCODE_DAILY_TIME_MINUTE = 0

ED_CHANNEL_NAME = "ed"
MD_CHANNEL_NAME = "md"
WELCOME_CHANNEL_NAME = "welcome"

# Daily DSA Problem Configuration (shuffled LeetCode + Codeforces rotation)
# 10:00 AM UTC daily
DSA_LEETCODE_DAILY_TIME_HOUR = 10
DSA_LEETCODE_DAILY_TIME_MINUTE = 0
# 3:00 PM UTC daily
DSA_CODEFORCES_DAILY_TIME_HOUR = 15
DSA_CODEFORCES_DAILY_TIME_MINUTE = 0
