"""
Posts indicator updates (periodic summary + strong-buy/sell alerts) to a Discord
channel via the bot REST API — plain synchronous HTTP, no gateway connection
needed for one-way posts, so this fits directly into the polling loop in main.py.

The /dashboard slash command (which does need a live gateway connection to
receive interactions) lives separately in Notifications/discord_bot.py, and
reuses the formatting helpers here.
"""
import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
import Evaluation.rating_utils as rating_utils

logger = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
MAX_MSG_LEN = 2000
WEEKLY_INTERVAL = timedelta(days=7)
WEEKLY_STATE_PATH = "Notifications/.weekly_state"


class DiscordNotifier:
    """Sends messages to one Discord channel using a bot token."""

    def __init__(self, base_dir):
        load_dotenv(Path(base_dir) / ".env")
        token = os.getenv("DISCORD_BOT_TOKEN")
        channel_id = os.getenv("DISCORD_CHANNEL_ID")

        self.enabled = bool(token) and bool(channel_id) and not token.lower().startswith("your_")
        if not self.enabled:
            logger.warning(
                "Discord notifications disabled: set DISCORD_BOT_TOKEN and "
                "DISCORD_CHANNEL_ID in .env"
            )
        self.token = token
        self.channel_id = channel_id

    def send_message(self, content):
        """Posts `content`, splitting on line breaks if over Discord's 2000-char limit."""
        if not self.enabled:
            logger.info(f"[Discord disabled] {content[:200]}")
            return False

        ok = True
        for chunk in chunk_message(content):
            ok = self._post(chunk) and ok
        return ok

    def _post(self, content, retry=True):
        url = f"{API_BASE}/channels/{self.channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}", "Content-Type": "application/json"}
        try:
            resp = requests.post(url, headers=headers, json={"content": content}, timeout=10)
            if resp.status_code == 429 and retry:
                retry_after = resp.json().get("retry_after", 1)
                time.sleep(retry_after)
                return self._post(content, retry=False)
            if not resp.ok:
                logger.error(f"Discord post failed ({resp.status_code}): {resp.text[:300]}")
                return False
            return True
        except requests.RequestException:
            logger.exception("Discord post failed")
            return False


def chunk_message(content, limit=MAX_MSG_LEN):
    """Splits `content` on line breaks into pieces no longer than Discord's message limit."""
    if len(content) <= limit:
        return [content]
    chunks, cur = [], ""
    for line in content.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def _fmt(v, nd=1):
    return f"{v:.{nd}f}" if v is not None else "--"


def _fmt_dollar(v):
    return f"${v:.2f}" if v is not None else "--"


def format_alert(rating):
    """Single-ticker message for a Strong Buy / Strong Sell tier transition."""
    r = rating
    return (
        f"**{r['ticker']}** just became a **{r['tier']}** (rating {r['rating']:.1f}/10) "
        f"— Close ${r['close']:.2f}, RSI {_fmt(r['rsi'])}, "
        f"SMA20 {_fmt_dollar(r['sma20'])}, SMA50 {_fmt_dollar(r['sma50'])}, ADX {_fmt(r['adx'])}"
    )


def format_ratings_table(ratings, title):
    """Ratings table for `ratings` (sorted best-to-worst) under a bold `title` line."""
    header = f"**{title}**"
    if not ratings:
        return f"{header}\nNo indicator data available yet."

    lines = [f"{'TICKER':<7}{'CLOSE':>9}{'RATING':>8}  {'SIGNAL':<12}{'RSI':>6}{'ADX':>6}"]
    for r in ratings:
        lines.append(
            f"{r['ticker']:<7}{_fmt_dollar(r['close']):>9}{r['rating']:>7.1f}  "
            f"{r['tier']:<12}{_fmt(r['rsi']):>6}{_fmt(r['adx']):>6}"
        )
    table = "\n".join(lines)
    return f"{header}\n```\n{table}\n```"


def format_weekly_summary(ratings, generated=None):
    """Full-watchlist ratings table, sorted best-to-worst (matches the dashboard Home page)."""
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    return format_ratings_table(ratings, f"Weekly Indicator Summary — {generated}")


def _weekly_state_path(base_dir):
    return Path(base_dir) / WEEKLY_STATE_PATH


def _read_last_sent(base_dir):
    try:
        return datetime.fromisoformat(_weekly_state_path(base_dir).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _write_last_sent(base_dir, when):
    path = _weekly_state_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(when.isoformat())


def maybe_send_weekly_summary(base_dir, tickers, notifier, interval=WEEKLY_INTERVAL):
    """Sends the ratings table to Discord if `interval` has elapsed since the last send."""
    now = datetime.now(timezone.utc)
    last_sent = _read_last_sent(base_dir)
    if last_sent is not None and now - last_sent < interval:
        return False

    ratings = rating_utils.all_ratings(tickers, base_dir)
    notifier.send_message(format_weekly_summary(ratings))
    _write_last_sent(base_dir, now)
    return True


def check_rating_alerts(base_dir, tickers, notifier, last_tiers, holdings=None):
    """
    Computes each ticker's current rating tier and alerts on any transition into
    STRONG BUY or STRONG SELL. STRONG SELL is only alerted for tickers in `holdings`
    (selling something you don't hold isn't actionable) when `holdings` is given;
    STRONG BUY always alerts, for any watchlisted ticker.

    `last_tiers` is a caller-owned {ticker: tier} dict that persists across calls
    (in-memory is fine — a missed alert on process restart just means the next
    loop iteration re-evaluates from current data).
    """
    for t in tickers:
        try:
            r = rating_utils.rating_for_ticker(t, base_dir)
        except Exception:
            logger.exception(f"Failed to compute rating for {t}")
            continue
        if r is None:
            continue

        prev_tier = last_tiers.get(t)
        last_tiers[t] = r["tier"]

        if r["tier"] == prev_tier:
            continue
        if r["tier"] not in ("STRONG BUY", "STRONG SELL"):
            continue
        if r["tier"] == "STRONG SELL" and holdings is not None and t not in holdings:
            continue

        logger.info(f"{t}: rating tier -> {r['tier']} ({r['rating']:.1f}/10)")
        notifier.send_message(format_alert(r))
