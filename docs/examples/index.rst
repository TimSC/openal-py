Examples
========

Browse or download the runnable scripts below. Code is included directly from
``examples/`` so these pages stay in sync with the scripts.

Run commands from the repository root after installing ``openal-py``. File
loading examples may require ``pip install 'openal-py[soundfile]'``. Playback
examples use your audio device; loopback examples render without audio hardware.
The documentation build displays source code without executing the examples.

.. toctree::
   :maxdepth: 1
   :caption: Engine and streaming

   11_audio_engine
   12_extending_engine
   14_engine_streaming
   15_soundfile_pcm_stream

.. toctree::
   :maxdepth: 1
   :caption: OpenAL objects

   01_quickstart
   02_devices
   03_listeners
   04_buffers
   05_sources
   06_lifecycle
   07_streaming
   13_streaming_helper

.. toctree::
   :maxdepth: 1
   :caption: Rendering, effects, and capture

   08_offline_rendering
   09_effects
   10_capture
