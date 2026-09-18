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


from src.copy_generator import self_check_candidate, regenerate_candidate, generate_with_self_check


@patch('src.copy_generator.call_llm_json')
def test_self_check_candidate_passes(mock_call):
    mock_call.return_value = {'insight_holds': True, 'reason': 'still true without the wit'}
    candidate = {'insight': 'x', 'title': 'Fast shoes, slower payments.', 'body': ''}
    assert self_check_candidate(candidate, model='claude-sonnet-4-6') is True


@patch('src.copy_generator.call_llm_json')
def test_self_check_candidate_fails(mock_call):
    mock_call.return_value = {'insight_holds': False, 'reason': 'nothing left without the pun'}
    candidate = {'insight': 'x', 'title': 'Scent-sibly priced', 'body': ''}
    assert self_check_candidate(candidate, model='claude-sonnet-4-6') is False


@patch('src.copy_generator.call_llm_json')
def test_self_check_candidate_handles_stringified_false(mock_call):
    mock_call.return_value = {'insight_holds': 'false', 'reason': 'stringified boolean'}
    candidate = {'insight': 'x', 'title': 'Some line', 'body': ''}
    assert self_check_candidate(candidate, model='claude-sonnet-4-6') is False


@patch('src.copy_generator.call_llm_json')
def test_self_check_candidate_handles_stringified_true(mock_call):
    mock_call.return_value = {'insight_holds': 'true', 'reason': 'stringified boolean'}
    candidate = {'insight': 'x', 'title': 'Some line', 'body': ''}
    assert self_check_candidate(candidate, model='claude-sonnet-4-6') is True


@patch('src.copy_generator.call_llm_json')
def test_self_check_candidate_defaults_false_on_non_dict_response(mock_call):
    mock_call.return_value = ['unexpected', 'array', 'response']
    candidate = {'insight': 'x', 'title': 'Some line', 'body': ''}
    assert self_check_candidate(candidate, model='claude-sonnet-4-6') is False


@patch('src.copy_generator.call_llm_json')
def test_regenerate_candidate_avoids_existing_insights(mock_call):
    mock_call.return_value = [{'insight': 'new angle', 'title': 'T', 'body': 'B'}]
    result = regenerate_candidate(SAMPLE_BRIEF, existing_insights=['angle a', 'angle b'], model='claude-sonnet-4-6')
    assert result['insight'] == 'new angle'
    _, kwargs = mock_call.call_args
    assert 'angle a' in kwargs.get('user', mock_call.call_args[0][2] if len(mock_call.call_args[0]) > 2 else '')


@patch('src.copy_generator.self_check_candidate')
@patch('src.copy_generator.generate_candidates')
def test_generate_with_self_check_flags_repeat_failures(mock_generate, mock_self_check):
    mock_generate.return_value = [{'insight': 'a', 'title': 'T', 'body': 'B'}]
    # Fails self-check both on the original AND the regenerated replacement
    mock_self_check.return_value = False

    with patch('src.copy_generator.regenerate_candidate') as mock_regen:
        mock_regen.return_value = {'insight': 'a2', 'title': 'T2', 'body': 'B2'}
        result = generate_with_self_check(SAMPLE_BRIEF, model='claude-sonnet-4-6')

    assert len(result) == 1
    assert result[0]['self_check_passed'] is False
    assert result[0]['self_check_flag'] == '⚠️ insight may be thin'


@patch('src.copy_generator.self_check_candidate')
@patch('src.copy_generator.generate_candidates')
def test_generate_with_self_check_accepts_regenerated_replacement(mock_generate, mock_self_check):
    mock_generate.return_value = [{'insight': 'a', 'title': 'T', 'body': 'B'}]
    # Fails first check, passes second (on the regenerated replacement)
    mock_self_check.side_effect = [False, True]

    with patch('src.copy_generator.regenerate_candidate') as mock_regen:
        mock_regen.return_value = {'insight': 'a2', 'title': 'T2', 'body': 'B2'}
        result = generate_with_self_check(SAMPLE_BRIEF, model='claude-sonnet-4-6')

    assert len(result) == 1
    assert result[0]['title'] == 'T2'
    assert result[0]['self_check_passed'] is True
    assert result[0].get('self_check_flag') is None


@patch('src.copy_generator.self_check_candidate')
@patch('src.copy_generator.generate_candidates')
def test_generate_with_self_check_updates_existing_insights_across_batch(mock_generate, mock_self_check):
    mock_generate.return_value = [
        {'insight': 'angle a', 'title': 'T1', 'body': 'B1'},
        {'insight': 'angle b', 'title': 'T2', 'body': 'B2'},
    ]
    # Both candidates fail their first self-check; both regenerations pass
    mock_self_check.side_effect = [False, True, False, True]

    with patch('src.copy_generator.regenerate_candidate') as mock_regen:
        mock_regen.side_effect = [
            {'insight': 'angle c', 'title': 'T1b', 'body': 'B1b'},
            {'insight': 'angle d', 'title': 'T2b', 'body': 'B2b'},
        ]
        generate_with_self_check(SAMPLE_BRIEF, model='claude-sonnet-4-6')

    # Second regenerate_candidate call's existing_insights arg should include
    # the FIRST regeneration's insight ('angle c'), not just the original batch's
    second_call_args = mock_regen.call_args_list[1]
    existing_insights_arg = second_call_args[0][1]  # regenerate_candidate(brief, existing_insights, model=...)
    assert 'angle c' in existing_insights_arg


from src.copy_generator import validate_lengths


def test_validate_lengths_flags_over_limit_title():
    candidates = [{'title': 'x' * 100, 'body': 'short body'}]
    validate_lengths(candidates)
    assert candidates[0]['title_over_limit'] is True
    assert candidates[0]['body_over_limit'] is False


def test_validate_lengths_passes_within_limit():
    candidates = [{'title': 'Short title', 'body': 'Short body'}]
    validate_lengths(candidates)
    assert candidates[0]['title_over_limit'] is False
    assert candidates[0]['body_over_limit'] is False


import pandas as pd
from src.copy_generator import generate_and_score


@patch('src.copy_generator.generate_with_self_check')
def test_generate_and_score_ties_everything_together(mock_generate):
    mock_generate.return_value = [
        {'insight': 'a', 'title': 'Win ₹50 POPcoins today', 'body': 'Pay with POP UPI',
         'self_check_passed': True, 'self_check_flag': None},
    ]
    empty_lookup = pd.DataFrame(columns=['bu', 'tonality', 'avg_ctr', 'campaign_count'])
    result = generate_and_score(SAMPLE_BRIEF, historical_lookup=empty_lookup)

    assert len(result) == 1
    # Has fields from self-check...
    assert result[0]['self_check_passed'] is True
    # ...from length validation...
    assert 'title_over_limit' in result[0]
    # ...and from rule-based scoring
    assert result[0]['tonality'] == 'DO: Smart — Value-aware'
