CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    channel_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message_url TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_content_hash ON messages(content_hash);
CREATE INDEX IF NOT EXISTS idx_guild_id ON messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_guild_created ON messages(guild_id, created_at);
