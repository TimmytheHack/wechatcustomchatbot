from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from .config import Settings
from .models import LLMPlanItem
from .utils import ensure_min_delay, parse_hhmm

LOG = logging.getLogger("bot.policy")

GIF_RATE_PROB = {
    "off": 0.0,
    "low": 0.2,
    "medium": 0.5,
    "high": 0.8,
}

MIN_SCHEDULE_DELAY = timedelta(seconds=60)


@dataclass(frozen=True)
class QuietBlock:
    start: time
    end: time


def build_quiet_blocks(settings: Settings) -> list[QuietBlock]:
    blocks = []
    for block in settings.quiet_hours:
        blocks.append(QuietBlock(start=parse_hhmm(block.start), end=parse_hhmm(block.end)))
    return blocks


def is_within_quiet_hours(local_dt: datetime, blocks: Iterable[QuietBlock]) -> bool:
    local_time = local_dt.timetz().replace(tzinfo=None)
    for block in blocks:
        if block.start <= block.end:
            if block.start <= local_time < block.end:
                return True
        else:
            if local_time >= block.start or local_time < block.end:
                return True
    return False


def next_allowed_time(local_dt: datetime, blocks: Iterable[QuietBlock]) -> datetime:
    candidate = local_dt
    for _ in range(5):
        moved = False
        local_time = candidate.timetz().replace(tzinfo=None)
        for block in blocks:
            if block.start <= block.end:
                if block.start <= local_time < block.end:
                    candidate = candidate.replace(hour=block.end.hour, minute=block.end.minute, second=0, microsecond=0)
                    moved = True
                    break
            else:
                if local_time >= block.start:
                    candidate = (candidate + timedelta(days=1)).replace(
                        hour=block.end.hour, minute=block.end.minute, second=0, microsecond=0
                    )
                    moved = True
                    break
                if local_time < block.end:
                    candidate = candidate.replace(hour=block.end.hour, minute=block.end.minute, second=0, microsecond=0)
                    moved = True
                    break
        if not moved:
            break
    return candidate


def allow_gif(gif_rate: str) -> bool:
    prob = GIF_RATE_PROB.get(gif_rate, 0.0)
    if prob <= 0.0:
        return False
    return random.random() < prob


def should_reply_in_group(is_mention: bool, settings: Settings) -> bool:
    if not settings.groups.reply_only_when_mentioned:
        return True
    return is_mention


def parse_send_at(send_at: str, tz_name: str) -> datetime | None:
    try:
        normalized = send_at.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if dt.tzinfo is None:
        LOG.warning("LLM send_at missing timezone, assuming %s", tz_name)
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def sanitize_schedule_time(send_at: datetime, local_now: datetime, blocks: Iterable[QuietBlock]) -> datetime:
    send_at = ensure_min_delay(send_at, local_now, MIN_SCHEDULE_DELAY)
    if is_within_quiet_hours(send_at, blocks):
        send_at = next_allowed_time(send_at, blocks)
    return send_at


def should_schedule_proactive(settings: Settings, chat_type: str) -> bool:
    if not settings.proactive.enabled:
        return False
    if chat_type == "group" and not settings.groups.allow_proactive:
        return False
    return True


def can_use_plan(item: LLMPlanItem, settings: Settings) -> bool:
    return item.confidence >= settings.proactive.min_confidence
