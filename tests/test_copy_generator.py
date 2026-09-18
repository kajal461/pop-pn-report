# filepath: tests/test_copy_generator.py
from unittest.mock import patch

import pytest

from src.copy_generator import build_user_prompt, generate_candidates
from src.llm_client import LLMError

SAMPLE_BRIEF = {
    'bu': 'Shop', 'product': 'Electronics', 'price': '20% off',
    'offer': 'Flash sale', 'brand': 'POP', 'campaign_type': 'Promo', 'segment': '',
}


def test_build_user_prompt_includes_all_brief_fields():
    prompt = build_user_prompt(SAMPLE_BRIEF)
    assert 'Shop' in prompt
    assert 'Electronics' in prompt
    assert '20% off' in prompt
    assert 'Flash sale' in prompt
    assert 'POP' in prompt
    assert 'Promo' in prompt


def test_build_user_prompt_handles_missing_segment():
    brief = dict(SAMPLE_BRIEF)
    brief['segment'] = ''
    prompt = build_user_prompt(brief)
    assert 'Not specified' in prompt


@patch('src.copy_generator.call_llm_json')
def test_generate_candidates_returns_parsed_list(mock_call):
    mock_call.return_value = [
        {'insight': 'a', 'title': 'Title A', 'body': 'Body A'},
        {'insight': 'b', 'title': 'Title B', 'body': 'Body B'},
    ]
    candidates = generate_candidates(SAMPLE_BRIEF, model='claude-sonnet-4-6')
    assert len(candidates) == 2
    assert candidates[0]['title'] == 'Title A'


@patch('src.copy_generator.call_llm_json')
def test_generate_candidates_raises_on_missing_keys(mock_call):
    mock_call.return_value = [{'insight': 'a', 'title': 'Title A'}]  # missing 'body'
    with pytest.raises(LLMError, match='missing required key'):
        generate_candidates(SAMPLE_BRIEF, model='claude-sonnet-4-6')


@patch('src.copy_generator.call_llm_json')
def test_generate_candidates_raises_on_non_list_response(mock_call):
    mock_call.return_value = {'not': 'a list'}
    with pytest.raises(LLMError, match='expected a JSON array'):
        generate_candidates(SAMPLE_BRIEF, model='claude-sonnet-4-6')
