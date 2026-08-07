import asyncio
import datetime
import difflib
import ipaddress
import json
import os
import random
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord
from agents import (
  Agent,
  AsyncOpenAI,
  GuardrailFunctionOutput,
  OpenAIChatCompletionsModel,
  RunContextWrapper,
  Runner,
  function_tool,
  set_tracing_disabled,
)
from agents.extensions.memory.async_sqlite_session import AsyncSQLiteSession

from config import (
  AGENT_MAX_INPUT_LENGTH,
  AGENT_SESSION_HISTORY_LIMIT,
  AGENT_SESSIONS_DB_PATH,
  DEEPSEEK_API_KEY,
  DEEPSEEK_BASE_URL,
  DEEPSEEK_MODEL,
  DSA_CODEFORCES_DAILY_TIME_HOUR,
  DSA_CODEFORCES_DAILY_TIME_MINUTE,
  DSA_LEETCODE_DAILY_TIME_HOUR,
  DSA_LEETCODE_DAILY_TIME_MINUTE,
  ED_CHANNEL_NAME,
  LEETCODE_CHANNEL_NAME,
  LEETCODE_DAILY_TIME_HOUR,
  LEETCODE_DAILY_TIME_MINUTE,
  MD_CHANNEL_NAME,
)
from utils.logging import get_logger

logger = get_logger("agent")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

INSTRUCTIONS = (
  "You are the AI assistant for \"the cracked\" Discord server - a community of "
  "developers, engineers, and friends, not a niche DSA-only space. People hang out, "
  "talk shop, and chat about whatever, same as any friend group's server. Among other "
  "things you help run, the server also does coding/DSA practice (daily LeetCode/"
  "Codeforces problems), a book club, and coworking sessions - but that's what the "
  "server *does*, not all it *is*. Treat this like hanging out with friends, not "
  "running a study bot. Keep responses SHORT and conversational - like texting a friend "
  "or co-worker. Don't lecture, don't give unsolicited advice, don't be preachy. Just "
  "answer what's asked, using casual language.\n\n"
  "Your message context always starts with a line telling you which channel and server "
  "you're currently in - you already know this, never ask the user which channel they "
  "mean unless they're clearly asking about a different one.\n\n"
  "You have tools available - only call one when you actually need it, not on every "
  "message. Pick the right one:\n"
  "- get_todays_leetcode_daily: LeetCode's own official Daily Challenge for today. Use "
  "for 'what's today's leetcode daily/question'.\n"
  "- get_dsa_rotation_status: the problem(s) THIS server's bot auto-posts on its own "
  "schedule (separate shuffled LeetCode + Codeforces rotation). Use for 'what DSA "
  "problem did the bot post today' or similar.\n"
  "- get_neetcode_status: where the NeetCode 150 rotation is up to.\n"
  "- search_dsa_problems: general problem recommendations by topic, difficulty vibe, or "
  "just 'give me something to solve' with no topic (it'll pick randomly). Use this for "
  "any 'give me a problem/question/challenge' ask that ISN'T about today's specific "
  "daily post - never invent a problem from memory, always call this.\n"
  "- get_server_schedule: when the server's recurring automated events happen (daily "
  "posts, book club, coworking).\n"
  "- get_channel_context: pull recent messages from a channel (defaults to the current "
  "channel if none is named) when you genuinely need more context to answer. Can also "
  "look back a specific number of hours (e.g. 'yesterday' ~= 24-48 hours) instead of "
  "just a message count.\n"
  "- find_member: look up a server member by name to get their exact @mention before "
  "tagging anyone. Never guess or hand-type a mention.\n"
  "- web_search: look up current or factual info you're not confident about from memory. "
  "Has narrow coverage (mainly well-known reference topics) - it will often come back "
  "empty, especially for anything specific, current, or numeric (stock prices, scores, "
  "weather). If it comes back empty, say so honestly instead of guessing or making "
  "something up.\n"
  "- fetch_url: open ONE SPECIFIC known URL (a link someone shared, or one web_search "
  "found) and read its actual text content. Use this to answer questions about a "
  "particular article/page - it's not a search tool, it needs an exact link."
)


@dataclass
class BotContext:
  guild: Optional[discord.Guild] = None
  channel: Optional[discord.abc.GuildChannel] = None


# --- Tool implementations (kept as plain functions, wrapped below, so the ---
# --- underlying logic can be unit tested without going through the LLM.  ---


async def _find_member_impl(wrapper: RunContextWrapper[BotContext], name: str) -> str:
  """Look up a server member by display name or username and return their exact
  @mention so you can correctly tag them. Always use this before mentioning someone
  by name instead of guessing their mention.

  Args:
    name: The name or partial name of the member to look up.
  """
  guild = wrapper.context.guild if wrapper.context else None
  if not guild:
    return "No server context available to look up members."

  name_lower = name.lower().lstrip("@")
  matches = [
    m for m in guild.members
    if name_lower in m.display_name.lower() or name_lower in m.name.lower()
  ]

  if not matches:
    return f"No member found matching '{name}'."
  if len(matches) == 1:
    m = matches[0]
    return f"{m.mention} (display name: {m.display_name}, username: {m.name})"

  lines = [f"- {m.mention} (display name: {m.display_name})" for m in matches[:5]]
  return "Multiple members matched, ask the user which one they mean:\n" + "\n".join(lines)


def _find_channel_fuzzy(guild: discord.Guild, name: str) -> Optional[discord.TextChannel]:
  """Resolve a channel name that might be typo'd, have extra letters (a nickname
  like 'wordleeeee'), or just be slightly off, to a real text channel."""
  name_lower = name.lower().strip().lstrip("#")
  if not name_lower:
    return None

  for ch in guild.text_channels:
    if ch.name.lower() == name_lower:
      return ch

  substring_matches = [
    ch for ch in guild.text_channels
    if name_lower in ch.name.lower() or ch.name.lower() in name_lower
  ]
  if len(substring_matches) == 1:
    return substring_matches[0]

  names_lower = [ch.name.lower() for ch in guild.text_channels]
  close = difflib.get_close_matches(name_lower, names_lower, n=1, cutoff=0.6)
  if close:
    return discord.utils.get(guild.text_channels, name=close[0])

  return None


async def _get_channel_context_impl(
  wrapper: RunContextWrapper[BotContext],
  channel_name: str = "",
  limit: int = 20,
  hours_back: int = 0,
) -> str:
  """Fetch recent messages from a text channel for extra conversational context.
  Only use this when you genuinely need actual chat history to answer the question.

  Args:
    channel_name: The channel name, with or without '#'. Leave empty to use the
      current channel this conversation is happening in.
    limit: How many recent messages to fetch (max 50). Ignored if hours_back is set.
    hours_back: If set, fetch all messages from the last N hours instead of a fixed
      count (max 336 = 14 days). Use this for asks like "yesterday" (~24-48) instead
      of guessing a message count.
  """
  guild = wrapper.context.guild if wrapper.context else None
  if not guild:
    return "No server context available."

  if channel_name.strip():
    channel = _find_channel_fuzzy(guild, channel_name)
    if not channel:
      return f"No channel found matching '{channel_name}' in this server."
  else:
    channel = wrapper.context.channel if wrapper.context else None
    if not channel:
      return "No current channel available, and no channel name was given."

  if not channel.permissions_for(guild.me).read_message_history:
    return f"I don't have permission to read #{channel.name}."

  lines = []
  if hours_back > 0:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
      hours=min(hours_back, 336)
    )
    async for msg in channel.history(after=cutoff, limit=200, oldest_first=True):
      if msg.author.bot:
        continue
      ts = msg.created_at.strftime("%m-%d %H:%M")
      lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
  else:
    limit = max(1, min(limit, 50))
    async for msg in channel.history(limit=limit):
      if msg.author.bot:
        continue
      ts = msg.created_at.strftime("%m-%d %H:%M")
      lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
    lines.reverse()

  return "\n".join(lines) if lines else f"No messages found in #{channel.name} for that range."


def _load_json(filename: str) -> list:
  try:
    with open(os.path.join(DATA_DIR, filename)) as f:
      return json.load(f)
  except Exception as e:
    logger.error(f"Failed to load {filename}: {e}")
    return []


_LEETCODE_PROBLEMS = _load_json("leetcode_problems.json")
_NEETCODE_PROBLEMS = _load_json("neetcode150.json")
_CODEFORCES_PROBLEMS = _load_json("codeforces_problems.json")


def _leetcode_link(p: dict) -> str:
  return f"https://leetcode.com/problems/{p.get('slug', '')}/"


def _neetcode_link(p: dict) -> str:
  return p.get("link", f"https://leetcode.com/problems/{p.get('titleSlug', '')}/")


def _codeforces_link(p: dict) -> str:
  return f"https://codeforces.com/problemset/problem/{p.get('contestId')}/{p.get('index', '')}"


async def _search_dsa_problems_impl(
  wrapper: RunContextWrapper[BotContext], query: str = "", source: str = "all", limit: int = 5
) -> str:
  """Search real LeetCode, NeetCode, and Codeforces problem sets by title or topic
  keyword, so you can recommend real problems with real links instead of making them
  up. Leave query empty for a random pick when the user has no specific topic in mind
  (e.g. "give me a problem to solve").

  Args:
    query: A title keyword or topic to search for (e.g. "two pointers", "binary
      search"). Leave empty for a random problem.
    source: Which set to search: "leetcode", "neetcode", "codeforces", or "all".
    limit: Max number of results to return (max 10).
  """
  query_lower = query.lower().strip()
  limit = max(1, min(limit, 10))

  pools = []
  if source in ("all", "leetcode"):
    pools.append(("LeetCode", _LEETCODE_PROBLEMS, _leetcode_link))
  if source in ("all", "neetcode"):
    pools.append(("NeetCode", _NEETCODE_PROBLEMS, _neetcode_link))
  if source in ("all", "codeforces"):
    pools.append(("Codeforces", _CODEFORCES_PROBLEMS, _codeforces_link))

  if not query_lower:
    all_problems = [(label, p, link_fn) for label, pool, link_fn in pools for p in pool]
    if not all_problems:
      return "No problems available."
    picks = random.sample(all_problems, min(limit, len(all_problems)))
    return "\n".join(
      f"[{label}] {p.get('title')} ({p.get('difficulty', '?')}) — {link_fn(p)}"
      for label, p, link_fn in picks
    )

  results = []
  for label, pool, link_fn in pools:
    for p in pool:
      title = str(p.get("title", "")).lower()
      topics = str(p.get("topics") or p.get("category") or "").lower()
      if query_lower in title or query_lower in topics:
        results.append(f"[{label}] {p.get('title')} ({p.get('difficulty', '?')}) — {link_fn(p)}")
      if len(results) >= limit:
        break
    if len(results) >= limit:
      break

  return "\n".join(results) if results else f"No problems found matching '{query}'."


async def _get_todays_leetcode_daily_impl(wrapper: RunContextWrapper[BotContext]) -> str:
  """Get LeetCode's own official Daily Challenge question for today - title,
  difficulty, and a real link. This is the question LeetCode itself designates as
  today's daily, separate from anything this bot posts on its own schedule."""
  from services.leetcode_service import get_leetcode_service

  question = await get_leetcode_service().fetch_daily_question()
  if not question:
    return "Couldn't fetch today's LeetCode daily question right now."

  q = question.get("question", {})
  title = q.get("title", "Unknown")
  difficulty = q.get("difficulty", "Unknown")
  link = f"https://leetcode.com{question.get('link', '')}"
  return f"{title} ({difficulty}) — {link}"


async def _get_dsa_rotation_status_impl(wrapper: RunContextWrapper[BotContext]) -> str:
  """Get the problem(s) THIS server's bot auto-posts from its own shuffled daily
  LeetCode + Codeforces rotation (separate from LeetCode's official daily challenge).
  Read-only - does not affect what gets posted next."""
  from services.dsa_daily_service import get_dsa_daily_service

  service = get_dsa_daily_service()
  lc, lc_pos, lc_total = service.peek_leetcode()
  cf, cf_pos, cf_total = service.peek_codeforces()

  lines = []
  if lc:
    lines.append(
      f"LeetCode [{lc_pos}/{lc_total}]: {lc.get('title')} ({lc.get('difficulty')}) — "
      f"{_leetcode_link(lc)}"
    )
  if cf:
    lines.append(
      f"Codeforces [{cf_pos}/{cf_total}]: {cf.get('title')} "
      f"({cf.get('difficulty')}, rating {cf.get('rating')}) — {_codeforces_link(cf)}"
    )
  return "\n".join(lines) if lines else "No DSA rotation data available."


async def _get_neetcode_status_impl(wrapper: RunContextWrapper[BotContext]) -> str:
  """Get where the NeetCode 150 rotation is up to - the next problem and overall
  progress. Read-only - does not affect what gets posted next."""
  from services.neetcode_service import get_neetcode_service

  problem, pos, total = get_neetcode_service().peek_next_problem()
  if not problem:
    return "NeetCode 150 data not loaded."

  link = _neetcode_link(problem)
  return (
    f"[{pos}/{total}] {problem.get('title')} ({problem.get('difficulty')}) — "
    f"{problem.get('category')} — {link}"
  )


_SERVER_SCHEDULE_TEXT = (
  "Recurring automated events (all times UTC):\n"
  f"- LeetCode Daily Challenge posted in #{LEETCODE_CHANNEL_NAME} at "
  f"{LEETCODE_DAILY_TIME_HOUR:02d}:{LEETCODE_DAILY_TIME_MINUTE:02d}\n"
  f"- Shuffled LeetCode problem posted in #{LEETCODE_CHANNEL_NAME} at "
  f"{DSA_LEETCODE_DAILY_TIME_HOUR:02d}:{DSA_LEETCODE_DAILY_TIME_MINUTE:02d}\n"
  f"- Shuffled Codeforces problem: normally {DSA_CODEFORCES_DAILY_TIME_HOUR:02d}:"
  f"{DSA_CODEFORCES_DAILY_TIME_MINUTE:02d} in #{LEETCODE_CHANNEL_NAME}, but auto-posting "
  "is currently paused - an admin can trigger it manually with /force_dsa_codeforces\n"
  f"- Book club reminders in #{ED_CHANNEL_NAME}: Tuesdays & Wednesdays at 20:45 (15 min "
  "warning) and 21:00 (starting now)\n"
  f"- Coworking session reminder in #{MD_CHANNEL_NAME}: Fridays at 08:45"
)


async def _get_server_schedule_impl(wrapper: RunContextWrapper[BotContext]) -> str:
  """Get the server's recurring automated schedule - when daily DSA problems, book
  club, and coworking sessions happen. Use this whenever asked when something
  recurring happens, instead of guessing."""
  return _SERVER_SCHEDULE_TEXT


_http_session: Optional[aiohttp.ClientSession] = None


async def _get_http_session() -> aiohttp.ClientSession:
  global _http_session
  if _http_session is None or _http_session.closed:
    _http_session = aiohttp.ClientSession()
  return _http_session


async def _web_search_impl(wrapper: RunContextWrapper[BotContext], query: str) -> str:
  """Look up current or factual information (definitions, well-known facts, companies,
  technologies) that you're not confident about from memory. Not a full search engine -
  best for reference-style questions, not real-time data like scores or weather.

  Args:
    query: The search query.
  """
  try:
    session = await _get_http_session()
    async with session.get(
      "https://api.duckduckgo.com/",
      params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
      headers={"User-Agent": "Mozilla/5.0 (compatible; CrackedBot/1.0)"},
    ) as response:
      if response.status >= 400:
        return f"Web search failed with status {response.status}."
      data = await response.json(content_type=None)
  except Exception as e:
    logger.error(f"Web search error: {e}")
    return f"Web search failed: {e}"

  abstract = data.get("AbstractText") or data.get("Abstract")
  if abstract:
    source = data.get("AbstractURL", "")
    return abstract + (f"\nSource: {source}" if source else "")

  lines = []
  for item in data.get("RelatedTopics") or []:
    text = item.get("Text")
    if not text:
      continue
    url = item.get("FirstURL")
    lines.append(f"- {text}" + (f" ({url})" if url else ""))
    if len(lines) >= 5:
      break

  return "\n".join(lines) if lines else f"No web results found for '{query}'."


class _ArticleTextExtractor(HTMLParser):
  """Minimal stdlib HTML-to-text extractor: strips script/style/nav/etc. and
  keeps visible text content, for reading a fetched page without a heavier
  HTML-parsing dependency."""

  _SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "form"}

  def __init__(self):
    super().__init__()
    self._skip_depth = 0
    self.chunks: list[str] = []

  def handle_starttag(self, tag, attrs):
    if tag in self._SKIP_TAGS:
      self._skip_depth += 1

  def handle_endtag(self, tag):
    if tag in self._SKIP_TAGS and self._skip_depth > 0:
      self._skip_depth -= 1

  def handle_data(self, data):
    if self._skip_depth == 0:
      text = data.strip()
      if text:
        self.chunks.append(text)


def _extract_readable_text(html: str, max_chars: int = 3000) -> str:
  parser = _ArticleTextExtractor()
  try:
    parser.feed(html)
  except Exception:
    pass
  text = re.sub(r"\s+", " ", " ".join(parser.chunks)).strip()
  return text[:max_chars]


async def _hostname_is_safe(hostname: str) -> bool:
  """Reject hostnames that resolve to private/internal/loopback addresses, so
  fetch_url can't be used to reach internal services (e.g. a cloud metadata
  endpoint) via a chat-facing tool."""
  try:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(hostname, None)
  except (socket.gaierror, OSError):
    return False

  if not infos:
    return False

  for info in infos:
    try:
      ip = ipaddress.ip_address(info[4][0])
    except ValueError:
      return False
    if (
      ip.is_private
      or ip.is_loopback
      or ip.is_link_local
      or ip.is_reserved
      or ip.is_multicast
      or ip.is_unspecified
    ):
      return False

  return True


MAX_FETCH_BYTES = 2_000_000  # 2MB cap - don't download huge files


async def _fetch_url_impl(wrapper: RunContextWrapper[BotContext], url: str) -> str:
  """Open a specific URL and return its readable text content, so you can actually
  answer questions about an article or page someone shared or you found a link to.
  This is for reading ONE KNOWN link, not searching - use web_search or
  search_dsa_problems to find things first if you don't already have a URL. Only
  works on public web pages.

  Args:
    url: The full URL to fetch, must start with http:// or https://.
  """
  parsed = urlparse(url.strip())
  if parsed.scheme not in ("http", "https") or not parsed.hostname:
    return "That doesn't look like a valid http(s) URL."

  if not await _hostname_is_safe(parsed.hostname):
    return "Can't fetch that URL (blocked or unresolvable host)."

  try:
    session = await _get_http_session()
    async with session.get(
      url,
      headers={"User-Agent": "Mozilla/5.0 (compatible; CrackedBot/1.0)"},
      timeout=aiohttp.ClientTimeout(total=10),
      allow_redirects=False,  # avoid redirect-based bypass of the hostname check above
    ) as response:
      if 300 <= response.status < 400:
        return "That URL redirects elsewhere - try fetching the final destination URL directly."
      if response.status >= 400:
        return f"Fetching that page failed with status {response.status}."

      content_type = response.headers.get("Content-Type", "")
      if "html" not in content_type and "text" not in content_type:
        return f"That URL isn't a readable page (content-type: {content_type or 'unknown'})."

      declared_length = response.headers.get("Content-Length")
      if declared_length and int(declared_length) > MAX_FETCH_BYTES:
        return "That page is too large to fetch."

      raw = await response.read()
      html = raw[:MAX_FETCH_BYTES].decode(response.get_encoding() or "utf-8", errors="replace")
  except asyncio.TimeoutError:
    return "Fetching that page timed out."
  except Exception as e:
    logger.error(f"fetch_url error for {url}: {e}")
    return f"Couldn't fetch that page: {e}"

  text = _extract_readable_text(html)
  return text if text else "Fetched the page, but couldn't find any readable text on it."


# --- Input guardrail: cheap, no-extra-API-call first line of defense against ---
# --- prompt injection / jailbreak attempts and cost-abuse via giant prompts. ---
#
# NOT currently attached to the agent (see AgentService.__init__) - it produced
# false positives in practice. Root cause: with session memory active, the model
# `input` passed to a guardrail is the FULL accumulated conversation (history +
# new message), not just the new message. The original version stringified that
# whole list, so one flagged message anywhere in a session's history would keep
# tripping the guardrail on every future turn - and a *tripped* turn's input still
# gets persisted to the session, so a single false positive could permanently wall
# off a user in that channel. Fixed below to only inspect the latest user message,
# but leaving it disabled until it's been exercised more before turning back on.

_INJECTION_PATTERNS = [
  re.compile(r"ignore (all|any|previous|prior)\s+(instructions|rules)", re.I),
  re.compile(r"disregard (your|all|any)\s+(instructions|rules|guidelines)", re.I),
  re.compile(r"reveal (your|the)\s+(system|hidden)\s+prompt", re.I),
  re.compile(r"(what|show me)\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions)", re.I),
  re.compile(r"you are now\s+(dan|jailbroken|unrestricted|unfiltered)", re.I),
  re.compile(r"pretend\s+(you have|to have)\s+no\s+(rules|restrictions|filters|guidelines)", re.I),
  re.compile(r"act as if\s+you have no\s+(rules|restrictions|filters|guidelines)", re.I),
]


def _extract_latest_user_text(agent_input: "str | list") -> str:
  """Pull out just the newest user message's text, even when `agent_input` is the
  full session-expanded item list, so guardrails only ever judge the new message."""
  if isinstance(agent_input, str):
    return agent_input
  if isinstance(agent_input, list) and agent_input:
    last = agent_input[-1]
    if isinstance(last, dict):
      content = last.get("content")
      if isinstance(content, str):
        return content
      if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return " ".join(p for p in parts if p)
  return str(agent_input)


async def _prompt_safety_guardrail(
  wrapper: RunContextWrapper[BotContext], agent: Agent, agent_input: "str | list"
) -> GuardrailFunctionOutput:
  text = _extract_latest_user_text(agent_input)

  if len(text) > AGENT_MAX_INPUT_LENGTH:
    return GuardrailFunctionOutput(
      output_info={"reason": "input_too_long", "length": len(text)},
      tripwire_triggered=True,
    )

  for pattern in _INJECTION_PATTERNS:
    if pattern.search(text):
      return GuardrailFunctionOutput(
        output_info={"reason": "possible_prompt_injection", "pattern": pattern.pattern},
        tripwire_triggered=True,
      )

  return GuardrailFunctionOutput(output_info={"reason": "ok"}, tripwire_triggered=False)


find_member = function_tool(
  _find_member_impl,
  name_override="find_member",
  description_override=_find_member_impl.__doc__.strip().split("\n\n")[0],
)
get_channel_context = function_tool(
  _get_channel_context_impl,
  name_override="get_channel_context",
  description_override=_get_channel_context_impl.__doc__.strip().split("\n\n")[0],
)
search_dsa_problems = function_tool(
  _search_dsa_problems_impl,
  name_override="search_dsa_problems",
  description_override=_search_dsa_problems_impl.__doc__.strip().split("\n\n")[0],
)
get_todays_leetcode_daily = function_tool(
  _get_todays_leetcode_daily_impl,
  name_override="get_todays_leetcode_daily",
  description_override=_get_todays_leetcode_daily_impl.__doc__.strip(),
)
get_dsa_rotation_status = function_tool(
  _get_dsa_rotation_status_impl,
  name_override="get_dsa_rotation_status",
  description_override=_get_dsa_rotation_status_impl.__doc__.strip(),
)
get_neetcode_status = function_tool(
  _get_neetcode_status_impl,
  name_override="get_neetcode_status",
  description_override=_get_neetcode_status_impl.__doc__.strip(),
)
get_server_schedule = function_tool(
  _get_server_schedule_impl,
  name_override="get_server_schedule",
  description_override=_get_server_schedule_impl.__doc__.strip(),
)
web_search = function_tool(
  _web_search_impl,
  name_override="web_search",
  description_override=_web_search_impl.__doc__.strip().split("\n\n")[0],
)
fetch_url = function_tool(
  _fetch_url_impl,
  name_override="fetch_url",
  description_override=_fetch_url_impl.__doc__.strip().split("\n\n")[0],
)


class AgentService:
  """Runs the bot's conversational AI as an OpenAI Agents SDK agent, pointed at
  DeepSeek's OpenAI-compatible Chat Completions API."""

  def __init__(self):
    self.enabled = bool(DEEPSEEK_API_KEY)
    self.provider_name = "DeepSeek"
    self.agent: Optional[Agent] = None

    if self.enabled:
      # We're not using OpenAI's own backend, so disable trace export (it
      # otherwise tries to upload run traces to platform.openai.com).
      set_tracing_disabled(True)

      client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
      model = OpenAIChatCompletionsModel(model=DEEPSEEK_MODEL, openai_client=client)

      self.agent = Agent(
        name="Cracked Bot",
        instructions=INSTRUCTIONS,
        model=model,
        tools=[
          find_member,
          get_channel_context,
          search_dsa_problems,
          get_todays_leetcode_daily,
          get_dsa_rotation_status,
          get_neetcode_status,
          get_server_schedule,
          web_search,
          fetch_url,
        ],
        # input_guardrails intentionally left off for now - see the comment above
        # _INJECTION_PATTERNS.
      )

    logger.info(
      f"🤖 Agent service {'enabled (DeepSeek)' if self.enabled else 'disabled — no DEEPSEEK_API_KEY set'}"
    )

  @staticmethod
  def _session_id(channel_id: int, user_id: int) -> str:
    return f"{channel_id}:{user_id}"

  def _build_session(self, channel_id: int, user_id: int) -> AsyncSQLiteSession:
    return AsyncSQLiteSession(
      session_id=self._session_id(channel_id, user_id),
      db_path=AGENT_SESSIONS_DB_PATH,
      session_settings={"limit": AGENT_SESSION_HISTORY_LIMIT},
    )

  async def run(
    self,
    prompt: str,
    guild: Optional[discord.Guild] = None,
    channel: Optional[discord.abc.GuildChannel] = None,
    user_id: Optional[int] = None,
    context: str = "",
  ) -> str:
    """Run the agent. When channel and user_id are both given, the conversation is
    remembered across calls for that (channel, user) pair - each following turn sees
    prior turns automatically, no manual history stitching needed. The current
    channel/server is also always told to the model, so it never has to ask."""
    if not self.enabled or not self.agent:
      return "Error: AI is not configured — missing DEEPSEEK_API_KEY."
    if not prompt:
      return "You need a prompt to be able to interact with the AI."

    location_line = ""
    if channel is not None:
      channel_name = getattr(channel, "name", None)
      guild_name = guild.name if guild else None
      if channel_name and guild_name:
        location_line = f"[You are currently in #{channel_name} on the '{guild_name}' server.]"
      elif channel_name:
        location_line = f"[You are currently in #{channel_name}.]"

    context_parts = [p for p in (location_line, context) if p]
    full_prompt = "\n\n".join(context_parts + [prompt]) if context_parts else prompt

    logger.info(f"🤖 Agent request: {prompt[:80]}...")

    channel_id = channel.id if channel is not None else None
    session = self._build_session(channel_id, user_id) if channel_id and user_id else None

    try:
      result = await Runner.run(
        self.agent,
        full_prompt,
        context=BotContext(guild=guild, channel=channel),
        session=session,
      )
      output = str(result.final_output) if result.final_output else "No response from the agent."
      logger.info(f"🤖 Agent response: {output[:80]}...")
      return output
    except Exception as e:
      logger.error(f"Agent error: {e}")
      return f"Error calling DeepSeek agent: {e}"
    finally:
      if session is not None:
        await session.close()


_agent_service: Optional[AgentService] = None


def get_agent_service() -> AgentService:
  global _agent_service
  if _agent_service is None:
    _agent_service = AgentService()
  return _agent_service
