"""M09 / P6: voice intent routing — 查询/记录/修改/反馈 (plan §15.3).

Deterministic keyword-stage classification over the transcript. The output is
a PREVIEW: nothing is written by this module. Commit paths reuse the diet v2
commands (preview/commit/correct) and observation/constraint endpoints, so
voice and text share one confirmation policy:

- query / record (high confidence)  → may auto-commit with undo
- record with unresolved entities   → preview + confirm (needs_confirmation)
- modify plan / lift constraint     → always confirm (shows the diff)
- feedback (pain etc.)              → records observation; block-level pain
                                      creates a constraint that requires
                                      explicit confirmation to lift later
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VoiceIntent:
    category: str            # query | record | modify | feedback | unknown
    action: Optional[str] = None      # log_meal | log_training | add_observation | ...
    confidence: float = 0.5           # lexical stage confidence
    entities: dict = field(default_factory=dict)
    needs_confirmation: bool = False
    reply_hint_zh: str = ""


_QUERY_PATTERNS = [
    ("今天练什么", "ask_today_training"),
    ("练什么", "ask_today_training"),
    ("吃了多少", "ask_diet_summary"),
    ("多少卡", "ask_diet_summary"),
    ("训练计划", "ask_today_training"),
]

_RECORD_PATTERNS = [
    (r"(吃了|喝了|吃了一个|来了一份?|干饭)", "log_meal"),
    (r"(卧推|深蹲|硬拉|划船|下拉|弯举|推举).{0,12}(组|次)", "log_sets"),
    (r"跑了?\s*[一二两三四五六七八九十百\d]+\s*(公里|千米|km)", "log_cardio"),
]

_FEEDBACK_PATTERNS = [
    (r"(膝盖|肩|肘|腰|手腕|髋)[\u4e00-\u9fff]{0,4}(疼|痛|不舒服|酸)", "report_pain"),
    (r"(这个视频|片段|提示).{0,8}(没用|有用|帮助)", "segment_feedback"),
    (r"(很累|疲劳|没劲|恢复好了|状态好)", "report_condition"),
]

_MODIFY_PATTERNS = [
    (r"(换成|改为|替换成|不要|取消|删掉)", "modify_plan_or_log"),
    (r"(器械|设备).{0,10}((?:被|给).{0,4}占|有人用|没有空|坏了)", "equipment_unavailable"),
]


def classify_intent(transcript: str) -> VoiceIntent:
    text = transcript.strip()
    if not text:
        return VoiceIntent(category="unknown", confidence=0.0, reply_hint_zh="没有听清内容")

    for pattern, action in _MODIFY_PATTERNS:
        if re.search(pattern, text):
            # Plan changes and deletions ALWAYS require confirmation (§15.4).
            return VoiceIntent(
                category="modify", action=action, confidence=0.85,
                entities={"transcript": text}, needs_confirmation=True,
                reply_hint_zh="这会改变计划或记录，请确认",
            )

    for pattern, action in _FEEDBACK_PATTERNS:
        if re.search(pattern, text):
            m = re.search(r"(膝盖|肩|肘|腰|手腕|髋)", text)
            return VoiceIntent(
                category="feedback", action=action, confidence=0.85,
                entities={"transcript": text, **({"body_part": m.group(1)} if m else {})},
                needs_confirmation=action == "report_pain",
                reply_hint_zh="已记录你的反馈" + ("，请注意身体，必要时咨询专业人士" if action == "report_pain" else ""),
            )

    for needle, action in _QUERY_PATTERNS:
        if needle in text:
            return VoiceIntent(
                category="query", action=action, confidence=0.9,
                entities={"transcript": text}, reply_hint_zh="",
            )

    for pattern, action in _RECORD_PATTERNS:
        if re.search(pattern, text):
            sets_match = re.search(r"([一二两三四五六七八九十\d]+)\s*组", text)
            reps_match = re.search(r"[组次]\s*(?:每[组次])?\s*([一二两三四五六七八九十\d]+)\s*次", text)
            meal_match = re.search(r"(?:吃了|喝了一个?)\s*(.{1,20})", text)
            entities = {"transcript": text}
            if sets_match:
                entities["sets"] = _cn_num(sets_match.group(1))
            if reps_match:
                entities["reps"] = _cn_num(reps_match.group(1))
            if meal_match:
                entities["food_description"] = meal_match.group(1).strip().rstrip("。，,；;！!？?. ")
            low_confidence = "大概" in text or "好像" in text or "可能" in text
            return VoiceIntent(
                category="record", action=action,
                confidence=0.5 if low_confidence else 0.85,
                entities=entities, needs_confirmation=low_confidence,
                reply_hint_zh="" if not low_confidence else "不太确定内容，请在确认后保存",
            )

    return VoiceIntent(
        category="unknown", confidence=0.2, entities={"transcript": text},
        needs_confirmation=True, reply_hint_zh="无法识别意图，请换种说法或手动输入",
    )


_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_num(token: str) -> int:
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token in _CN_DIGITS:
        return _CN_DIGITS[token]
    if len(token) == 2 and token[0] == "十":
        return 10 + _CN_DIGITS.get(token[1], 0)
    if len(token) == 2 and token[1] == "十":
        return _CN_DIGITS.get(token[0], 0) * 10
    if len(token) == 3 and token[1] == "十":
        return _CN_DIGITS.get(token[0], 0) * 10 + _CN_DIGITS.get(token[2], 0)
    try:
        return int(token)
    except ValueError:
        return 0
