import json
import os
from typing import Dict, Optional, Tuple

import discord

from utils.logging import get_logger

logger = get_logger("project_euler")

EULER_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "project_euler_problems.json")
EULER_PROGRESS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "project_euler_progress.json")


class ProjectEulerService:
  """Serves Project Euler problems in numeric order (1, 2, 3, ...) - one
  problem at a time, never shuffled, since the problems get harder roughly
  in order and practice should follow that curve."""

  def __init__(self):
    self.problems = self._load_problems()

  def _load_problems(self) -> list:
    try:
      with open(EULER_DATA_PATH, "r") as f:
        return json.load(f)
    except Exception as e:
      logger.error(f"Failed to load Project Euler data: {e}")
      return []

  def _load_progress(self) -> int:
    try:
      with open(EULER_PROGRESS_PATH, "r") as f:
        data = json.load(f)
        return data.get("current_index", 0)
    except (FileNotFoundError, json.JSONDecodeError):
      return 0

  def _save_progress(self, index: int):
    os.makedirs(os.path.dirname(EULER_PROGRESS_PATH), exist_ok=True)
    with open(EULER_PROGRESS_PATH, "w") as f:
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

    logger.info(f"🧮 Project Euler [{current_number}/{total}]: #{problem.get('number')} {problem.get('title')}")
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

  def create_euler_embed(self, problem: Dict, current: int, total: int) -> discord.Embed:
    """Create a Discord embed for a Project Euler problem."""
    number = problem.get("number", "?")
    title = problem.get("title", "Unknown")
    link = problem.get("link", f"https://projecteuler.net/problem={number}")

    embed = discord.Embed(
      title=f"🧮 Project Euler #{number}: {title}",
      url=link,
      color=discord.Color.purple(),
    )

    embed.add_field(name="🔗 Link", value=link, inline=False)
    embed.set_footer(text="Project Euler • Cracked LeetCode Bot 🚀")

    return embed


_project_euler_service: Optional[ProjectEulerService] = None


def get_project_euler_service() -> ProjectEulerService:
  global _project_euler_service
  if _project_euler_service is None:
    _project_euler_service = ProjectEulerService()
  return _project_euler_service
