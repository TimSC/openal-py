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
#   --wheelhouse PATH    Parent for unique per-run outputs (default: ./wheelhouse)
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
# Build these interpreter versions by default; additional tags can be requested.
PYTHON_TAGS="${PYTHON_TAGS:-cp311-cp311 cp312-cp312 cp313-cp313 cp314-cp314 cp315-cp315}"
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

if ! [[ "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "--jobs must be a positive integer" >&2
    exit 1
fi

WHEELHOUSE="$(realpath -m "$WHEELHOUSE")"
mkdir -p "$WHEELHOUSE"
image_label="${MANYLINUX_IMAGE##*/}"
image_label="${image_label//[^a-zA-Z0-9_.-]/_}"
RUN_DIR="$(mktemp -d "$WHEELHOUSE/$image_label.XXXXXXXX")"
echo "Wheel output: $RUN_DIR"

# Source is read-only. Snapshots, CMake/Meson builds, and raw/repaired wheels
# live in a private container workspace. Only validated wheels are published.
"$CONTAINER_ENGINE" run --rm \
    -e "PYTHON_TAGS=$PYTHON_TAGS" \
    -e "JOBS=$JOBS" \
    -v "$ROOT_DIR:/source:ro" \
    -v "$RUN_DIR:/wheelhouse" \
    -w /tmp \
    "$MANYLINUX_IMAGE" \
    bash -lc '
        set -euo pipefail

        python_tags=()
        for tag in $PYTHON_TAGS; do
            if [[ -x "/opt/python/$tag/bin/python" ]]; then
                python_tags+=("$tag")
            else
                echo "skip: $tag is not in the image" >&2
            fi
        done
        if ((${#python_tags[@]} == 0)); then
            echo "No requested Python interpreters are available in this image" >&2
            exit 1
        fi

        work_dir="$(mktemp -d /tmp/openalpy.XXXXXXXX)"
        project="$work_dir/project"
        native_build="$work_dir/openal"
        "/opt/python/${python_tags[0]}/bin/python" \
            /source/tools/prepare_wheel_source.py /source "$project"
        cd "$project"

        echo "Building libopenal with the image toolchain..."
        # JACK and PortAudio development packages come from EPEL. Enable its
        # development dependencies too (PowerTools on AlmaLinux 8, CRB on 9+).
        dnf install -y dnf-plugins-core epel-release
        source /etc/os-release
        case "${VERSION_ID%%.*}" in
            8) dnf config-manager --set-enabled powertools ;;
            9|10) dnf config-manager --set-enabled crb ;;
        esac
        dnf install -y alsa-lib-devel pulseaudio-libs-devel pipewire-devel \
            jack-audio-connection-kit-devel portaudio-devel
        # PipeWire is built if found, not required: the pipewire in the image
        # (0.3.6) is older than the 0.3.23 openal-soft needs.
        cmake -S openal-soft -B "$native_build" \
            -DCMAKE_BUILD_TYPE=Release \
            -DBUILD_SHARED_LIBS=ON \
            -DALSOFT_EXAMPLES=OFF \
            -DALSOFT_UTILS=OFF \
            -DALSOFT_TESTS=OFF \
            -DALSOFT_REQUIRE_ALSA=ON \
            -DALSOFT_REQUIRE_PULSEAUDIO=ON \
            -DALSOFT_BACKEND_JACK=ON \
            -DALSOFT_REQUIRE_JACK=ON \
            -DALSOFT_BACKEND_PORTAUDIO=ON \
            -DALSOFT_REQUIRE_PORTAUDIO=ON \
            -DALSOFT_BACKEND_PIPEWIRE=ON
        cmake --build "$native_build" -j "$JOBS"
        test -f "$native_build/libopenal.so.1"

        for tag in "${python_tags[@]}"; do
            python="/opt/python/$tag/bin/python"

            echo "Building openal-py wheel for $tag..."
            export PATH="/opt/python/$tag/bin:$PATH"
            "$python" -m pip install --upgrade \
                "meson-python>=0.16" "meson>=1.11" "ninja>=1.11" \
                "cython>=3.0" build twine auditwheel

            raw_dir="$work_dir/raw/$tag"
            repaired_dir="$work_dir/repaired/$tag"
            mkdir -p "$raw_dir" "$repaired_dir"

            "$python" -m build \
                --wheel \
                --no-isolation \
                --skip-dependency-check \
                --outdir "$raw_dir" \
                -C "setup-args=-Dopenal_libdir=$native_build"

            "$python" -m auditwheel show "$raw_dir"/*.whl
            # The audio libraries are dlopen()ed by the backends at runtime
            # (recorded in the .note.dlopen section), so auditwheel knows
            # to leave them out of the wheel.
            "$python" -m auditwheel repair "$raw_dir"/*.whl --wheel-dir "$repaired_dir"
            for wheel in "$repaired_dir"/*.whl; do
                "$python" -m twine check "$wheel"
                cp "$wheel" /wheelhouse/
            done
        done
    '

echo "Built manylinux wheels:"
find "$RUN_DIR" -maxdepth 1 -type f -name '*.whl' -print | sort
