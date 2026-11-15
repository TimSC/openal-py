# The OpenAL-soft checkout lives in the 'openal-soft' git submodule; its
# build tree is at <repo-root>/openal-soft/build by default.
repo_root = meson.project_source_root()
openal_libdir = repo_root / get_option('openal_libdir')

openal_inc = include_directories('../../../openal-soft/include')
local_inc = include_directories('.')

cc = meson.get_compiler('c')
openal_dep = cc.find_library('openal', dirs: [openal_libdir], required: true)

# Meson's built-in cython transpiler does not forward include directories,
# and _al_api.pxd lives next to _core.pyx; transpile explicitly.
cy_bin = find_program('cython')
core_c = custom_target('core_c',
    input: '_core.pyx',
    output: 'core.c',
    command: [cy_bin, '-3', '-I', '@CURRENT_SOURCE_DIR@', '-o', '@OUTPUT@', '@INPUT@'],
)

is_windows = host_machine.system() == 'windows'
link_args = []
if not is_windows
    # Find the bundled libopenal next to the extension module at runtime.
    link_args = ['-Wl,-rpath,$ORIGIN']
endif

core = py.extension_module(
    '_core',
    [core_c, '_api_table.c'],
    include_directories: [local_inc, openal_inc],
    dependencies: openal_dep,
    link_args: link_args,
    install: true,
    subdir: 'openal_py',
    gnu_symbol_visibility: 'default',  # dlopen(NULL) must see libopenal symbols
)

py.install_sources(
    ['__init__.py', '_errors.py', '_constants.py', '_finalize.py',
     'device.py', 'context.py', 'listener.py', 'source.py', 'buffer.py'],
    subdir: 'openal_py',
)



# Bundle the OpenAL shared library into the package directory.
if get_option('bundle_openal')
    if is_windows
        libfile = openal_libdir / 'openal.dll'
    elif host_machine.system() == 'darwin'
        libfile = openal_libdir / 'libopenal.1.dylib'
    else
        libfile = openal_libdir / 'libopenal.so.1'
    endif
    install_data(libfile, install_dir: py.get_install_dir() / 'openal_py')
endif
