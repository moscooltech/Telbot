"""
Series state manager: the ONLY code allowed to read/write series/active.json.

Design (from series-unorouter-spec.md):
- One active series at a time, stored in a single JSON file.
- All mutations go through this class; handlers never hand-edit the JSON.
- Saves are atomic (tmp file + os.replace) so a crash mid-write never corrupts state.
- No Telegram imports here - pure logic + file I/O, easy to unit test.
- Timezone-aware scheduling with a stdlib-only fallback (zoneinfo, else fixed offset).
"""
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone

from config import (
    SERIES_FILE,
    SERIES_MAX_PROMPTS,
    SERIES_TIMEZONE,
)

logger = logging.getLogger(__name__)

# Reason codes returned by is_due()
REASON_OK = "ok"
REASON_NOT_DUE = "not-due"
REASON_PAUSED = "paused"
REASON_EMPTY = "empty"
REASON_NO_SERIES = "no-series"


def _tz():
    """Resolve the configured timezone.

    Prefers stdlib zoneinfo (Python 3.9+, runtime is 3.12); falls back to a
    fixed UTC+1 offset (Africa/Lagos has no DST) if the tz database is
    unavailable (slim Docker images without tzdata).
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(SERIES_TIMEZONE)
    except Exception:
        logger.warning("Timezone %r unavailable; using fixed UTC+1 fallback.", SERIES_TIMEZONE)
        return timezone(timedelta(hours=1), name="Africa/Lagos")


def _anchor_seconds_past_midnight(anchor):
    """'09:00' -> seconds since local midnight. Returns None on bad input."""
    try:
        hh, mm = anchor.split(":")
        hh, mm = int(hh), int(mm)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 3600 + mm * 60
    except (ValueError, AttributeError):
        pass
    return None


def _next_anchor_time(now_local, interval_hours, anchor):
    """Next wall-clock occurrence of `anchor` that is strictly after
    `now_local`, stepping in `interval_hours` multiples from today's anchor."""
    secs = _anchor_seconds_past_midnight(anchor)
    today_anchor = now_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=secs)
    interval = timedelta(hours=interval_hours)
    candidate = today_anchor
    while candidate <= now_local:
        candidate += interval
    return candidate


def _iso(dt):
    return dt.isoformat()


def _parse_iso(value):
    """Parse ISO-8601; naive timestamps are assumed to be the series timezone."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_tz())
        return dt
    except ValueError:
        return None


def _validate_series(data):
    """Structural validation for a loaded series dict. Returns bool."""
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("title"), str) or not isinstance(data.get("prompts"), list):
        return False
    if not isinstance(data.get("schedule"), dict):
        return False
    for p in data["prompts"]:
        if not isinstance(p, dict) or not isinstance(p.get("prompt"), str):
            return False
    return True


class SeriesManager:
    """Reads, validates and mutates the single active series file."""

    def __init__(self, file_path=None):
        self.file_path = file_path or SERIES_FILE

    # ------------------------------------------------------------------ I/O

    def load(self):
        """Load + validate the series file. Returns a dict or None.
        Corrupt/invalid files are reported (not raised) so the scheduler and
        handlers can degrade gracefully."""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Series file unreadable (%s): %s", self.file_path, e)
            return None
        if not _validate_series(data):
            logger.warning("Series file failed validation; ignoring (%s).", self.file_path)
            return None
        return data

    def save(self, data):
        """Atomic write: dump to a tmp file in the same directory, then
        os.replace() over the target (atomic on POSIX)."""
        directory = os.path.dirname(self.file_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".series_", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.file_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def exists(self):
        return os.path.exists(self.file_path)

    # ------------------------------------------------------------ mutations

    def create(self, title, owner_chat_id):
        """Build a fresh series dict (schedule disabled until /series schedule)."""
        now = datetime.now(_tz())
        data = {
            "series_id": "s_%d_%04x" % (int(time.time()), int(time.time() * 1000) % 0xFFFF),
            "title": title,
            "owner_chat_id": owner_chat_id,
            "created_at": _iso(now),
            "schedule": {
                "enabled": False,
                "interval_hours": 24,
                "next_run": None,
                "anchor": None,
                "timezone": SERIES_TIMEZONE,
                "last_run": None,
                "last_result": None,
                "last_failure": None,
                "runs_completed": 0,
            },
            "prompts": [],
        }
        self.save(data)
        return data

    def add_prompt(self, data, text, fmt="narration"):
        """Append one prompt. Returns (ok, reason). Enforces the pending cap."""
        pending = len(data.get("prompts", []))
        if pending >= SERIES_MAX_PROMPTS:
            return False, "cap"
        now = _iso(datetime.now(_tz()))
        data["prompts"].append({
            "id": "p%03d" % (pending + 1),
            "prompt": text.strip(),
            "format": fmt if fmt in ("narration", "description") else "narration",
            "status": "pending",
            "created_at": now,
        })
        return True, "ok"

    def pop_next(self, data):
        """Remove + return the first pending prompt (caller persists on success).
        The prompt dict is kept by the caller so a failed run can be re-inserted."""
        for i, p in enumerate(data.get("prompts", [])):
            if p.get("status") == "pending":
                data["prompts"].pop(i)
                self._resequence(data)
                return p
        return None

    def reinsert_front(self, data, prompt):
        """Put a previously popped prompt back at position 0 (failed run)."""
        prompt = dict(prompt, status="pending")
        data["prompts"].insert(0, prompt)
        self._resequence(data)

    @staticmethod
    def _resequence(data):
        """Keep ids in queue order (p001 = next in line)."""
        for i, p in enumerate(data.get("prompts", []), 1):
            p["id"] = "p%03d" % i

    def set_schedule(self, data, interval_hours=None, anchor=None, enabled=None):
        """Set interval (and optional 'HH:MM' wall-clock anchor), enable schedule
        and compute the first next_run."""
        sched = data["schedule"]
        if interval_hours is not None:
            sched["interval_hours"] = max(1, min(168, int(interval_hours)))
        if anchor is not None:
            anchor = anchor.strip()
            sched["anchor"] = anchor if _anchor_seconds_past_midnight(anchor) is not None else None
        if enabled is not None:
            sched["enabled"] = bool(enabled)
        sched["last_failure"] = None
        sched["next_run"] = _iso(self.advance_next_run(data, from_now=True))
        return sched

    def advance_next_run(self, data, from_now=False):
        """next_run = max(now, last_run) + interval, honoring the anchor.
        Returns the new next_run as an aware datetime (caller persists)."""
        sched = data["schedule"]
        tz = _tz()
        now = datetime.now(tz)
        last = _parse_iso(sched.get("last_run"))
        base = now if from_now or not last else max(now, last)
        anchor = sched.get("anchor")
        if anchor:
            nxt = _next_anchor_time(base, sched["interval_hours"], anchor)
        else:
            nxt = base + timedelta(hours=sched["interval_hours"])
        sched["next_run"] = _iso(nxt)
        return nxt

    def pause(self, data):
        data["schedule"]["enabled"] = False

    def resume(self, data):
        """Re-enable. An overdue next_run is intentionally left overdue so the
        scheduler fires immediately on its next tick (spec decision #10)."""
        data["schedule"]["enabled"] = True

    def mark_run_started(self, data):
        sched = data["schedule"]
        sched["last_run"] = _iso(datetime.now(_tz()))
        sched["last_result"] = "running"

    def mark_run_succeeded(self, data):
        sched = data["schedule"]
        sched["last_result"] = "success"
        sched["last_failure"] = None
        sched["runs_completed"] = sched.get("runs_completed", 0) + 1
        self.advance_next_run(data)

    def mark_run_failed(self, data, reason):
        sched = data["schedule"]
        sched["last_result"] = "failed"
        sched["last_failure"] = str(reason)[:200]
        # Retry at the next scheduled slot; prompt stays at the queue head.
        self.advance_next_run(data)

    # -------------------------------------------------------------- queries

    def is_due(self, data, now_ts=None):
        """(due?, reason). Scheduler calls this every tick."""
        if not data:
            return False, REASON_NO_SERIES
        sched = data["schedule"]
        if not sched.get("enabled"):
            return False, REASON_PAUSED
        if not any(p.get("status") == "pending" for p in data.get("prompts", [])):
            return False, REASON_EMPTY
        next_run = _parse_iso(sched.get("next_run"))
        if next_run is None:
            # Enabled but never scheduled: fire immediately.
            return True, REASON_OK
        now = datetime.fromtimestamp(now_ts, next_run.tzinfo) if now_ts is not None else datetime.now(next_run.tzinfo)
        if now < next_run:
            return False, REASON_NOT_DUE
        return True, REASON_OK

    def pending_prompts(self, data):
        return [p for p in data.get("prompts", []) if p.get("status") == "pending"]

    def run_position(self, data):
        """(k, n) labels for the run currently in flight. Called AFTER pop_next,
        so: k = runs_completed + 1 (this run's number), n = runs_completed +
        remaining + 1 (the popped prompt + queued + already-produced videos).
        A failed run keeps runs_completed unchanged, so its retry shows the
        same k/n labels. Series files created before runs_completed existed
        default to 0 via .get()."""
        sched = data.get("schedule", {})
        done = sched.get("runs_completed", 0)
        remaining = len(data.get("prompts", []))
        return done + 1, done + remaining + 1

    def is_missed_slot(self, data, grace_seconds=120, now_ts=None):
        """True when next_run passed by more than `grace_seconds` (bot was down).
        Used once per overdue next_run for the catch-up notification."""
        next_run = _parse_iso(data.get("schedule", {}).get("next_run"))
        if next_run is None:
            return False
        now = datetime.fromtimestamp(now_ts, next_run.tzinfo) if now_ts is not None else datetime.now(next_run.tzinfo)
        return now > next_run + timedelta(seconds=grace_seconds)

    def clear_missed_slot(self, data):
        """Consume the missed-slot flag: pull next_run forward to 'now' so the
        catch-up notification is not repeated on subsequent ticks while a
        long generation is still in flight."""
        sched = data.get("schedule", {})
        if sched.get("next_run"):
            sched["next_run"] = _iso(datetime.now(_tz()))
            return True
        return False

    def format_next_run(self, data):
        """Human-readable next_run in the series timezone (or a placeholder)."""
        next_run = _parse_iso(data.get("schedule", {}).get("next_run"))
        if next_run is None:
            return "not scheduled"
        local = next_run.astimezone(_tz())
        delta = local - datetime.now(_tz())
        if delta.total_seconds() < 0:
            return "%s (overdue)" % local.strftime("%b %d, %H:%M")
        hours, rem = divmod(int(delta.total_seconds()), 3600)
        mins = rem // 60
        in_text = "(in %dh %02dm)" % (hours, mins) if hours else "(in %dm)" % mins
        return "%s %s" % (local.strftime("%b %d, %H:%M"), in_text)

    # -------------------------------------------------------------- display

    def queue_text(self, data):
        """Full queue for /series list."""
        prompts = data.get("prompts", [])
        header = "📋 **Series: %s**\n%d/%d prompts queued\n\n" % (
            data["title"], len(prompts), SERIES_MAX_PROMPTS)
        if not prompts:
            return header + "_(empty — add prompts with /series add)_"
        lines = []
        for p in prompts:
            text = p["prompt"][:80] + ("…" if len(p["prompt"]) > 80 else "")
            lines.append("`%s` · %s · %s" % (p["id"], p.get("format", "narration"), text))
        return header + "\n".join(lines)

    def summary_text(self, data):
        """Compact summary for /series status."""
        sched = data.get("schedule", {})
        state = "▶️ enabled" if sched.get("enabled") else "⏸ paused"
        anchor = (" at " + sched["anchor"]) if sched.get("anchor") else ""
        lines = [
            "📺 **Series: %s**" % data["title"],
            "• State: %s (every %dh%s)" % (state, sched.get("interval_hours", 24), anchor),
            "• Prompts pending: %d/%d" % (len(self.pending_prompts(data)), SERIES_MAX_PROMPTS),
            "• Next run: %s" % self.format_next_run(data),
        ]
        if sched.get("last_run"):
            lines.append("• Last run: %s (%s)" % (sched["last_run"][:16].replace("T", " "),
                                                  sched.get("last_result") or "n/a"))
        if sched.get("last_failure"):
            lines.append("• Last failure: `%s`" % sched["last_failure"][:120])
        lines.append("• Timezone: %s" % sched.get("timezone", SERIES_TIMEZONE))
        return "\n".join(lines)
