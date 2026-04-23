"""
Shared DeepSeek client. All DeepSeek calls should route through here so we have
one place to tweak model, timeouts, and error handling.
"""

import os

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI

load_dotenv()

DEEPSEEK_MODEL = "deepseek-reasoner"
# deepseek-reasoner does NOT support response_format=json_object. Use
# deepseek-chat for any structured-output call (JSON-mode / function-style).
DEEPSEEK_CHAT_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def get_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY is not configured")
    return OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        http_client=httpx.Client(trust_env=False),
    )
