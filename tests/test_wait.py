from app import state
from app.wait import WAIT_WM_IMAGE, clear_wait, get_wait, set_wait


def test_get_wait_expires():
    clear_wait(42)
    set_wait(42, WAIT_WM_IMAGE)
    assert get_wait(42) == WAIT_WM_IMAGE
    kind, _expires = state.WAIT[42]
    state.WAIT[42] = (kind, 0)
    assert get_wait(42) is None
    assert 42 not in state.WAIT
