"""Wheel builds preserve source/build artifacts and use independent outputs."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_wheel_source', ROOT / 'tools/prepare_wheel_source.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def write(path, content='source'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def source_tree(tmp_path):
    root = tmp_path / 'checkout'
    for name in prepare.ROOT_FILES:
        write(root / name)
    for name in ('src/openal_py/_api_table.c', 'src/openal_py/_core.pyx',
                 'src/openal_py/_al_api.pxd', 'examples/example.py',
                 'openal-soft/include/AL/al.h', 'openal-soft/source.cpp',
                 'openal-soft/build_version.py'):
        write(root / name)
    for name in ('.git/index', '.aws/credentials',
                 'src/openal_py/__pycache__/buffer.pyc', 'src/openal_py/_core.so',
                 'src/openal_py/openal.dll', 'openal-soft/.git',
                 'openal-soft/build/CMakeCache.txt', 'openal-soft/build-debug/cache',
                 'wheelhouse/old.whl'):
        write(root / name, 'keep original')
    return root


def test_source_snapshot_copies_current_inputs_and_preserves_originals(source_tree, tmp_path):
    write(source_tree / 'openal-soft/source.cpp', 'uncommitted current source')
    destination = tmp_path / 'snapshot'
    prepare.prepare_source(source_tree, destination)
    assert (destination / 'openal-soft/source.cpp').read_text() == 'uncommitted current source'
    assert (destination / 'src/openal_py/_api_table.c').is_file()
    assert (destination / 'openal-soft/build_version.py').is_file()
    assert not (destination / 'openal-soft/build').exists()
    assert not (destination / 'openal-soft/build-debug').exists()
    assert not (destination / 'openal-soft/.git').exists()
    assert not (destination / '.git').exists()
    assert not (destination / '.aws').exists()
    assert not (destination / 'wheelhouse').exists()
    assert not (destination / 'src/openal_py/__pycache__').exists()
    assert not (destination / 'src/openal_py/_core.so').exists()
    assert not (destination / 'src/openal_py/openal.dll').exists()
    assert (source_tree / 'openal-soft/build/CMakeCache.txt').read_text() == 'keep original'
    assert (source_tree / 'wheelhouse/old.whl').read_text() == 'keep original'


def test_snapshot_does_not_merge_with_existing_directory(source_tree, tmp_path):
    destination = tmp_path / 'snapshot'
    write(destination / 'marker', 'existing')
    with pytest.raises(FileExistsError):
        prepare.prepare_source(source_tree, destination)
    assert (destination / 'marker').read_text() == 'existing'


def test_snapshot_rejects_workspace_inside_source(source_tree):
    with pytest.raises(ValueError, match='outside'):
        prepare.prepare_source(source_tree, source_tree / 'snapshot')
    assert not (source_tree / 'snapshot').exists()


def test_snapshot_respects_custom_openal_source(source_tree, tmp_path):
    alternative = tmp_path / 'other-openal'
    write(alternative / 'include/AL/al.h', 'custom headers')
    write(alternative / 'custom.cpp')
    destination = tmp_path / 'snapshot'
    prepare.prepare_source(source_tree, destination, alternative)
    assert (destination / 'openal-soft/include/AL/al.h').read_text() == 'custom headers'
    assert (destination / 'openal-soft/custom.cpp').is_file()
    assert not (destination / 'openal-soft/source.cpp').exists()


@pytest.mark.skipif(shutil.which('bash') is None, reason='requires bash')
def test_parallel_wheel_invocations_preserve_outputs_and_native_build(source_tree, tmp_path):
    # Exercise the actual host script with a container-engine stand-in. Native
    # compilation/repair is covered by the real manylinux integration build.
    script = source_tree / 'tools/build_manylinux_wheels.sh'
    script.parent.mkdir()
    shutil.copy2(ROOT / 'tools/build_manylinux_wheels.sh', script)
    fake_engine = tmp_path / 'container-engine'
    fake_engine.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CONTAINER_TEST_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
mount = next(value for value in args if value.endswith(':/wheelhouse'))
output = pathlib.Path(mount[:-len(':/wheelhouse')])
(output / 'new.whl').write_text('validated wheel stand-in')
''')
    fake_engine.chmod(0o755)
    output = tmp_path / 'wheel output'
    write(output / 'old.whl', 'earlier wheel')
    log = tmp_path / 'container-calls.jsonl'
    command = ['bash', str(script), '--engine', str(fake_engine),
               '--wheelhouse', str(output), '--jobs', '2', '--python-tags', 'cp312-cp312']
    env = dict(os.environ, CONTAINER_TEST_LOG=str(log))
    def run():
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert all(result.returncode == 0 for result in results), [result.stderr for result in results]
    assert (output / 'old.whl').read_text() == 'earlier wheel'
    assert (source_tree / 'openal-soft/build/CMakeCache.txt').read_text() == 'keep original'
    assert (source_tree / 'src/openal_py/_api_table.c').is_file()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    mounts = [next(value for value in call if value.endswith(':/wheelhouse')) for call in calls]
    assert len(set(mounts)) == 2
    for call, mount in zip(calls, mounts):
        assert str(source_tree) + ':/source:ro' in call
        directory = Path(mount[:-len(':/wheelhouse')])
        assert directory.parent == output and (directory / 'new.whl').is_file()
        body = call[-1]
        syntax = subprocess.run(['bash', '-n'], input=body, text=True, capture_output=True)
        assert syntax.returncode == 0, syntax.stderr
