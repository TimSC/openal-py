#!/usr/bin/env bash
# Build and repair manylinux wheels for openal-py.
#
# PyPI does not accept generic linux_x86_64 wheels, so each wheel is built
# inside a manylinux container (where libopenal is also built, with the
# image's own toolchain) and then repaired with auditwheel.
#
# The bundled openal-soft 1.25 needs C++20 (gcc 11+), so use the
# manylinux_2_28 image (ships gcc-toolset-14), not manylinux2014 (gcc 4.8).
#
# Usage:
#   tools/build_manylinux_wheels.sh [options]
#
# Options:
#   --python-tags TAGS   Space-separated /opt/python tags to build
#   --wheelhouse PATH    Output directory (default: ./wheelhouse)
#   --image IMAGE        manylinux image
#   --engine COMMAND     Container engine: docker or podman
#   --jobs N             Parallelism for the libopenal build
#   -h, --help           Show this help
#
# Environment variables provide the same configuration:
#   PYTHON_TAGS, WHEELHOUSE, MANYLINUX_IMAGE, CONTAINER_ENGINE, JOBS
#
# Examples:
#   tools/build_manylinux_wheels.sh
#   tools/build_manylinux_wheels.sh --python-tags "cp311-cp311 cp312-cp312"
#   CONTAINER_ENGINE=podman tools/build_manylinux_wheels.sh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-docker}"
MANYLINUX_IMAGE="${MANYLINUX_IMAGE:-quay.io/pypa/manylinux_2_28_x86_64}"
# The manylinux_2_28 image ships interpreters up to cp313.
PYTHON_TAGS="${PYTHON_TAGS:-cp310-cp310 cp311-cp311 cp312-cp312 cp313-cp313}"
WHEELHOUSE="${WHEELHOUSE:-"$ROOT_DIR/wheelhouse"}"
JOBS="${JOBS:-$(nproc)}"

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
}

while (($#)); do
    case "$1" in
        --python-tags)
            PYTHON_TAGS="$2"
            shift 2
            ;;
        --wheelhouse)
            WHEELHOUSE="$2"
            shift 2
            ;;
        --image)
            MANYLINUX_IMAGE="$2"
            shift 2
            ;;
        --engine)
            CONTAINER_ENGINE="$2"
            shift 2
            ;;
        --jobs)
            JOBS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! command -v "$CONTAINER_ENGINE" >/dev/null 2>&1; then
    echo "Container engine not found: $CONTAINER_ENGINE" >&2
    exit 1
fi

WHEELHOUSE="$(realpath -m "$WHEELHOUSE")"
mkdir -p "$WHEELHOUSE"
rm -f "$WHEELHOUSE"/*.whl

# The wheel's libopenal is built at openal-soft/build (the meson default),
# so the repo is mounted read-write and that directory is rebuilt inside
# the image. The build tree is git-ignored.
"$CONTAINER_ENGINE" run --rm \
    -e "PYTHON_TAGS=$PYTHON_TAGS" \
    -e "JOBS=$JOBS" \
    -v "$ROOT_DIR:/project" \
    -v "$WHEELHOUSE:/wheelhouse" \
    -w /project \
    "$MANYLINUX_IMAGE" \
    bash -lc '
        set -euo pipefail

        echo "Building libopenal with the image toolchain..."
        dnf install -y alsa-lib-devel pulseaudio-libs-devel pipewire-devel
        rm -rf openal-soft/build
        # PipeWire is built if found, not required: the pipewire in the image
        # (0.3.6) is older than the 0.3.23 openal-soft needs.
        cmake -S openal-soft -B openal-soft/build \
            -DCMAKE_BUILD_TYPE=Release \
            -DBUILD_SHARED_LIBS=ON \
            -DENABLE_ALSOFT_EXAMPLES=OFF \
            -DBUILD_TESTING=OFF \
            -DALSOFT_REQUIRE_ALSA=ON \
            -DALSOFT_REQUIRE_PULSEAUDIO=ON \
            -DALSOFT_BACKEND_PIPEWIRE=ON
        cmake --build openal-soft/build -j "$JOBS"
        test -f openal-soft/build/libopenal.so.1

        built=0
        for tag in $PYTHON_TAGS; do
            python="/opt/python/$tag/bin/python"
            if [[ ! -x "$python" ]]; then
                echo "skip: $tag is not in the image" >&2
                continue
            fi

            echo "Building openal-py wheel for $tag..."
            export PATH="/opt/python/$tag/bin:$PATH"
            "$python" -m pip install --upgrade \
                "meson-python>=0.16" "meson>=1.8" "ninja>=1.11" \
                "cython>=3.0" build twine auditwheel

            raw_dir="/tmp/openalpy-raw/$tag"
            rm -rf "$raw_dir"
            mkdir -p "$raw_dir"

            "$python" -m build \
                --wheel \
                --no-isolation \
                --skip-dependency-check \
                --outdir "$raw_dir"

            "$python" -m auditwheel show "$raw_dir"/*.whl
            # The audio libraries are dlopen()ed by the backends at runtime
            # (recorded in the .note.gnu.dlopen section), so auditwheel knows
            # to leave them out of the wheel.
            "$python" -m auditwheel repair "$raw_dir"/*.whl --wheel-dir /wheelhouse
            for wheel in /wheelhouse/*.whl; do
                "$python" -m twine check "$wheel"
            done
            built=$((built + 1))
        done

        if [[ "$built" -eq 0 ]]; then
            echo "No interpreters built: none of $PYTHON_TAGS is in $MANYLINUX_IMAGE" >&2
            exit 1
        fi
    '

echo "Built manylinux wheels:"
find "$WHEELHOUSE" -maxdepth 1 -type f -name '*.whl' -print | sort
