from typing import List, Optional

import aiosqlite

from config import DB_PATH


async def init_db():
  import os

  db_dir = os.path.dirname(DB_PATH)
  if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

  schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
  async with aiosqlite.connect(DB_PATH) as db:
    with open(schema_path, "r") as f:
      schema = f.read()
    await db.executescript(schema)
    await db.commit()


async def insert_message(
  message_id: str,
  channel_id: str,
  guild_id: str,
  author_id: str,
  content: str,
  content_hash: str,
  message_url: str,
) -> bool:
  async with aiosqlite.connect(DB_PATH) as db:
    try:
      await db.execute(
        """
                INSERT INTO messages 
                (message_id, channel_id, guild_id, author_id, content, content_hash, message_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
        (
          message_id,
          channel_id,
          guild_id,
          author_id,
          content,
          content_hash,
          message_url,
        ),
      )
      await db.commit()
      return True
    except aiosqlite.IntegrityError:
      return False


async def get_message_by_hash(content_hash: str) -> Optional[dict]:
  async with aiosqlite.connect(DB_PATH) as db:
    db.row_factory = aiosqlite.Row
    async with db.execute(
      "SELECT * FROM messages WHERE content_hash = ?", (content_hash,)
    ) as cursor:
      row = await cursor.fetchone()
      if row:
        return dict(row)
      return None


async def get_existing_hashes(content_hashes: List[str]) -> set:
  if not content_hashes:
    return set()

  async with aiosqlite.connect(DB_PATH) as db:
    placeholders = ",".join("?" * len(content_hashes))
    async with db.execute(
      f"SELECT content_hash FROM messages WHERE content_hash IN ({placeholders})",
      content_hashes,
    ) as cursor:
      rows = await cursor.fetchall()
      return {row[0] for row in rows}


async def get_message_urls(message_ids: List[int]) -> List[str]:
  if not message_ids:
    return []

  async with aiosqlite.connect(DB_PATH) as db:
    placeholders = ",".join("?" * len(message_ids))
    async with db.execute(
      f"SELECT message_url FROM messages WHERE id IN ({placeholders})",
      message_ids,
    ) as cursor:
      rows = await cursor.fetchall()
      return [row[0] for row in rows]


async def reset_database(guild_id: Optional[str] = None) -> int:
  async with aiosqlite.connect(DB_PATH) as db:
    if guild_id:
      async with db.execute(
        "DELETE FROM messages WHERE guild_id = ?", (guild_id,)
      ) as cursor:
        await db.commit()
        return cursor.rowcount
    else:
      async with db.execute("DELETE FROM messages") as cursor:
        await db.commit()
        return cursor.rowcount


async def get_message_count(guild_id: Optional[str] = None) -> int:
  async with aiosqlite.connect(DB_PATH) as db:
    if guild_id:
      async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE guild_id = ?", (guild_id,)
      ) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0
    else:
      async with db.execute("SELECT COUNT(*) FROM messages") as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_weekly_message_counts(guild_id: str) -> List[dict]:
  """Return per-user message counts for the past 7 days, ordered descending."""
  import datetime
  cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
  async with aiosqlite.connect(DB_PATH) as db:
    async with db.execute(
      """
      SELECT author_id, COUNT(*) as cnt
      FROM messages
      WHERE guild_id = ? AND created_at >= ?
      GROUP BY author_id
      ORDER BY cnt DESC
      """,
      (guild_id, cutoff),
    ) as cursor:
      rows = await cursor.fetchall()
      return [{"author_id": row[0], "count": row[1]} for row in rows]
