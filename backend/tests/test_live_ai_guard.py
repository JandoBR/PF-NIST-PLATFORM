from app.ai.guard import check_live_ai_guard


def test_ai_not_requested_never_blocks():
    assert check_live_ai_guard(False, api_key="sk-real", confirmed=False) is None


def test_no_api_key_never_blocks():
    assert check_live_ai_guard(True, api_key=None, confirmed=False) is None
    assert check_live_ai_guard(True, api_key="", confirmed=False) is None


def test_real_key_without_confirmation_blocks():
    error = check_live_ai_guard(True, api_key="sk-real", confirmed=False)
    assert error is not None
    assert "DEEPSEEK_API_KEY" in error


def test_real_key_with_confirmation_proceeds():
    assert check_live_ai_guard(True, api_key="sk-real", confirmed=True) is None


def test_ai_adjust_alone_without_documents_still_triggers_the_guard():
    """--ai-adjust puede llamar a la IA sin --documents: el guard debe cubrirlo igual."""

    error = check_live_ai_guard(True, api_key="sk-real", confirmed=False)
    assert error is not None
