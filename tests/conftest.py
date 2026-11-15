"""Shared fixtures: device + context for each test (null backend is fine)."""
import pytest

from openal_py import Context, Device


@pytest.fixture(scope="session")
def device():
    # One shared device for the whole run: the OpenAL-soft null backend has a
    # limited number of simultaneous devices, and per-test open/close churn
    # can exhaust it.
    dev = Device.default()
    yield dev
    dev.close()


@pytest.fixture
def ctx(device):
    context = Context(device)
    with context:
        yield context
