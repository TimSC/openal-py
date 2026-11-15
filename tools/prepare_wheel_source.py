#!/usr/bin/env python3
"""Copy build inputs into a fresh snapshot without Git or local build artifacts.

Both wheel scripts use this helper so builds consume the current working files
(including uncommitted changes) without writing into the development checkout.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

ROOT_FILES = ('pyproject.toml', 'README.md', 'meson.build', 'meson_options.txt')
SOURCE_DIRS = ('src', 'examples')


def ignore_artifacts(directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if (name in ('.git', '__pycache__')
                or name.endswith(('.pyc', '.pyo', '.so', '.pyd', '.dll', '.dylib', '.whl'))
                or '.so.' in name):
            ignored.add(name)
        elif (Path(directory) / name).is_dir() and (
            name in ('build', 'dist', 'venv', '.venv')
            or name.startswith(('build-', 'build_', 'cmake-build-', '.mesonpy-'))
        ):
            ignored.add(name)
    return ignored


def prepare_source(root: Path, destination: Path, openal_source: Path | None = None) -> None:
    root = root.resolve(strict=True)
    openal = (openal_source or root / 'openal-soft').resolve(strict=True)
    destination = destination.resolve()
    if destination.is_relative_to(root) or destination.is_relative_to(openal):
        raise ValueError('the build snapshot must be outside the source checkout')
    required = [*(root / name for name in ROOT_FILES),
                *(root / name for name in SOURCE_DIRS), openal / 'include/AL/al.h']
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f'missing build input: {path}')
    # Never merge into or remove an existing directory supplied by the caller.
    destination.mkdir(parents=True, exist_ok=False)
    for name in ROOT_FILES:
        shutil.copy2(root / name, destination / name)
    for name in SOURCE_DIRS:
        shutil.copytree(root / name, destination / name, ignore=ignore_artifacts)
    shutil.copytree(openal, destination / 'openal-soft', ignore=ignore_artifacts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--openal-source', type=Path)
    args = parser.parse_args()
    prepare_source(args.root, args.destination, args.openal_source)


if __name__ == '__main__':
    main()
