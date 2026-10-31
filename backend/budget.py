"""Cost guard for the public demo (Meta's Spend Limit is only an alert).

- MAX_RUNS_PER_DAY live runs in total (from .env), MAX_RUNS_PER_IP per visitor per day
- uploads: at most 25 MB and 90 s of video
Sample replays cost nothing and are never counted. State lives in runs/_budget.json.
"""
import json
import os
import threading
from datetime import date
from pathlib import Path

from backend.media import MediaError, probe

MAX_BYTES = 25 * 1024 * 1024
MAX_SECONDS = 90
STATE = Path(__file__).resolve().parent.parent / "runs" / "_budget.json"
_lock = threading.Lock()


class BudgetError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _limits() -> tuple[int, int]:
    return int(os.getenv("MAX_RUNS_PER_DAY", "30")), int(os.getenv("MAX_RUNS_PER_IP", "3"))


def _load() -> dict:
    today = date.today().isoformat()
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    return state if state.get("date") == today else {"date": today, "total": 0, "per_ip": {}}


def check_video(path: Path) -> float:
    """Raises BudgetError unless the file is a video of at most MAX_SECONDS. Returns its length."""
    if path.stat().st_size > MAX_BYTES:
        raise BudgetError(413, f"Upload is over {MAX_BYTES // 2**20} MB.")
    try:
        seconds = probe(path)["duration"]
    except MediaError:
        raise BudgetError(400, "That file isn't a video we can read.") from None
    if seconds > MAX_SECONDS:
        raise BudgetError(413, f"Video is {seconds:.0f} s; the limit is {MAX_SECONDS} s.")
    return seconds


def charge(ip: str) -> dict:
    """Count one live run for ip, or raise BudgetError(429) if a daily limit is reached."""
    per_day, per_ip = _limits()
    with _lock:
        state = _load()
        if state["total"] >= per_day:
            raise BudgetError(429, "Today's live runs are used up. Try a sample bug instead (free).")
        if state["per_ip"].get(ip, 0) >= per_ip:
            raise BudgetError(429, f"You've used your {per_ip} live runs for today. Samples are free.")
        state["total"] += 1
        state["per_ip"][ip] = state["per_ip"].get(ip, 0) + 1
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(state))
    return {"left_today": per_day - state["total"], "left_for_you": per_ip - state["per_ip"][ip]}


def status(ip: str) -> dict:
    per_day, per_ip = _limits()
    state = _load()
    return {"left_today": max(0, per_day - state["total"]),
            "left_for_you": max(0, per_ip - state["per_ip"].get(ip, 0)),
            "max_mb": MAX_BYTES // 2**20, "max_seconds": MAX_SECONDS}
