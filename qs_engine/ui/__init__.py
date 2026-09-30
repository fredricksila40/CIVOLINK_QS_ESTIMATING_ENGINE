"""Desktop UI layer (Phase 13): MVP over the QS engine.

controllers.py is framework-agnostic (string in, view-model out, engine
decides — fully headless-testable). views.py binds those controllers to
stdlib tkinter widgets. To swap toolkits, rewrite views.py only.
"""

from . import controllers, viewmodels

__all__ = ["controllers", "viewmodels"]
