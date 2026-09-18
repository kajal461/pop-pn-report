# tests/test_config_copy_generator.py
from config import LLM_MODEL_REGISTRY, COPY_GEN_MODEL, BRIEF_SHEET_ID


def test_default_model_is_registered():
    assert COPY_GEN_MODEL in LLM_MODEL_REGISTRY


def test_all_registry_entries_have_provider_and_api_model():
    for model, entry in LLM_MODEL_REGISTRY.items():
        assert 'provider' in entry
        assert 'api_model' in entry
        assert entry['provider'] in ('anthropic', 'fireworks')


def test_brief_sheet_id_is_set():
    assert BRIEF_SHEET_ID  # should resolve to TEST_SHEET_ID by default
