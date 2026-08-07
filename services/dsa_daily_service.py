import json
import os
import random
from typing import Dict, List, Optional, Tuple

import discord

from utils.logging import get_logger

logger = get_logger("dsa_daily")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

LEETCODE_DATA_PATH = os.path.join(DATA_DIR, "leetcode_problems.json")
LEETCODE_PROGRESS_PATH = os.path.join(DATA_DIR, "leetcode_daily_progress.json")

CODEFORCES_DATA_PATH = os.path.join(DATA_DIR, "codeforces_problems.json")
CODEFORCES_PROGRESS_PATH = os.path.join(DATA_DIR, "codeforces_daily_progress.json")


class ShuffledDailyRotation:
  """Shuffles a list of problems once and hands out one per day.

  The shuffled order + position are persisted to disk so restarts don't
  reset progress or repeat a problem within the same pass. Once the whole
  shuffled list has been exhausted, it reshuffles for a fresh pass.
  """

  def __init__(self, data_path: str, progress_path: str, label: str):
    self.data_path = data_path
    self.progress_path = progress_path
    self.label = label
    self.problems = self._load_problems()

  def _load_problems(self) -> List[Dict]:
    try:
      with open(self.data_path, "r") as f:
        return json.load(f)
    except Exception as e:
      logger.error(f"Failed to load {self.label} data: {e}")
      return []

  def _new_order(self, total: int) -> List[int]:
    order = list(range(total))
    random.shuffle(order)
    logger.info(f"🔀 Shuffled {total} {self.label} problems for a new rotation")
    return order

  def _save_progress(self, order: List[int], index: int):
    os.makedirs(os.path.dirname(self.progress_path), exist_ok=True)
    with open(self.progress_path, "w") as f:
      json.dump({"order": order, "current_index": index}, f)

  def _load_progress(self) -> Tuple[List[int], int]:
    """Return (shuffled_order, current_index), reshuffling if missing/stale/exhausted."""
    total = len(self.problems)
    try:
      with open(self.progress_path, "r") as f:
        data = json.load(f)
      order = data.get("order", [])
      index = data.get("current_index", 0)
      if sorted(order) != list(range(total)):
        raise ValueError("stale shuffle order (problem set changed)")
      if index >= len(order):
        order = self._new_order(total)
        index = 0
        self._save_progress(order, index)
      return order, index
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
      order = self._new_order(total)
      self._save_progress(order, 0)
      return order, 0

  def get_next_problem(self) -> Tuple[Optional[Dict], int, int]:
    """Get the next problem in the shuffled rotation and advance. Returns (problem, position, total)."""
    if not self.problems:
      return None, 0, 0

    order, index = self._load_progress()
    total = len(order)

    problem = self.problems[order[index]]
    position = index + 1

    self._save_progress(order, index + 1)

    logger.info(f"📋 {self.label} [{position}/{total}]: {problem.get('title')}")
    return problem, position, total

  def get_progress(self) -> Tuple[int, int]:
    """Return (next_position, total) without advancing."""
    order, index = self._load_progress()
    total = len(order)
    if index >= total:
      index = 0
    return index + 1, total

  def peek_current_problem(self) -> Tuple[Optional[Dict], int, int]:
    """Return the problem that would be handed out next, WITHOUT advancing
    the rotation. Safe to call as often as needed (e.g. from a read-only
    chat tool) without affecting what gets posted next."""
    if not self.problems:
      return None, 0, 0

    order, index = self._load_progress()
    total = len(order)
    problem = self.problems[order[index]]
    return problem, index + 1, total


class DsaDailyService:
  """Manages the daily shuffled LeetCode + Codeforces problem rotation."""

  def __init__(self):
    self.leetcode = ShuffledDailyRotation(LEETCODE_DATA_PATH, LEETCODE_PROGRESS_PATH, "LeetCode")
    self.codeforces = ShuffledDailyRotation(CODEFORCES_DATA_PATH, CODEFORCES_PROGRESS_PATH, "Codeforces")

  def peek_leetcode(self) -> Tuple[Optional[Dict], int, int]:
    return self.leetcode.peek_current_problem()

  def peek_codeforces(self) -> Tuple[Optional[Dict], int, int]:
    return self.codeforces.peek_current_problem()

  @staticmethod
  def _leetcode_link(problem: Dict) -> str:
    slug = problem.get("slug", "")
    return f"https://leetcode.com/problems/{slug}/"

  @staticmethod
  def _codeforces_link(problem: Dict) -> str:
    contest_id = problem.get("contestId")
    index = problem.get("index", "")
    return f"https://codeforces.com/problemset/problem/{contest_id}/{index}"

  @staticmethod
  def _color_for_difficulty(difficulty: str) -> discord.Color:
    if difficulty == "Medium":
      return discord.Color.gold()
    if difficulty == "Hard":
      return discord.Color.red()
    return discord.Color.green()

  def get_next_leetcode(self) -> Tuple[Optional[Dict], int, int]:
    return self.leetcode.get_next_problem()

  def get_next_codeforces(self) -> Tuple[Optional[Dict], int, int]:
    return self.codeforces.get_next_problem()

  def get_progress(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Return ((leetcode_next, leetcode_total), (codeforces_next, codeforces_total))."""
    return self.leetcode.get_progress(), self.codeforces.get_progress()

  def create_leetcode_embed(self, problem: Dict, position: int, total: int) -> discord.Embed:
    title = problem.get("title", "Unknown")
    difficulty = problem.get("difficulty", "Unknown")
    topics = problem.get("topics", "")
    link = self._leetcode_link(problem)

    embed = discord.Embed(
      title=f"🧩 Daily LeetCode: {title}",
      url=link,
      description=f"**Difficulty:** {difficulty}\n**Progress:** {position}/{total}",
      color=self._color_for_difficulty(difficulty),
    )
    embed.add_field(name="Problem ID", value=str(problem.get("id", "?")), inline=True)
    if topics:
      embed.add_field(name="Topics", value=topics, inline=False)
    embed.add_field(name="🔗 Link", value=link, inline=False)
    embed.set_footer(text=f"LeetCode • Problem {position} of {total} • Cracked LeetCode Bot 🚀")

    return embed

  def create_codeforces_embed(self, problem: Dict, position: int, total: int) -> discord.Embed:
    title = problem.get("title", "Unknown")
    difficulty = problem.get("difficulty", "Unknown")
    rating = problem.get("rating", "?")
    topics = problem.get("topics", "")
    link = self._codeforces_link(problem)

    embed = discord.Embed(
      title=f"⚔️ Daily Codeforces: {title}",
      url=link,
      description=f"**Difficulty:** {difficulty} ({rating})\n**Progress:** {position}/{total}",
      color=self._color_for_difficulty(difficulty),
    )
    embed.add_field(name="Problem", value=str(problem.get("id", "?")), inline=True)
    embed.add_field(name="Rating", value=str(rating), inline=True)
    if topics:
      embed.add_field(name="Topics", value=topics, inline=False)
    embed.add_field(name="🔗 Link", value=link, inline=False)
    embed.set_footer(text=f"Codeforces • Problem {position} of {total} • Cracked LeetCode Bot 🚀")

    return embed


_dsa_daily_service: Optional[DsaDailyService] = None


def get_dsa_daily_service() -> DsaDailyService:
  global _dsa_daily_service
  if _dsa_daily_service is None:
    _dsa_daily_service = DsaDailyService()
  return _dsa_daily_service
