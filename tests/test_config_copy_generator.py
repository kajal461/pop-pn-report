# tests/test_config_copy_generator.py
from config import LLM_MODEL_REGISTRY, COPY_GEN_MODEL, BRIEF_SHEET_ID, ANTHROPIC_GATEWAY_BASE_URL


def test_default_model_is_registered():
    assert COPY_GEN_MODEL in LLM_MODEL_REGISTRY


def test_all_registry_entries_have_provider_and_api_model():
    for model, entry in LLM_MODEL_REGISTRY.items():
        assert 'provider' in entry
        assert 'api_model' in entry
        assert entry['provider'] in ('anthropic', 'fireworks')


def test_brief_sheet_id_is_set():
    assert BRIEF_SHEET_ID  # should resolve to TEST_SHEET_ID by default


def test_anthropic_gateway_base_url_has_no_trailing_v1():
    # The anthropic SDK appends /v1/messages itself — a base_url ending in
    # /v1 produces a double /v1/v1/messages path and a 404 on every real
    # call (caught 2026-09-18 during live verification against the actual
    # gateway, not just mocked tests).
    assert not ANTHROPIC_GATEWAY_BASE_URL.rstrip('/').endswith('/v1')


def test_config_calls_load_dotenv_itself():
    # config.py must call load_dotenv() itself at import time, not rely on
    # some other module (e.g. src/bq_loader.py) having already done so
    # first — every Copy Generator script imports `config` before
    # `src.bq_loader`, so if config.py doesn't load .env itself, its
    # env-driven constants silently default to '' regardless of what's
    # actually in .env (caught 2026-09-18 during live verification).
    import config
    import inspect
    source = inspect.getsource(config)
    assert 'load_dotenv()' in source
