# filepath: src/llm_client.py
"""
Thin, provider-abstracting client for calling the LLM gateway used by the
Copy Generator. Supports two provider families reachable through Razorpay's
internal gateways:
  - 'anthropic'  -> Claude models, via the Anthropic-compatible gateway
  - 'fireworks'  -> Kimi/GLM/GPT models, via the OpenAI-compatible LiteLLM gateway

Model names are looked up in config.LLM_MODEL_REGISTRY to decide which
provider function to call — callers never need to know which HTTP API a
given model name maps to.
"""
import json

import anthropic
import openai

from config import (
    LLM_MODEL_REGISTRY,
    ANTHROPIC_GATEWAY_BASE_URL, ANTHROPIC_GATEWAY_API_KEY,
    FIREWORKS_GATEWAY_BASE_URL, FIREWORKS_GATEWAY_API_KEY,
    FIREWORKS_GATEWAY_LITELLM_KEY,
)


class LLMError(Exception):
    """Raised when the LLM gateway call fails, or its response can't be parsed."""


def _call_anthropic(api_model: str, system: str, user: str, max_tokens: int) -> str:
    client = anthropic.Anthropic(
        base_url=ANTHROPIC_GATEWAY_BASE_URL,
        api_key=ANTHROPIC_GATEWAY_API_KEY,
    )
    response = client.messages.create(
        model=api_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{'role': 'user', 'content': user}],
    )
    return response.content[0].text


def _call_fireworks(api_model: str, system: str, user: str, max_tokens: int) -> str:
    client = openai.OpenAI(
        base_url=FIREWORKS_GATEWAY_BASE_URL,
        api_key=FIREWORKS_GATEWAY_API_KEY,
        default_headers={'x-litellm-api-key': f'Bearer {FIREWORKS_GATEWAY_LITELLM_KEY}'},
    )
    response = client.chat.completions.create(
        model=api_model,
        max_tokens=max_tokens,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    )
    return response.choices[0].message.content


_PROVIDER_FUNCS = {
    'anthropic': _call_anthropic,
    'fireworks': _call_fireworks,
}


def call_llm(model: str, system: str, user: str, max_tokens: int = 1500) -> str:
    """
    Call the given model with a system + user prompt, return the raw text
    response. Raises LLMError on failure — callers decide whether to retry.
    """
    if model not in LLM_MODEL_REGISTRY:
        raise LLMError(f'Unknown model {model!r} — add it to config.LLM_MODEL_REGISTRY')
    entry = LLM_MODEL_REGISTRY[model]
    func = _PROVIDER_FUNCS[entry['provider']]
    try:
        return func(entry['api_model'], system, user, max_tokens)
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f'LLM call to {model!r} failed: {exc}') from exc


def call_llm_json(model: str, system: str, user: str, max_tokens: int = 1500) -> dict:
    """
    Call the LLM and parse its response as JSON. Raises LLMError if the
    response isn't valid JSON (strips markdown code fences first, since
    models often wrap JSON in ```json ... ``` blocks).
    """
    raw = call_llm(model, system, user, max_tokens=max_tokens)
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as exc:
        raise LLMError(f'LLM response was not valid JSON: {exc}\nRaw response: {raw!r}') from exc
