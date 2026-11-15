project(
    'openal-py',
    'c', 'cython',
    version: '0.1.0',
    meson_version: '>=1.11',
    default_options: [
        'c_std=c11',
        'warning_level=1',
    ],
)

py = import('python').find_installation(pure: false)

subdir('src/openal_py')

# Ship the example scripts alongside the package for discovery in the wheel.
install_subdir(
    'examples',
    install_dir: py.get_install_dir() / 'openal_py',
    install_tag: 'runtime',
)
