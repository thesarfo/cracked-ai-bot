import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import aiohttp
import discord
from agents import (
  Agent,
  AsyncOpenAI,
  GuardrailFunctionOutput,
  InputGuardrail,
  InputGuardrailTripwireTriggered,
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
)
from utils.logging import get_logger

logger = get_logger("agent")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

INSTRUCTIONS = (
  "You are a helpful, casual AI bot in a Discord server for people grinding DSA/coding "
  "practice. Keep responses SHORT and conversational - like texting a friend or co-worker. "
  "Don't lecture, don't give unsolicited advice, don't be preachy. Just answer what's asked, "
  "using casual language.\n\n"
  "You have tools available - only call one when you actually need it, not on every message:\n"
  "- find_member: look up a server member by name to get their exact @mention before tagging "
  "anyone. Never guess or hand-type a mention.\n"
  "- get_channel_context: pull recent messages from a named channel if you genuinely need more "
  "context to answer (e.g. 'what were we just talking about in #general').\n"
  "- search_dsa_problems: look up real LeetCode/NeetCode/Codeforces problems by title or topic "
  "when asked for problem recommendations, so you recommend real problems with real links "
  "instead of making them up.\n"
  "- web_search: look up current or factual info you're not confident about from memory."
)


@dataclass
class BotContext:
  guild: Optional[discord.Guild] = None


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


async def _get_channel_context_impl(
  wrapper: RunContextWrapper[BotContext], channel_name: str, limit: int = 20
) -> str:
  """Fetch the most recent messages from a named text channel in the current server,
  for extra conversational context. Only use this when you genuinely need recent
  chat history to answer the question.

  Args:
    channel_name: The channel name, with or without the leading '#'.
    limit: How many recent messages to fetch (max 50).
  """
  guild = wrapper.context.guild if wrapper.context else None
  if not guild:
    return "No server context available."

  channel_name = channel_name.lstrip("#")
  channel = discord.utils.get(guild.text_channels, name=channel_name)
  if not channel:
    return f"No channel named #{channel_name} found in this server."

  if not channel.permissions_for(guild.me).read_message_history:
    return f"I don't have permission to read #{channel_name}."

  limit = max(1, min(limit, 50))
  lines = []
  async for msg in channel.history(limit=limit):
    if msg.author.bot:
      continue
    lines.append(f"{msg.author.display_name}: {msg.content}")
  lines.reverse()

  return "\n".join(lines) if lines else f"No recent messages found in #{channel_name}."


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
  wrapper: RunContextWrapper[BotContext], query: str, source: str = "all", limit: int = 5
) -> str:
  """Search real LeetCode, NeetCode, and Codeforces problem sets by title or topic
  keyword, so you can recommend real problems with real links instead of making them up.

  Args:
    query: A title keyword or topic to search for (e.g. "two pointers", "binary search").
    source: Which set to search: "leetcode", "neetcode", "codeforces", or "all".
    limit: Max number of results to return (max 10).
  """
  query_lower = query.lower().strip()
  if not query_lower:
    return "Provide a search term (title keyword or topic)."
  limit = max(1, min(limit, 10))

  pools = []
  if source in ("all", "leetcode"):
    pools.append(("LeetCode", _LEETCODE_PROBLEMS, _leetcode_link))
  if source in ("all", "neetcode"):
    pools.append(("NeetCode", _NEETCODE_PROBLEMS, _neetcode_link))
  if source in ("all", "codeforces"):
    pools.append(("Codeforces", _CODEFORCES_PROBLEMS, _codeforces_link))

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


# --- Input guardrail: cheap, no-extra-API-call first line of defense against ---
# --- prompt injection / jailbreak attempts and cost-abuse via giant prompts. ---

_INJECTION_PATTERNS = [
  re.compile(r"ignore (all|any|previous|prior)\s+(instructions|rules)", re.I),
  re.compile(r"disregard (your|all|any)\s+(instructions|rules|guidelines)", re.I),
  re.compile(r"reveal (your|the)\s+(system|hidden)\s+prompt", re.I),
  re.compile(r"(what|show me)\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions)", re.I),
  re.compile(r"you are now\s+(dan|jailbroken|unrestricted|unfiltered)", re.I),
  re.compile(r"pretend\s+(you have|to have)\s+no\s+(rules|restrictions|filters|guidelines)", re.I),
  re.compile(r"act as if\s+you have no\s+(rules|restrictions|filters|guidelines)", re.I),
]


async def _prompt_safety_guardrail(
  wrapper: RunContextWrapper[BotContext], agent: Agent, agent_input: str | list
) -> GuardrailFunctionOutput:
  text = agent_input if isinstance(agent_input, str) else str(agent_input)

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
web_search = function_tool(
  _web_search_impl,
  name_override="web_search",
  description_override=_web_search_impl.__doc__.strip().split("\n\n")[0],
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
        tools=[find_member, get_channel_context, search_dsa_problems, web_search],
        input_guardrails=[
          InputGuardrail(
            guardrail_function=_prompt_safety_guardrail,
            name="prompt_safety",
            # Run before the model call, not alongside it, so a blocked prompt
            # never reaches the DeepSeek API.
            run_in_parallel=False,
          )
        ],
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
    channel_id: Optional[int] = None,
    user_id: Optional[int] = None,
    context: str = "",
  ) -> str:
    """Run the agent. When channel_id and user_id are both given, the
    conversation is remembered across calls for that (channel, user) pair -
    each following turn sees prior turns automatically, no manual history
    stitching needed."""
    if not self.enabled or not self.agent:
      return "Error: AI is not configured — missing DEEPSEEK_API_KEY."
    if not prompt:
      return "You need a prompt to be able to interact with the AI."

    full_prompt = f"{context}\n\n{prompt}" if context else prompt
    logger.info(f"🤖 Agent request: {prompt[:80]}...")

    session = self._build_session(channel_id, user_id) if channel_id and user_id else None

    try:
      result = await Runner.run(
        self.agent, full_prompt, context=BotContext(guild=guild), session=session
      )
      output = str(result.final_output) if result.final_output else "No response from the agent."
      logger.info(f"🤖 Agent response: {output[:80]}...")
      return output
    except InputGuardrailTripwireTriggered as e:
      reason = e.guardrail_result.output.output_info
      logger.warning(f"🛑 Input guardrail tripped: {reason}")
      return "I can't help with that one. Try rephrasing?"
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
