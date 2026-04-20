import pytest


@pytest.fixture(autouse=True)
def _reset_ai_provider_cache():
    """每个测试前清除 ai_classifier 的 provider 缓存，防止测试间泄漏。"""
    import ai_classifier
    ai_classifier.invalidate_provider_cache()
    yield
    ai_classifier.invalidate_provider_cache()
