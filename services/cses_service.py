import json
import os
from typing import Dict, Optional, Tuple

import discord

from utils.logging import get_logger

logger = get_logger("cses")

CSES_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cses_problems.json")
CSES_PROGRESS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cses_progress.json")

# Category emoji mapping, in the same order CSES presents them.
CATEGORY_EMOJI = {
  "Introductory Problems": "🌱",
  "Sorting and Searching": "🔍",
  "Dynamic Programming": "📈",
  "Graph Algorithms": "🕸️",
  "Range Queries": "📏",
  "Tree Algorithms": "🌳",
  "Mathematics": "🧮",
  "String Algorithms": "🔤",
  "Geometry": "📐",
  "Advanced Techniques": "🧠",
  "Sliding Window Problems": "🪟",
  "Interactive Problems": "🎮",
  "Bitwise Operations": "🔢",
  "Construction Problems": "🏗️",
  "Advanced Graph Problems": "🗺️",
  "Counting Problems": "🔢",
  "Additional Problems I": "➕",
  "Additional Problems II": "➕",
}


class CsesService:
  """Serves the CSES Problem Set in its official topic order (Introductory ->
  Sorting and Searching -> ... -> Additional Problems II) - one problem at a
  time, never shuffled, so practice follows the intended curriculum."""

  def __init__(self):
    self.problems = self._load_problems()

  def _load_problems(self) -> list:
    try:
      with open(CSES_DATA_PATH, "r") as f:
        return json.load(f)
    except Exception as e:
      logger.error(f"Failed to load CSES data: {e}")
      return []

  def _load_progress(self) -> int:
    try:
      with open(CSES_PROGRESS_PATH, "r") as f:
        data = json.load(f)
        return data.get("current_index", 0)
    except (FileNotFoundError, json.JSONDecodeError):
      return 0

  def _save_progress(self, index: int):
    os.makedirs(os.path.dirname(CSES_PROGRESS_PATH), exist_ok=True)
    with open(CSES_PROGRESS_PATH, "w") as f:
      json.dump({"current_index": index}, f)

  def get_next_problem(self) -> Tuple[Optional[Dict], int, int]:
    """Get the next problem in order and advance the index. Returns (problem, current_number, total)."""
    if not self.problems:
      return None, 0, 0

    index = self._load_progress()
    total = len(self.problems)

    if index >= total:
      index = 0

    problem = self.problems[index]
    current_number = index + 1

    self._save_progress(index + 1)

    logger.info(f"📋 CSES [{current_number}/{total}]: {problem.get('title')} ({problem.get('category')})")
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

  def create_cses_embed(self, problem: Dict, current: int, total: int) -> discord.Embed:
    """Create a Discord embed for a CSES problem."""
    title = problem.get("title", "Unknown")
    category = problem.get("category", "Unknown")
    link = problem.get("link", f"https://cses.fi/problemset/task/{problem.get('task_id', '')}")

    emoji = CATEGORY_EMOJI.get(category, "📝")

    embed = discord.Embed(
      title=f"📘 CSES: {title}",
      url=link,
      description=(
        f"**Section:** {emoji} {category}\n"
        f"**Progress:** {current}/{total}"
      ),
      color=discord.Color.blue(),
    )

    embed.add_field(name="🔗 Link", value=link, inline=False)
    embed.set_footer(text=f"CSES Problem Set • Problem {current} of {total} • Cracked LeetCode Bot 🚀")

    return embed


_cses_service: Optional[CsesService] = None


def get_cses_service() -> CsesService:
  global _cses_service
  if _cses_service is None:
    _cses_service = CsesService()
  return _cses_service
