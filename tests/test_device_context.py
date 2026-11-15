"""Device and context lifecycle, current-context routing."""
import pytest

from openal_py import Context, Device, ALC
from openal_py._core import get_current_context


# -- device -----------------------------------------------------------------

def test_device_name(device):
    assert device.name is None  # default device


def test_device_spec_is_string(device):
    assert isinstance(device.spec, str)
    assert len(device.spec) > 0


def test_device_extensions_are_strings(device):
    exts = device.extensions
    assert isinstance(exts, frozenset)
    assert all(isinstance(e, str) for e in exts)
    # System implementations may expose fewer extensions than the bundle.
    for ext in exts:
        assert device.supports(ext)
    assert not device.supports("ALC_NO_SUCH_EXTENSION")


def test_device_attributes(device):
    attrs = device.attributes
    assert isinstance(attrs, dict)
    assert attrs["ALC_FREQUENCY"] > 0
    assert attrs["ALC_REFRESH"] > 0
    assert attrs["ALC_MONO_SOURCES"] >= 1
    assert attrs["ALC_STEREO_SOURCES"] >= 1


def test_device_repr(device):
    assert "Device" in repr(device)


def test_device_context_manager():
    with Device.default() as dev:
        assert dev.spec
    # closed on exit; reopening a new handle works
    assert Device.default().spec


def test_open_device_by_name():
    name = Device.default().spec
    dev = Device.open(name)
    try:
        assert dev.spec
    finally:
        dev.close()


def test_close_idempotent():
    dev = Device.default()  # own handle; the shared fixture must stay open
    dev.close()
    dev.close()  # must not raise


def test_double_open_is_independent():
    d1 = Device.default()
    d2 = Device.default()
    assert d1.handle != d2.handle
    d1.close()
    d2.close()


# -- context ------------------------------------------------------------------

def test_context_not_current_by_default(device):
    with device.create_context() as context:
        assert not context.is_current


def test_make_current_returns_previous(ctx):
    prev = ctx.device and get_current_context()
    prev = ctx.make_current()
    assert prev is not None  # context was already made current by the fixture
    assert ctx.is_current


def test_multiple_contexts_switch(device):
    c1 = Context(device)
    c2 = Context(device)
    assert c1.handle != c2.handle

    with c1.activate():
        assert c1.is_current
        prev = c2.make_current()
        assert not c1.is_current
        assert c2.is_current
        # switch back
        c1.make_current()
        assert c1.is_current and not c2.is_current

    c1.destroy()
    c2.destroy()


def test_context_manager_clears_on_exit(device):
    with Context(device) as context, context.activate():
        assert get_current_context() != 0
    assert get_current_context() == 0


def test_context_manager_clears_on_exception(device):
    with pytest.raises(RuntimeError):
        with Context(device) as context, context.activate():
            raise RuntimeError("boom")
    assert get_current_context() == 0


def test_context_device_property(ctx, device):
    assert ctx.device is device


def test_process_and_suspend(ctx):
    ctx.process()  # should be a no-op that succeeds
    ctx.suspend()
    ctx.process()


def test_destroy_idempotent(device):
    c = Context(device)
    c.destroy()
    c.destroy()


def test_attributes_passed_through(device):
    c = Context(device, {"ALC_FREQUENCY": 48000})
    try:
        assert c.is_current is False
    finally:
        c.destroy()


@pytest.mark.parametrize("same_context", [False, True])
@pytest.mark.parametrize("raises", [False, True])
def test_nested_context_restores_outer(ctx, device, same_context, raises):
    inner = ctx if same_context else Context(device)
    try:
        if raises:
            with pytest.raises(ValueError):
                with inner.activate():
                    assert inner.is_current
                    raise ValueError("test")
        else:
            with inner.activate():
                assert inner.is_current
        assert ctx.is_current
    finally:
        if not same_context:
            inner.destroy()


def test_make_current_returns_actual_previous_handle(ctx, device):
    other = Context(device)
    try:
        assert other.make_current() == ctx.handle
        assert ctx.make_current() == other.handle
    finally:
        other.destroy()
