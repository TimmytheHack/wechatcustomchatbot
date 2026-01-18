from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import Settings
from .db import BotDB
from .giflib import GifLibrary
from .models import PlanRecord
from .policy import (
    allow_gif,
    build_quiet_blocks,
    is_within_quiet_hours,
    next_allowed_time,
    should_schedule_proactive,
)
from .utils import from_ts_utc, local_now, utc_now, utc_ts

LOG = logging.getLogger("bot.scheduler")


def _refresh_daily_counter(settings: Settings, db: BotDB, chat_id: str, current_date: str, daily_date: str | None, daily_count: int) -> int:
    if daily_date != current_date:
        db.update_daily_counter(chat_id, 0, current_date)
        return 0
    return daily_count


def _next_after_cooldown(last_bot_ts_utc: int | None, cooldown_hours: int) -> datetime | None:
    if not last_bot_ts_utc:
        return None
    last_dt = from_ts_utc(last_bot_ts_utc)
    return last_dt + timedelta(hours=cooldown_hours)


def process_due_plans(db: BotDB, settings: Settings, connector, gif_lib: GifLibrary) -> None:
    now_utc = utc_now()
    now_utc_ts = utc_ts(now_utc)
    blocks = build_quiet_blocks(settings)

    due_plans = db.get_due_plans(now_utc_ts)
    if not due_plans:
        return

    for plan in due_plans:
        try:
            _handle_plan(plan, db, settings, connector, gif_lib, blocks, now_utc)
        except Exception as exc:
            LOG.exception("Failed processing plan %s: %s", plan.id, exc)


def _handle_plan(
    plan: PlanRecord,
    db: BotDB,
    settings: Settings,
    connector,
    gif_lib: GifLibrary,
    blocks,
    now_utc: datetime,
) -> None:
    conversation = db.get_conversation(plan.chat_id)
    if not should_schedule_proactive(settings, conversation.chat_type):
        db.mark_plan_canceled(plan.id, utc_ts(now_utc))
        LOG.info("Canceled plan %s due to proactive disabled", plan.id)
        return

    local_now_dt = local_now(settings.timezone)
    current_date = local_now_dt.date().isoformat()
    daily_count = _refresh_daily_counter(
        settings, db, plan.chat_id, current_date, conversation.daily_date, conversation.daily_count
    )
    if daily_count >= settings.proactive.max_per_day:
        db.mark_plan_canceled(plan.id, utc_ts(now_utc))
        LOG.info("Canceled plan %s due to max per day", plan.id)
        return

    if is_within_quiet_hours(local_now_dt, blocks):
        next_time = next_allowed_time(local_now_dt, blocks)
        db.reschedule_plan(plan.id, int(next_time.astimezone(timezone.utc).timestamp()), utc_ts(now_utc))
        LOG.info("Rescheduled plan %s due to quiet hours", plan.id)
        return

    cooldown_until = _next_after_cooldown(conversation.last_bot_ts_utc, settings.proactive.cooldown_hours)
    if cooldown_until and now_utc < cooldown_until:
        db.reschedule_plan(plan.id, utc_ts(cooldown_until), utc_ts(now_utc))
        LOG.info("Rescheduled plan %s due to cooldown", plan.id)
        return

    connector.send_text(plan.chat_id, plan.text)
    db.add_message(plan.chat_id, "bot", "bot", utc_ts(now_utc), plan.text, "text")

    if plan.gif_tag and allow_gif(settings.gif_rate):
        gif_path = gif_lib.pick_gif(plan.gif_tag)
        if gif_path:
            connector.send_gif(plan.chat_id, str(gif_path))
            db.add_message(plan.chat_id, "bot", "bot", utc_ts(now_utc), str(gif_path), "gif")

    db.mark_plan_sent(plan.id, utc_ts(now_utc))
    db.update_last_bot_ts(plan.chat_id, utc_ts(now_utc))
    db.update_daily_counter(plan.chat_id, daily_count + 1, current_date)
