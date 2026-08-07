import json
import os
from typing import Dict, Optional, Tuple

import discord

from utils.logging import get_logger

logger = get_logger("neetcode")

NEETCODE_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "neetcode150.json")
NEETCODE_PROGRESS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "neetcode_progress.json")

# Category emoji mapping
CATEGORY_EMOJI = {
  "Arrays & Hashing": "🗃️",
  "Two Pointers": "👉👈",
  "Sliding Window": "🪟",
  "Stack": "📚",
  "Binary Search": "🔍",
  "Linked List": "🔗",
  "Trees": "🌳",
  "Tries": "🔤",
  "Heap / Priority Queue": "⛰️",
  "Backtracking": "🔙",
  "Graphs": "🕸️",
  "Advanced Graphs": "🗺️",
  "1-D Dynamic Programming": "📈",
  "2-D Dynamic Programming": "📊",
  "Greedy": "🤑",
  "Intervals": "📐",
  "Math & Geometry": "🧮",
  "Bit Manipulation": "🔢",
}


class NeetCodeService:
  """Service to manage NeetCode 150 daily problem rotation."""

  def __init__(self):
    self.problems = self._load_problems()

  def _load_problems(self) -> list:
    try:
      with open(NEETCODE_DATA_PATH, "r") as f:
        return json.load(f)
    except Exception as e:
      logger.error(f"Failed to load NeetCode 150 data: {e}")
      return []

  def _load_progress(self) -> int:
    try:
      with open(NEETCODE_PROGRESS_PATH, "r") as f:
        data = json.load(f)
        return data.get("current_index", 0)
    except (FileNotFoundError, json.JSONDecodeError):
      return 0

  def _save_progress(self, index: int):
    os.makedirs(os.path.dirname(NEETCODE_PROGRESS_PATH), exist_ok=True)
    with open(NEETCODE_PROGRESS_PATH, "w") as f:
      json.dump({"current_index": index}, f)

  def get_next_problem(self) -> Tuple[Optional[Dict], int, int]:
    """Get the next problem and advance the index. Returns (problem, current_number, total)."""
    if not self.problems:
      return None, 0, 0

    index = self._load_progress()
    total = len(self.problems)

    # Wrap around if we've gone through all problems
    if index >= total:
      index = 0

    problem = self.problems[index]
    current_number = index + 1

    # Advance to next
    self._save_progress(index + 1)

    logger.info(f"📋 NeetCode 150 [{current_number}/{total}]: {problem['title']}")
    return problem, current_number, total

  def get_progress(self) -> Tuple[int, int]:
    """Return (next_problem_number, total)."""
    index = self._load_progress()
    total = len(self.problems)
    if index >= total:
      index = 0
    return index + 1, total

  def peek_next_problem(self) -> Tuple[Optional[Dict], int, int]:
    """Return the problem that would be handed out next, WITHOUT advancing
    the rotation. Safe to call from a read-only chat tool."""
    if not self.problems:
      return None, 0, 0
    index = self._load_progress()
    total = len(self.problems)
    if index >= total:
      index = 0
    return self.problems[index], index + 1, total

  def create_neetcode_embed(self, problem: Dict, current: int, total: int) -> discord.Embed:
    """Create a Discord embed for a NeetCode 150 problem."""
    title = problem.get("title", "Unknown")
    problem_id = problem.get("id", "?")
    difficulty = problem.get("difficulty", "Unknown")
    category = problem.get("category", "Unknown")
    link = problem.get("link", f"https://leetcode.com/problems/{problem.get('titleSlug', '')}/")
    neetcode_link = problem.get("neetcodeLink", f"https://neetcode.io/problems/{problem.get('titleSlug', '')}")

    emoji = CATEGORY_EMOJI.get(category, "📝")

    # Color based on difficulty
    color = discord.Color.green()
    if difficulty == "Medium":
      color = discord.Color.gold()
    elif difficulty == "Hard":
      color = discord.Color.red()

    embed = discord.Embed(
      title=f"📋 NeetCode 150: {title}",
      url=link,
      description=(
        f"**Category:** {emoji} {category}\n"
        f"**Difficulty:** {difficulty}\n"
        f"**Progress:** {current}/{total}"
      ),
      color=color,
    )

    embed.add_field(name="LeetCode #", value=str(problem_id), inline=True)
    embed.add_field(name="NeetCode", value=f"[View Solution]({neetcode_link})", inline=True)

    embed.set_footer(text=f"NeetCode 150 • Problem {current} of {total} • Cracked LeetCode Bot 🚀")

    return embed


_neetcode_service: Optional[NeetCodeService] = None


def get_neetcode_service() -> NeetCodeService:
  global _neetcode_service
  if _neetcode_service is None:
    _neetcode_service = NeetCodeService()
  return _neetcode_service
