"""Thin wrapper around the Google Gemini Interactions API."""

import logging

from google import genai

logger = logging.getLogger(__name__)


def create_client(api_key):
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set. Copy .env.example to .env and fill it in.")

    return genai.Client(api_key=api_key)


def user_message(text):
    return {"type": "user_input", "content": [{"type": "text", "text": text}]}


def model_message(text):
    return {"type": "model_output", "text": text}


async def generate(client, messages, model, tools=None):
    """Returns the interaction, or None on failure."""
    try:
        if tools:
            return await client.aio.interactions.create(input=messages, tools=tools, model=model)

        return await client.aio.interactions.create(input=messages, model=model)
    except Exception:
        logger.exception("error while calling the LLM")
        return None


def token_usage(interaction):
    usage = interaction.usage
    return {
        "input": usage.total_input_tokens,
        "output": usage.total_output_tokens,
        "thoughts": usage.total_thought_tokens,
        "tools": usage.total_tool_use_tokens,
        "total": usage.total_tokens,
    }
