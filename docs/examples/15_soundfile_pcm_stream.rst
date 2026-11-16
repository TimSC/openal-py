Wrapping an open SoundFile
==========================

Borrow an already-open SoundFile reader, expose PCM frames, and stream playback.

.. code-block:: console

   python examples/15_soundfile_pcm_stream.py

Install ``openal-py[soundfile]`` first. With no filename, the example plays a
short generated tone. To play your own file:

.. code-block:: console

   python examples/15_soundfile_pcm_stream.py music.flac

The reader remains owned by its caller. For ordinary file paths, use the built-in
:class:`~openal_py.SoundFileStream` adapter.

:download:`Download 15_soundfile_pcm_stream.py <../../examples/15_soundfile_pcm_stream.py>`

.. literalinclude:: ../../examples/15_soundfile_pcm_stream.py
   :language: python
   :linenos:
