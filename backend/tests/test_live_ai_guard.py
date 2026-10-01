from pathlib import Path

from app.main import check_live_ai_guard

DOCS_PATH = Path("tests/fixtures/documents")


def test_no_documents_requested_never_blocks():
    assert check_live_ai_guard(None, api_key="sk-real", confirmed=False) is None


def test_no_api_key_never_blocks():
    assert check_live_ai_guard(DOCS_PATH, api_key=None, confirmed=False) is None
    assert check_live_ai_guard(DOCS_PATH, api_key="", confirmed=False) is None


def test_real_key_without_confirmation_blocks():
    error = check_live_ai_guard(DOCS_PATH, api_key="sk-real", confirmed=False)
    assert error is not None
    assert "DEEPSEEK_API_KEY" in error


def test_real_key_with_confirmation_proceeds():
    assert check_live_ai_guard(DOCS_PATH, api_key="sk-real", confirmed=True) is None
