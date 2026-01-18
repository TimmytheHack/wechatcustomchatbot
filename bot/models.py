from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


class InboundEvent(BaseModel):
    chat_id: str
    chat_type: Literal["direct", "group"]
    sender_id: str
    timestamp: int
    text: str
    is_mention: bool = False


class LLMReply(BaseModel):
    text: str
    send_gif: bool = False
    gif_tag: str | None = None


class LLMPlanItem(BaseModel):
    send_at: str
    text: str
    gif_tag: str | None = None
    reason: str = ""
    confidence: float = 0.0


class LLMPlanning(BaseModel):
    action: Literal["none", "cancel_all", "replace_all", "append"] = "none"
    items: list[LLMPlanItem] = Field(default_factory=list)


class LLMMemoryUpdate(BaseModel):
    type: Literal["preference", "fact", "none"] = "none"
    key: str = ""
    value: str = ""


class LLMOutput(BaseModel):
    reply: LLMReply
    planning: LLMPlanning
    memory_updates: list[LLMMemoryUpdate] = Field(default_factory=list)


@dataclass(frozen=True)
class MessageRecord:
    role: str
    content: str
    ts_utc: int
    msg_type: str
    sender_id: str


@dataclass(frozen=True)
class ConversationState:
    chat_id: str
    chat_type: str
    summary: str
    last_user_ts_utc: int | None
    last_bot_ts_utc: int | None
    daily_count: int
    daily_date: str | None


@dataclass(frozen=True)
class PlanRecord:
    id: int
    chat_id: str
    send_at_utc: int
    text: str
    gif_tag: str | None
    status: str
    reason: str
    confidence: float
