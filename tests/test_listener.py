"""Listener parameter round-trips (AL listener state)."""
import pytest

from openal_py import Listener


def _fresh(ctx):
    L = Listener()
    L.position = (0.0, 0.0, 0.0)
    L.direction = (0.0, 0.0, -1.0)
    L.up = (0.0, 1.0, 0.0)
    L.velocity = (0.0, 0.0, 0.0)
    L.gain = 1.0
    return L


@pytest.fixture
def L(ctx):
    return _fresh(ctx)


def test_position(L):
    L.position = (1.0, 2.0, 3.0)
    assert L.position == pytest.approx((1.0, 2.0, 3.0))


def test_velocity(L):
    L.velocity = (-1.5, 0.25, 3.5)
    assert L.velocity == pytest.approx((-1.5, 0.25, 3.5))


def test_direction_and_up(L):
    L.direction = (0.0, 0.0, 1.0)
    assert L.direction == pytest.approx((0.0, 0.0, 1.0))
    # up must be preserved when direction changes
    assert L.up == pytest.approx((0.0, 1.0, 0.0))

    L.up = (1.0, 0.0, 0.0)
    assert L.up == pytest.approx((1.0, 0.0, 0.0))
    # direction must be preserved when up changes
    assert L.direction == pytest.approx((0.0, 0.0, 1.0))


def test_direction_up_orthogonal_pair(L):
    # set a full orientation pair
    L.direction = (1.0, 0.0, 0.0)
    L.up = (0.0, 0.0, 1.0)
    assert L.direction == pytest.approx((1.0, 0.0, 0.0))
    assert L.up == pytest.approx((0.0, 0.0, 1.0))


def test_gain(L):
    L.gain = 0.25
    assert L.gain == pytest.approx(0.25)
    L.gain = 2.0
    assert L.gain == pytest.approx(2.0)


def test_listener_is_global_state(ctx, device):
    # Listener state is global: a second Listener sees the same values
    L1 = _fresh(ctx)
    L1.gain = 0.42
    L2 = Listener()
    assert L2.gain == pytest.approx(0.42)
    # and survives to a new context on the same device
    L1.gain = 1.0
    from openal_py import Context
    c2 = Context(device)
    with c2:
        assert Listener().gain == pytest.approx(1.0)
    c2.destroy()
