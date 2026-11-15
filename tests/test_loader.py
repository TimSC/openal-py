"""Selection policy and isolated native-library fallback tests."""
import ctypes.util
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

import openal_py
from openal_py import _core, _loader


@pytest.fixture
def policy(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAL_PY_LIBRARY", raising=False)
    monkeypatch.setattr(_loader, "system_libraries", lambda: ["system-one", "system-two"])
    bundle = tmp_path / "bundle.so"
    bundle.touch()
    return str(bundle)


def test_prefers_bundle_with_devices(policy):
    calls = []
    _loader.initialize(policy, lambda path, probe: calls.append((path, probe)) or True)
    assert calls == [(policy, True)]


@pytest.mark.parametrize("present", [False, True])
def test_falls_back_to_system(policy, present):
    if not present:
        Path(policy).unlink()
    calls = []

    def load(path, probe):
        calls.append((path, probe))
        return path == "system-two"

    _loader.initialize(policy, load)
    assert calls == ([(policy, True)] if present else []) + [
        ("system-one", False), ("system-two", False)
    ]


def test_headless_bundle_remains_usable_if_system_unavailable(policy):
    calls = []

    def load(path, probe):
        calls.append((path, probe))
        return path == policy and not probe

    _loader.initialize(policy, load)
    assert calls[-1] == (policy, False)


def test_missing_all_libraries_reports_attempts(policy):
    with pytest.raises(ImportError, match="system-two.*Install system OpenAL"):
        _loader.initialize(policy, lambda *args: False)


@pytest.mark.parametrize("success", [False, True])
def test_override_is_authoritative(policy, monkeypatch, success):
    monkeypatch.setenv("OPENAL_PY_LIBRARY", "/explicit/openal.so")
    calls = []

    def load(path, probe):
        calls.append((path, probe))
        return success

    if success:
        _loader.initialize(policy, load)
    else:
        with pytest.raises(ImportError, match="OPENAL_PY_LIBRARY"):
            _loader.initialize(policy, load)
    assert calls == [("/explicit/openal.so", False)]


@pytest.fixture
def isolated_package(tmp_path):
    root = tmp_path / "package"
    package = root / "openal_py"
    package.mkdir(parents=True)
    for source in Path(openal_py.__file__).parent.glob("*.py"):
        shutil.copy2(source, package / source.name)
    extension = Path(_core.__file__)
    shutil.copy2(extension, package / extension.name)
    return root, package


def run_isolated(root, code, override=None):
    env = dict(os.environ, PYTHONPATH=str(root), ALSOFT_DRIVERS="null")
    env.pop("OPENAL_PY_LIBRARY", None)
    if override is not None:
        env["OPENAL_PY_LIBRARY"] = str(override)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=root, env=env,
        capture_output=True, text=True, timeout=15,
    )


def require_system_openal():
    if not sys.platform.startswith("linux") or not ctypes.util.find_library("openal"):
        pytest.skip("integration test requires Linux system OpenAL")


@pytest.mark.parametrize("broken_bundle", [False, True])
def test_import_without_usable_bundle_uses_system(isolated_package, broken_bundle):
    require_system_openal()
    root, package = isolated_package
    if broken_bundle:
        (package / "libopenal.so.1").write_text("not a shared library")
    result = run_isolated(root, '''
from openal_py import Device, Context, library_path
assert library_path() == "libopenal.so.1", library_path()
with Device.default() as device:
    context = Context(device)
    with context.activate():
        source = context.create_source()
        source.play()
        source.delete()
    context.destroy()
''')
    assert result.returncode == 0, result.stderr


@pytest.fixture
def stub_library(tmp_path):
    """A core-complete OpenAL with no devices and no optional extensions."""
    if not sys.platform.startswith("linux") or not shutil.which("cc"):
        pytest.skip("requires a Linux C compiler")
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("openal_codegen", repo / "codegen/generate_api.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    commands = generator.parse_commands(ET.parse(generator.XML).getroot())
    bodies = {
        "alcGetString": 'return getenv("OPENAL_TEST_DEVICES") ? "one\\0two\\0\\0" : "";',
        "alcIsExtensionPresent": "return 1;",
        "alcGetIntegerv": "if (size > 0) values[0] = 1;",
    }
    definitions = ['#include "_api_table.h"', '#include <stdlib.h>']
    for command in commands:
        if command.get("ext"):
            continue
        name, ret = command["name"], command["ret"]
        args = ", ".join(f"{ctype} {arg}" for ctype, arg in command["params"]) or "void"
        body = bodies.get(name, "" if ret == "void" else "return 0;")
        definitions.append(f"{ret} {name}({args}) {{ {body} }}")
    source = tmp_path / "stub.c"
    source.write_text("\n".join(definitions))
    library = tmp_path / "stub.so"
    subprocess.run([
        "cc", "-shared", "-fPIC", "-DAL_LIBTYPE_STATIC",
        "-I", str(repo / "src/openal_py"), "-I", str(repo / "openal-soft/include"),
        str(source), "-o", str(library),
    ], check=True, capture_output=True, text=True)
    return library


def test_bundle_without_devices_uses_system(isolated_package, stub_library):
    require_system_openal()
    root, package = isolated_package
    shutil.copy2(stub_library, package / "libopenal.so.1")
    result = run_isolated(root, '''
from openal_py import library_path, Device
assert library_path() == "libopenal.so.1", library_path()
with Device.default():
    pass
''')
    assert result.returncode == 0, result.stderr


def test_override_without_optional_extensions_fails_safely(isolated_package, stub_library):
    root, _ = isolated_package
    result = run_isolated(root, '''
from openal_py import _core
try:
    _core.gen_effects(1)
except NotImplementedError:
    pass
else:
    raise AssertionError("missing optional function should raise")
''', override=stub_library)
    assert result.returncode == 0, result.stderr


def test_invalid_explicit_override_does_not_fall_back(isolated_package):
    root, _ = isolated_package
    result = run_isolated(root, "import openal_py", override=root / "missing.so")
    assert result.returncode != 0
    assert "OPENAL_PY_LIBRARY" in result.stderr


@pytest.mark.parametrize("explicit", [False, True])
def test_bundle_preference_and_full_device_list(isolated_package, stub_library, explicit):
    root, package = isolated_package
    bundle = package / "libopenal.so.1"
    shutil.copy2(stub_library, bundle)
    code = (
        "import os; os.environ['OPENAL_TEST_DEVICES'] = '1'\n"
        "from openal_py import library_path, enumerate_devices\n"
        f"assert library_path() == {str(bundle)!r}, library_path()\n"
        "assert enumerate_devices() == ['one', 'two'], enumerate_devices()\n"
    )
    result = run_isolated(root, code, override=bundle if explicit else None)
    assert result.returncode == 0, result.stderr


def test_proc_only_extension_addresses_follow_current_context(isolated_package, stub_library, tmp_path):
    """Routers need not export EFX; their proc addresses can differ by context."""
    import re
    root, _ = isolated_package
    source = tmp_path / 'stub.c'
    text = source.read_text()
    text = text.replace('#include "_api_table.h"', '''#include "_api_table.h"
#include <string.h>
static ALCcontext* active_context;
static void generate_one(ALsizei n, ALuint* values) { if(n) values[0]=101; }
static void generate_two(ALsizei n, ALuint* values) { if(n) values[0]=102; }
''')
    text, current_count = re.subn(
        r'(ALCcontext\s*\*\s*alcGetCurrentContext\([^\n]+\)\s*\{)[^\n]*\}',
        r'\1 return active_context; }', text)
    text, set_count = re.subn(
        r'(ALCboolean\s+alcMakeContextCurrent\([^\n]+\)\s*\{)[^\n]*\}',
        r'\1 active_context=context; return 1; }', text)
    text, proc_count = re.subn(
        r'(void\s*\*\s*alGetProcAddress\([^\n]+\)\s*\{)[^\n]*\}',
        r'\1 if(strcmp(fname,"alGenEffects")) return 0; '
        r'return (void*)(active_context==(ALCcontext*)1 ? generate_one : generate_two); }', text)
    assert (current_count, set_count, proc_count) == (1, 1, 1)
    source.write_text(text)
    repo = Path(__file__).resolve().parents[1]
    subprocess.run(['cc', '-shared', '-fPIC', '-DAL_LIBTYPE_STATIC',
                    '-I', str(repo / 'src/openal_py'), '-I', str(repo / 'openal-soft/include'),
                    str(source), '-o', str(stub_library)], check=True, capture_output=True, text=True)
    result = run_isolated(root, '''
from openal_py import _core
_core.make_context_current(1)
assert _core.gen_effects(1) == [101]
_core.make_context_current(2)
assert _core.gen_effects(1) == [102]
_core.make_context_current(None)
''', override=stub_library)
    assert result.returncode == 0, result.stderr
