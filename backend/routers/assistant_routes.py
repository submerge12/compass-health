from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import assistant_tools, deepseek, llm_quota


router = APIRouter(prefix="/api/assistant", tags=["assistant"])
log = logging.getLogger("compass.app")


class AssistantMessage(BaseModel):
    role: str = Field(..., min_length=1, max_length=16)
    content: str = Field(..., max_length=8000)


class AssistantChatRequest(BaseModel):
    messages: list[AssistantMessage] = Field(..., min_length=1, max_length=20)
    context_page: Optional[str] = Field(default=None, max_length=80)


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_user_targets",
            "description": "Return the user's BMR/TDEE and daily macro targets from the local calorie engine.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_food_library",
            "description": "Resolve a natural-language food name to candidate Compass food-library slugs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "execution_bucket": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_foods",
            "description": "Calculate macros and tracked micronutrients for food-library slugs and grams.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "slug": {"type": "string"},
                                "grams": {"type": "number", "exclusiveMinimum": 0},
                            },
                            "required": ["slug", "grams"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["ingredients"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "audit_food_set",
            "description": "Run the user's closed food-library nutrition audit and return compact gaps/suggestions.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_replacements",
            "description": "Return same-slot replacement foods for a Compass food-library slug.",
            "parameters": {
                "type": "object",
                "properties": {"slug": {"type": "string"}},
                "required": ["slug"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_fat_loss_food",
            "description": "Evaluate whether a food or dish the user wants to eat can fit a fat-loss day. Returns local matches, targets, risk flags, and a traffic-light hint; the assistant should make the final judgement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Food or dish name, e.g. 洋葱炒牛肉, 火锅, 奶茶"},
                    "grams": {"type": "number", "exclusiveMinimum": 0, "description": "Optional estimated edible grams"},
                    "meal_type": {"type": "string", "description": "Optional breakfast/lunch/dinner/snack"},
                    "context": {"type": "string", "description": "Optional user context such as craving, restaurant, planned meal, or cooking method"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_day_plan",
            "description": "Preview generated slots for one day without writing meal-plan entries.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; omit for today"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_week_overview",
            "description": "Return a compact, read-only 7-day planning overview.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nutrition_memory",
            "description": "Return custom nutrition labels, aliases, and free-text notes saved for the user.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fixed_meals",
            "description": "Return the user's current fixed meals.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_action",
            "description": "Create a pending user-confirmation action. Use this for every database mutation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": [
                            "save_nutrition_memory",
                            "upsert_fixed_breakfast",
                            "apply_day_plan_slot",
                        ],
                    },
                    "summary": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["action_type", "summary", "payload"],
                "additionalProperties": False,
            },
        },
    },
]


def _system_prompt(user: models.User, context_page: str | None) -> str:
    lang = getattr(user, "language", "zh") or "zh"
    return f"""
You are the Compass Health nutrition assistant.
User language preference: {lang}. Current app page: {context_page or "unknown"}.

Rules:
- All nutrition calculations MUST use tools. Never invent calories, macros, micronutrients, or targets.
- Before changing meal plans, fixed meals, or nutrition memory, call propose_action and wait for confirmation.
- When the user mentions a food by name, call search_food_library before calculating or proposing with that food.
- When the user asks whether something they want to eat is suitable for fat loss, call evaluate_fat_loss_food before answering.
- If a food is not in the library, explain the closest slug approximation.
- For fat-loss suitability answers, use a traffic light: green = usually fine, yellow = can fit with portion/method control, red = best limited or modified. Always include a practical portion and one adjustment.
- Do not recommend extremely low-calorie (<1200 kcal), extremely low-carb (<100g), or unsupported supplement plans.
- If the user has no BMR profile, tell them to complete body goal setup first and do not guess targets.
- Keep replies concise, practical, and in the user's language.
- Action summaries and proposed recipe/meal names must be in the user's language.
""".strip()


def _quota_detail(exc: llm_quota.LLMQuotaExceeded) -> dict:
    return {
        "error": "quota_exhausted",
        "kind": llm_quota.ASSISTANT_CHAT,
        "message_zh": "本周 AI 营养助手额度已用完，请稍后再试。",
        "message_en": "The weekly AI nutrition assistant quota is exhausted.",
        "next_refresh_at": exc.next_refresh_at.isoformat()
        if getattr(exc, "next_refresh_at", None) else None,
    }


def _message_dict(message: AssistantMessage) -> dict:
    role = message.role.strip().lower()
    if role not in {"user", "assistant"}:
        role = "user"
    return {"role": role, "content": message.content}


def _assistant_message_dict(msg: Any) -> dict:
    out = {"role": "assistant", "content": getattr(msg, "content", None) or ""}
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in tool_calls
        ]
    return out


def _call_deepseek_with_quota(db: Session, user_id: int, client: Any, messages: list[dict]) -> Any:
    quota_call_id: int | None = None
    try:
        quota_usage = llm_quota.check_and_consume(db, user_id, llm_quota.ASSISTANT_CHAT)
        quota_call_id = quota_usage.get("call_log_id")
    except llm_quota.LLMQuotaExceeded as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=_quota_detail(exc))

    try:
        resp = client.chat.completions.create(
            model=deepseek.DEEPSEEK_CHAT_MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            max_tokens=1000,
        )
        db.commit()
        return resp
    except HTTPException:
        llm_quota.refund_call(
            db,
            quota_call_id,
            user_id=user_id,
            kind=llm_quota.ASSISTANT_CHAT,
        )
        db.commit()
        raise
    except Exception as exc:
        llm_quota.refund_call(
            db,
            quota_call_id,
            user_id=user_id,
            kind=llm_quota.ASSISTANT_CHAT,
        )
        db.commit()
        log.exception(
            "assistant deepseek call failed",
            extra={"event": "assistant_chat_failed", "exc_class": exc.__class__.__name__},
        )
        raise HTTPException(status_code=502, detail="Assistant model call failed")


def _tool_args(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Assistant tool arguments were invalid JSON: {exc}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Assistant tool arguments must be an object")
    return parsed


@router.get("/memory")
def get_memory(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return assistant_tools.get_nutrition_memory(db, current_user.id)


@router.post("/chat")
def chat(
    body: AssistantChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not current_user.bmr_profile:
        return {
            "reply": (
                "请先完成身体目标设置（BMR/身高体重/目标）。完成后我才能按你的目标计算蛋白、热量和微量营养。"
                if (current_user.language or "zh") != "en"
                else "Please complete body goal setup first. Then I can calculate targets and nutrition gaps."
            ),
            "tool_results": [],
            "proposed_actions": [],
        }

    client = deepseek.get_client()
    messages: list[dict] = [{"role": "system", "content": _system_prompt(current_user, body.context_page)}]
    messages.extend(_message_dict(m) for m in body.messages[-12:])

    tool_results: list[dict] = []
    proposed_actions_by_id: dict[int, dict] = {}

    for _ in range(5):
        resp = _call_deepseek_with_quota(db, current_user.id, client, messages)
        choice = resp.choices[0]
        msg = choice.message
        messages.append(_assistant_message_dict(msg))
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            db.commit()
            return {
                "reply": msg.content or "",
                "tool_results": tool_results,
                "proposed_actions": list(proposed_actions_by_id.values()),
            }

        for call in tool_calls:
            name = call.function.name
            args = _tool_args(call.function.arguments or "{}")
            result = assistant_tools.call_tool(db, current_user, name, args)
            tool_record = {
                "tool": name,
                "arguments": args,
                "result": result,
            }
            tool_results.append(tool_record)
            action = result.get("proposed_action") if isinstance(result, dict) else None
            if isinstance(action, dict) and action.get("id"):
                proposed_actions_by_id[int(action["id"])] = action
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    db.commit()
    return {
        "reply": "我已经完成了工具检查，但这轮需要你确认下一步。请看下面的结果卡片。",
        "tool_results": tool_results,
        "proposed_actions": list(proposed_actions_by_id.values()),
    }


@router.post("/actions/{action_id}/confirm")
def confirm_action(
    action_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        result = assistant_tools.confirm_action(db, current_user, action_id)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        log.exception(
            "assistant action execution failed",
            extra={"event": "assistant_action_failed", "action_id": action_id, "exc_class": exc.__class__.__name__},
        )
        raise HTTPException(status_code=500, detail="Assistant action execution failed")
