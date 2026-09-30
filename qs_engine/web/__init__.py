"""CIVOLINK QS web layer (Phase 18): FastAPI facade over controllers.

No toolkit, no calculation here — HTTP shaping only. Tkinter UI,
controllers, adapters, and parsers remain untouched.
"""

from .api import app

__all__ = ["app"]
