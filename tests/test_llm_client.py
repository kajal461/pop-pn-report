# filepath: tests/test_llm_client.py
from unittest.mock import MagicMock, patch

import pytest

from src.llm_client import call_llm, call_llm_json, LLMError


def test_call_llm_unknown_model_raises():
    with pytest.raises(LLMError, match='Unknown model'):
        call_llm('not-a-real-model', 'system', 'user')


@patch('src.llm_client.anthropic.Anthropic')
def test_call_llm_anthropic_provider(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='hello from claude')]
    mock_client.messages.create.return_value = mock_response
    mock_anthropic_cls.return_value = mock_client

    result = call_llm('claude-sonnet-4-6', 'sys', 'usr')

    assert result == 'hello from claude'
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs['model'] == 'claude-sonnet-4-6'
    assert kwargs['system'] == 'sys'


@patch('src.llm_client.openai.OpenAI')
def test_call_llm_fireworks_provider(mock_openai_cls):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='hello from kimi'))]
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai_cls.return_value = mock_client

    result = call_llm('kimi-k3', 'sys', 'usr')

    assert result == 'hello from kimi'


@patch('src.llm_client.anthropic.Anthropic')
def test_call_llm_anthropic_provider_wraps_sdk_exception(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception('rate limited')
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMError, match="LLM call to 'claude-sonnet-4-6' failed: rate limited"):
        call_llm('claude-sonnet-4-6', 'sys', 'usr')


@patch('src.llm_client.openai.OpenAI')
def test_call_llm_fireworks_provider_calls_with_correct_kwargs_and_wraps_exception(mock_openai_cls):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='hello from kimi'))]
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai_cls.return_value = mock_client

    call_llm('kimi-k3', 'sys', 'usr')

    _, kwargs = mock_client.chat.completions.create.call_args
    assert kwargs['model'] == 'kimi-k3'
    assert kwargs['messages'] == [
        {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': 'usr'},
    ]

    mock_client.chat.completions.create.side_effect = Exception('gateway timeout')
    with pytest.raises(LLMError, match="LLM call to 'kimi-k3' failed: gateway timeout"):
        call_llm('kimi-k3', 'sys', 'usr')


@patch('src.llm_client.call_llm')
def test_call_llm_json_parses_plain_json(mock_call_llm):
    mock_call_llm.return_value = '{"a": 1, "b": "two"}'
    result = call_llm_json('claude-sonnet-4-6', 'sys', 'usr')
    assert result == {'a': 1, 'b': 'two'}


@patch('src.llm_client.call_llm')
def test_call_llm_json_strips_markdown_fences(mock_call_llm):
    mock_call_llm.return_value = '```json\n{"a": 1}\n```'
    result = call_llm_json('claude-sonnet-4-6', 'sys', 'usr')
    assert result == {'a': 1}


@patch('src.llm_client.call_llm')
def test_call_llm_json_raises_on_invalid_json(mock_call_llm):
    mock_call_llm.return_value = 'not json at all'
    with pytest.raises(LLMError, match='not valid JSON'):
        call_llm_json('claude-sonnet-4-6', 'sys', 'usr')
