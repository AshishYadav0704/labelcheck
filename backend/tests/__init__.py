"""Test package. Points storage at a throwaway folder before the app is imported."""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="labelcheck-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")
