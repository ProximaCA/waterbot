import pytest

from app import state


@pytest.fixture(autouse=True)
def isolate_ui_state():
    state.UI_MID.clear()
    state.CHANNEL_RETURN.clear()
    yield
    state.UI_MID.clear()
    state.CHANNEL_RETURN.clear()
