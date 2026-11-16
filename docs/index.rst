openal-py
=========

Spatial audio for Python, with managed resources, streaming playback, and access
to the OpenAL object model. Use :class:`~openal_py.AudioEngine` for everyday
playback, or work directly with devices, contexts, sources, and buffers when you
need more control.

Platform wheels bundle OpenAL Soft by default. The binding falls back to system
OpenAL when the bundle is unavailable or detects no playback devices.

Installation
------------

.. code-block:: console

   pip install openal-py

For FLAC, OGG, and other formats supported by SoundFile, install the optional
decoder dependency:

.. code-block:: console

   pip install 'openal-py[soundfile]'

Mono/stereo 8-bit and 16-bit PCM WAV files work without this extra.

Play a sound
------------

.. code-block:: python

   from openal_py import AudioEngine

   with AudioEngine() as audio:
       sound = audio.load("sound.wav")
       voice = audio.play(sound, gain=0.8, position=(2, 0, -5))
       voice.wait()

A :class:`~openal_py.Sound` is a reusable audio asset. Each call to
:meth:`~openal_py.AudioEngine.play` creates a :class:`~openal_py.Voice` with its
own position, gain, pitch, and playback controls. Closing the engine releases its
playback resources.

``wait()`` is useful for small scripts. In an application loop, call
:meth:`~openal_py.AudioEngine.update` regularly and inspect ``voice.finished``
instead of blocking. Engine operations run on the thread that created it.

Stream longer audio
-------------------

Streaming decodes audio in chunks and reuses a bounded pool of OpenAL buffers:

.. code-block:: python

   import time
   from openal_py import AudioEngine, SoundFileStream

   with AudioEngine() as audio, SoundFileStream("music.flac") as stream:
       with audio.play_stream(stream) as voice:
           while voice.active:
               audio.update()
               time.sleep(0.01)

The engine refills streams during ``update()``; it does not start a background
thread. Stream inputs are borrowed by default, so keep them open until playback
has stopped, as the nested resource blocks do above.

Subclass :class:`~openal_py.PCMStream` to provide generated samples, an existing
decoder, or a queue fed by a producer. Supply a fixed format and sample rate, and
implement ``read_frames(count)``. Return complete PCM frames, empty bytes for EOF,
or ``None`` when data is temporarily unavailable. Reads must return promptly.

Explore the API
---------------

* :class:`~openal_py.AudioEngine`, :class:`~openal_py.Sound`, and
  :class:`~openal_py.Voice`: managed playback and reusable assets.
* :class:`~openal_py.PCMStream`, :class:`~openal_py.SoundFileStream`, and
  :class:`~openal_py.StreamingVoice`: extensible streaming inputs and playback.
* :class:`~openal_py.Device`, :class:`~openal_py.Context`,
  :class:`~openal_py.Source`, and :class:`~openal_py.Buffer`: explicit OpenAL
  resource management. Use ``ctx.activate()`` for context-dependent operations;
  resource blocks manage lifetime separately.
* :class:`~openal_py.Listener`, :class:`~openal_py.Effect`, and
  :class:`~openal_py.Filter`: spatial audio and device-supported effects.
* :class:`~openal_py.LoopbackDevice` and :class:`~openal_py.CaptureDevice`:
  offline rendering and audio capture where supported.

Browse the :doc:`examples/index` for runnable scripts, including custom PCM
streams and adapters for already-open SoundFile readers. Each page includes
the source code and a download link.

.. toctree::
   :maxdepth: 2
   :caption: Documentation

   examples/index
   api

Building these docs
-------------------

From a source checkout with its build prerequisites available:

.. code-block:: console

   pip install '.[docs]'
   ALSOFT_DRIVERS=null python -m sphinx -W -b html docs docs/_build/html

API documentation imports the compiled binding, so a usable OpenAL library must
be available. On Windows PowerShell, set ``$env:ALSOFT_DRIVERS = "null"`` before
running the ``python -m sphinx`` command. Generated HTML is written to
``docs/_build/html/``.
