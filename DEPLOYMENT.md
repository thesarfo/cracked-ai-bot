# Deployment Guide

## Quick Start (Docker)

```bash
# 1. Copy environment file and configure
cp .env.example .env
# Edit .env with your DISCORD_BOT_TOKEN and DEEPSEEK_API_KEY

# 2. Build and run
make up-d

# 3. View logs
make logs
```

## Docker Deployment

### Prerequisites
- Docker and Docker Compose installed
- `.env` file with required environment variables

### Deploy

```bash
# Build and start in background
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Data Persistence

Data is persisted via Docker volumes:
- `./data/` → `/app/data` (SQLite database with messages and embeddings)
- `./messages.json` → `/app/messages.json` (Leetcode rotation config)

---

## Manual Deployment (Any VM)

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Steps

```bash
# 1. Clone and enter directory
git clone <repo-url>
cd cracked-leetcode-junkie-bot

# 2. Install dependencies
uv sync

# 3. Configure environment
cp .env.example .env
# Edit .env with your tokens

# 4. Run the bot
uv run python main.py
```

### Systemd Service (Recommended)

Create `/etc/systemd/system/discord-bot.service`:

```ini
[Unit]
Description=Discord Bot
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/cracked-leetcode-junkie-bot
ExecStart=/path/to/.local/bin/uv run python main.py
Restart=always
RestartSec=10
Environment=PATH=/usr/bin:/path/to/.local/bin

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl start discord-bot

# View logs
journalctl -u discord-bot -f
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token |
| `DEEPSEEK_API_KEY` | Yes | DeepSeek API key — powers the AI agent (chat, mentions/replies, `/ai_status`) via the OpenAI Agents SDK pointed at DeepSeek's OpenAI-compatible API |

---

## Monitoring

```bash
# Docker logs
docker-compose logs -f

# Systemd logs
journalctl -u discord-bot -f
```

---

## Troubleshooting

**Bot not starting:**
- Check `.env` file has valid tokens
- Verify Python 3.12+ installed

**Database errors:**
- Ensure `data/` directory exists and is writable
- Check disk space

**Permission denied:**
- Run `chmod -R 755 data/` on the data directory
