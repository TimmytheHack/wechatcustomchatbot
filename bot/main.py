from __future__ import annotations

import importlib
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Header, HTTPException, Request

from .config import EnvConfig, Settings, SettingsError, load_env, load_settings
from .connector import ConnectorAdapter
from .db import BotDB
from .giflib import GifLibrary
from .llm import LLMClient
from .models import InboundEvent
from .planner import build_llm_context, update_summary
from .policy import (
    allow_gif,
    build_quiet_blocks,
    can_use_plan,
    parse_send_at,
    sanitize_schedule_time,
    should_reply_in_group,
    should_schedule_proactive,
)
from .scheduler import process_due_plans
from .utils import local_now, utc_now, utc_ts

LOG = logging.getLogger("bot")


@dataclass
class AppState:
    settings: Settings
    env: EnvConfig
    db: BotDB
    gif_lib: GifLibrary
    connector: ConnectorAdapter
    llm: LLMClient
    scheduler: BackgroundScheduler


def _load_connector(path: str) -> ConnectorAdapter:
    if ":" not in path:
        raise SettingsError("runtime.connector must be in module:Class format")
    module_name, class_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise SettingsError(f"Connector class not found: {path}")
    return cls()


def _refresh_daily_counter(settings: Settings, conversation, db: BotDB) -> tuple[int, str]:
    local_date = local_now(settings.timezone).date().isoformat()
    if conversation.daily_date != local_date:
        db.update_daily_counter(conversation.chat_id, 0, local_date)
        return 0, local_date
    return conversation.daily_count, conversation.daily_date or local_date


def _apply_planning(
    state: AppState,
    event: InboundEvent,
    action: str,
    plan_item,
    pending_count: int,
    conversation,
) -> None:
    now_utc_ts = utc_ts(utc_now())
    settings = state.settings

    if action == "cancel_all":
        state.db.cancel_all_plans(event.chat_id, now_utc_ts)
        return

    if not plan_item:
        if action == "replace_all":
            state.db.cancel_all_plans(event.chat_id, now_utc_ts)
        return

    if not should_schedule_proactive(settings, event.chat_type):
        return

    if not can_use_plan(plan_item, settings):
        return

    if conversation.daily_count >= settings.proactive.max_per_day:
        return

    send_at_local = parse_send_at(plan_item.send_at, settings.timezone)
    if send_at_local is None:
        return

    blocks = build_quiet_blocks(settings)
    local_now_dt = local_now(settings.timezone)
    if conversation.last_bot_ts_utc:
        cooldown_until = datetime.fromtimestamp(conversation.last_bot_ts_utc, tz=timezone.utc) + timedelta(
            hours=settings.proactive.cooldown_hours
        )
        cooldown_until_local = cooldown_until.astimezone(local_now_dt.tzinfo)
        if send_at_local < cooldown_until_local:
            send_at_local = cooldown_until_local
    send_at_local = sanitize_schedule_time(send_at_local, local_now_dt, blocks)
    send_at_utc = int(send_at_local.astimezone(timezone.utc).timestamp())

    plan_tuple = (
        send_at_utc,
        plan_item.text.strip() or "(empty)",
        plan_item.gif_tag,
        plan_item.reason,
        plan_item.confidence,
    )

    if action == "replace_all":
        state.db.replace_plans(event.chat_id, [plan_tuple], now_utc_ts)
        return

    if action == "append":
        if pending_count >= settings.proactive.max_pending_per_chat:
            return
        state.db.append_plans(event.chat_id, [plan_tuple], now_utc_ts)


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    env = load_env()
    config_path = os.getenv("BOT_CONFIG", "config.yaml")
    settings = load_settings(config_path)

    db = BotDB(settings.runtime.db_path)
    gif_lib = GifLibrary(settings.gif_folder)
    connector = _load_connector(settings.runtime.connector)
    llm = LLMClient(env, settings)

    scheduler = BackgroundScheduler()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler.add_job(
            process_due_plans,
            "interval",
            seconds=settings.runtime.scheduler_interval_seconds,
            args=[db, settings, connector, gif_lib],
        )
        scheduler.start()
        LOG.info("Scheduler started")
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            db.close()

    app = FastAPI(lifespan=lifespan)
    app.state.ctx = AppState(
        settings=settings,
        env=env,
        db=db,
        gif_lib=gif_lib,
        connector=connector,
        llm=llm,
        scheduler=scheduler,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true", "version": "0.1.0"}

    @app.post("/wechat/event")
    def wechat_event(
        event: InboundEvent,
        request: Request,
        x_bot_secret: str | None = Header(default=None, alias="X-BOT-SECRET"),
    ) -> dict[str, bool | str]:
        state: AppState = request.app.state.ctx
        if x_bot_secret != state.settings.security.shared_secret:
            raise HTTPException(status_code=401, detail="Unauthorized")

        conversation = state.db.ensure_conversation(event.chat_id, event.chat_type)
        state.db.add_message(
            event.chat_id,
            event.sender_id,
            "user",
            event.timestamp,
            event.text,
            "text",
        )
        state.db.update_last_user_ts(event.chat_id, event.timestamp)

        daily_count, daily_date = _refresh_daily_counter(state.settings, conversation, state.db)
        conversation = replace(conversation, daily_count=daily_count, daily_date=daily_date)

        if event.chat_type == "group" and not should_reply_in_group(event.is_mention, state.settings):
            recent_messages = state.db.get_recent_messages(event.chat_id, state.settings.memory.recent_messages)
            summary = update_summary(conversation.summary, recent_messages, state.settings.memory.summary_max_chars)
            state.db.update_conversation_summary(event.chat_id, summary)
            return {"ok": True, "skipped": "group_not_mentioned"}

        recent_messages = state.db.get_recent_messages(event.chat_id, state.settings.memory.recent_messages)
        pending_plans = state.db.get_pending_plans(event.chat_id)
        llm_context = build_llm_context(state.settings, conversation, event.text, recent_messages, pending_plans)
        llm_output = state.llm.generate_response(llm_context)

        reply_text = llm_output.reply.text.strip() or "Got it."
        state.connector.send_text(event.chat_id, reply_text)
        now_utc = utc_now()
        now_utc_ts = utc_ts(now_utc)
        state.db.add_message(event.chat_id, "bot", "bot", now_utc_ts, reply_text, "text")
        state.db.update_last_bot_ts(event.chat_id, now_utc_ts)
        conversation = replace(conversation, last_bot_ts_utc=now_utc_ts)

        if llm_output.reply.send_gif and allow_gif(state.settings.gif_rate):
            gif_tag = llm_output.reply.gif_tag or ""
            gif_path = state.gif_lib.pick_gif(gif_tag)
            if gif_path:
                state.connector.send_gif(event.chat_id, str(gif_path))
                state.db.add_message(event.chat_id, "bot", "bot", now_utc_ts, str(gif_path), "gif")

        planning = llm_output.planning
        plan_item = planning.items[0] if planning.items else None
        pending_count = len(pending_plans)
        _apply_planning(state, event, planning.action, plan_item, pending_count, conversation)

        recent_messages = state.db.get_recent_messages(event.chat_id, state.settings.memory.recent_messages)
        summary = update_summary(conversation.summary, recent_messages, state.settings.memory.summary_max_chars)
        state.db.update_conversation_summary(event.chat_id, summary)

        return {"ok": True}

    return app


def run() -> None:
    import uvicorn

    app = create_app()
    settings = app.state.ctx.settings
    uvicorn.run(app, host=settings.runtime.host, port=settings.runtime.port, log_level="info")


if __name__ == "__main__":
    run()
