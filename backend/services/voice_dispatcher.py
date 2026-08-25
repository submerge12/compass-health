"""WO-HS-08 / M22: voice dispatcher — routes each confirmed intent to its
domain action, returning a structured result the UI renders per category.

Covers the full instruction matrix (plan §十一):
- query 今天练什么        -> cycle engine answer, no write
- record meal            -> diet v2 commit (idempotent, undoable)
- record sets            -> active session/exercise set log
- record cardio          -> activity log
- modify / substitute    -> diff/propose (confirmation handled by caller)
- feedback pain          -> pain command (observation + constraint)
- segment feedback       -> media helpfulness
- unknown                -> refuses any write

Meal time expressions (早餐/中午/下午/晚餐/昨晚) map to explicit meal types;
only when absent do we infer from the current clock.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Optional

from services.domain_identity import external_id_for_user
from services.health_domain_client import HealthDomainClient
from services.voice_intent import VoiceIntent


class DispatchError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


_MEAL_TIME_PATTERNS: list[tuple[str, str]] = [
    (r"早餐|早上|早晨", "breakfast"),
    (r"中午|午餐|午饭", "lunch"),
    (r"下午(?!茶)|加餐|下午茶", "snack"),
    (r"晚上|晚餐|晚饭|夜里", "dinner"),
    (r"昨晚", "dinner"),
]


def resolve_meal_type(transcript: str, now: Optional[datetime] = None) -> str:
    for pattern, meal in _MEAL_TIME_PATTERNS:
        if re.search(pattern, transcript):
            return meal
    hour = (now or datetime.now()).hour
    if 5 <= hour < 11:
        return "breakfast"
    if 11 <= hour < 15:
        return "lunch"
    if 15 <= hour < 18:
        return "snack"
    return "dinner"


def _extract_food_description(intent: VoiceIntent) -> Optional[str]:
    raw = intent.entities.get("food_description")
    if not raw:
        return None
    return re.sub(r"[。．.,;；!！?？\s]+$", "", str(raw)).strip() or None


async def dispatch(
    intent: VoiceIntent,
    *,
    user_id: int,
    token_actor: str,
    date: str,
    idempotency_key: str,
    client: HealthDomainClient,
    chosen_items: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Execute one confirmed intent against the domain API."""
    external_id = external_id_for_user(user_id)

    async def call(method: str, path: str, body: Any = None) -> Any:
        response = await client.request(
            method, path,
            external_user_id=external_id,
            params={"date": date} if method == "GET" and path.startswith("/api/v1/daily-state") else None,
            json_body=body,
            actor=token_actor,
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("error")):
            raise DispatchError(
                response.status_code if response.status_code >= 400 else 502,
                str(payload.get("error", "domain_error")) if isinstance(payload, dict) else "domain_error",
                payload.get("detail") if isinstance(payload, dict) else "domain call failed",
            )
        return payload

    # ── query ──
    if intent.category == "query":
        state = await call("GET", "/api/v1/daily-state")
        training = state.get("training") or {}
        constraints = state.get("activeConstraints") or []
        blocked = [c for c in constraints if c.get("severity") == "block"]
        parts: list[str] = []
        if blocked:
            parts.append("当前有疼痛限制，建议休息或避开受限动作")
        elif training.get("sessionId"):
            parts.append(f"今天已开始训练（状态 {training.get('status')}）")
        else:
            rec = training.get("recommendation") or "按循环继续"
            parts.append(f"建议训练日：{rec}")
        parts.append(f"今日已完成训练组数 {training.get('completedSets', 0)}")
        return {"status": "answered", "answer_zh": "；".join(parts), "daily_state": state}

    # ── record: meal ──
    if intent.action == "log_meal":
        description = _extract_food_description(intent)
        if not description:
            raise DispatchError(422, "missing_food_entity", "未能从语句中识别食物，请补充说明")
        meal_type = resolve_meal_type(str(intent.entities.get("transcript", "")))
        body: dict[str, Any] = {
            "date": date,
            "mealType": meal_type,
            "description": description,
            "idempotencyKey": idempotency_key,
        }
        if chosen_items:
            body["items"] = [
                {"slug": str(c["slug"]), "grams": float(c.get("grams", 100))}
                for c in chosen_items if c.get("slug")
            ]
        result = await call("POST", "/api/v1/diet/logs:commit", body)
        if isinstance(result, dict) and result.get("status") == "needs_confirmation":
            return {
                "status": "needs_confirmation",
                "needs_confirmation": result.get("details", {}).get("needsConfirmation", []),
                "unmatched": result.get("details", {}).get("unmatched", []),
            }
        log = result.get("log", {})
        return {"status": "committed", "kind": "meal",
                "log_id": log.get("id"), "kcal": log.get("caloriesKcal"),
                "meal_type": meal_type}

    # ── record: training sets -> requires an active session ──
    if intent.action == "log_sets":
        sets_count = int(intent.entities.get("sets", 0))
        reps = int(intent.entities.get("reps", 0)) or None
        exercise_hint = intent.entities.get("exercise")
        daily_state = await call("GET", "/api/v1/daily-state")
        training = daily_state.get("training") or {}
        session_id = training.get("sessionId")
        if not session_id or training.get("status") != "in_progress":
            raise DispatchError(
                409, "no_active_session",
                "当前没有进行中的训练；请先在训练页准备并开始本次训练",
            )
        # Find matching exercise by hint within the session.
        read_back = await call("GET", f"/api/v1/training/sessions?id={session_id}")
        exercises = (read_back.get("exercisesWithSets") or [])
        target = None
        if exercise_hint:
            hint = str(exercise_hint).lower()
            for entry in exercises:
                slug = str(entry.get("exercise", {}).get("exerciseSlug", "")).lower()
                if hint.split("_")[0] in slug or slug in hint:
                    target = entry
                    break
        if target is None and len(exercises) == 1:
            target = exercises[0]
        if target is None:
            raise DispatchError(422, "ambiguous_exercise",
                                "无法确定是哪个动作；请在训练页逐组记录或说得更具体")
        done_sets = len(target.get("sets") or [])
        next_set_number = int(target["exercise"].get("targetSets") or 0) > done_sets and done_sets + 1 or done_sets + 1
        logged = await call("POST", "/api/v1/training/sets", {
            "sessionId": session_id,
            "sessionExerciseId": target["exercise"]["id"],
            "setNumber": next_set_number,
            "reps": reps,
            "source": "voice",
            "idempotencyKey": idempotency_key,
        })
        return {"status": "committed", "kind": "training_set",
                "session_id": session_id,
                "exercise": target["exercise"].get("exerciseSlug"),
                "set_number": logged.get("log", {}).get("setNumber", next_set_number),
                "reps": reps}

    # ── record: cardio -> activity ──
    if intent.action == "log_cardio":
        transcript = str(intent.entities.get("transcript", ""))
        km_match = re.search(r"([0-9]+(?:\.[0-9]+)?|[一二两三四五六七八九十]+)\s*(?:公里|千米|km)", transcript)
        minutes_match = re.search(r"([0-9]+|[一二两三四五六七八九十]+)\s*分钟", transcript)
        activity_type = "running"
        duration = 30
        notes = transcript[:200]
        if km_match:
            notes = f"{km_match.group(1)} 公里 · {notes}"
        if minutes_match:
            from services.voice_intent import _cn_num  # reuse CN numeral parsing
            duration = _cn_num(minutes_match.group(1))
        logged = await call("POST", "/api/v1/activities", {
            "activity_type": activity_type,
            "duration_minutes": duration,
            "notes": notes,
        })
        return {"status": "committed", "kind": "activity",
                "activity": logged.get("logs", [{}])[-1] if logged.get("logs") else None,
                "total_minutes": logged.get("total_minutes")}

    # ── substitute (equipment occupied etc.) -> propose only ──
    if intent.action == "equipment_unavailable":
        daily_state = await call("GET", "/api/v1/daily-state")
        session_id = (daily_state.get("training") or {}).get("sessionId")
        if not session_id:
            raise DispatchError(409, "no_active_session",
                                "当前没有进行中的训练，无需替代动作")
        read_back = await call("GET", f"/api/v1/training/sessions?id={session_id}")
        pending = [e for e in (read_back.get("exercisesWithSets") or [])
                   if e.get("exercise", {}).get("status") == "pending"]
        if not pending:
            return {"status": "answered", "answer_zh": "所有动作都已完成，无需替代"}
        first = pending[0]["exercise"]
        proposal = await call("POST", "/api/v1/training/substitutions:propose", {
            "sessionId": session_id,
            "sessionExerciseId": first["id"],
        })
        return {"status": "substitution_proposed",
                "original": proposal.get("originalSlug"),
                "remaining_sets": proposal.get("remainingSets"),
                "volume_note": proposal.get("volumeNote"),
                "candidates": proposal.get("candidates", [])}

    # ── feedback: pain -> pain command ──
    if intent.action == "report_pain":
        body_part = intent.entities.get("body_part")
        severity_hint = ("worsening" if "加重" in str(intent.entities.get("transcript", ""))
                         else "unknown")
        result = await call("POST", "/api/v1/health/pain", {
            "observedOn": date,
            "bodyPart": body_part,
            "severityHint": severity_hint,
            "description": str(intent.entities.get("transcript", "")),
        })
        return {"status": "committed", "kind": "pain",
                "constraint_severity": result.get("severity"),
                "guidance_zh": result.get("guidance")}

    # ── generic plan modification -> never auto-applied from voice ──
    if intent.category == "modify":
        return {"status": "needs_ui_diff",
                "hint": "修改类操作请在计划页确认差异后应用"}

    raise DispatchError(422, "unsupported_intent", "该意图暂不支持语音执行")
