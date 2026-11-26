import os
import tempfile

# Keep all test data out of the real %LOCALAPPDATA% folder.
os.environ.setdefault("ANKI_SCRIBE_DATA", tempfile.mkdtemp(prefix="anki-scribe-tests-"))
