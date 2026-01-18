from __future__ import annotations

from zoneinfo import ZoneInfo

from .config import Settings
from .llm import LLMContext
from .models import ConversationState, MessageRecord, PlanRecord
from .utils import clamp_text, from_ts_utc, local_now


def build_llm_context(
    settings: Settings,
    conversation: ConversationState,
    incoming_text: str,
    recent_messages: list[MessageRecord],
    pending_plans: list[PlanRecord],
) -> LLMContext:
    local_dt = local_now(settings.timezone)
    return LLMContext(
        incoming_text=incoming_text,
        local_time=local_dt.isoformat(),
        timezone=settings.timezone,
        settings={
            "tone": settings.tone,
            "gif_rate": settings.gif_rate,
            "proactive": settings.proactive.model_dump(),
            "quiet_hours": [qh.model_dump() for qh in settings.quiet_hours],
            "groups": settings.groups.model_dump(),
        },
        summary=conversation.summary,
        recent_messages=[
            {"role": msg.role, "content": msg.content, "ts_utc": msg.ts_utc, "msg_type": msg.msg_type}
            for msg in recent_messages
        ],
        pending_plans=[
            {
                "send_at": from_ts_utc(plan.send_at_utc).astimezone(ZoneInfo(settings.timezone)).isoformat(),
                "text": plan.text,
                "gif_tag": plan.gif_tag,
                "status": plan.status,
                "reason": plan.reason,
                "confidence": plan.confidence,
            }
            for plan in pending_plans
        ],
        counters={
            "last_bot_ts_utc": conversation.last_bot_ts_utc,
            "daily_count": conversation.daily_count,
            "daily_date": conversation.daily_date,
        },
    )


def update_summary(
    previous_summary: str,
    recent_messages: list[MessageRecord],
    max_chars: int,
) -> str:
    lines = []
    for msg in recent_messages[-6:]:
        role = "U" if msg.role == "user" else "B"
        content = clamp_text(msg.content.replace("\n", " "), 160)
        lines.append(f"{role}: {content}")

    base = previous_summary.strip()
    if base:
        base = clamp_text(base, max_chars // 2)
        combined = f"{base}\nRecent:\n" + "\n".join(lines)
    else:
        combined = "Recent:\n" + "\n".join(lines)

    return clamp_text(combined, max_chars)
