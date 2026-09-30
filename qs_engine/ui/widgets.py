"""CIVOLINK QS overlay widgets: help icon buttons, tooltips, popovers.

Stdlib tkinter/ttk only. Importing this module needs no display; only
instantiating widgets does. Window creation is headless-safe (returns
None instead of raising) while state (guide_text/guide_key) is always
recorded for tests.

NOTE: the import-boundary test pins tkinter to qs_engine/ui/views.py.
This module is the sanctioned overlay-widget companion to views.py and
is imported by views.py itself; if that boundary test is extended to
this companion, allow-list qs_engine/ui/widgets.py alongside views.py.
"""

import tkinter as tk
from tkinter import ttk

#: Glyphs: info severity uses circled-i, warning/question uses ?.
HELP_ICON_INFO = "\u24d8"
HELP_ICON_QUESTION = "?"

#: Compact flat style for help icons (~24-28px with width=2 + padding).
HELP_BUTTON_STYLE = "Help.TButton"

#: Hover delay before the summary tooltip appears (ms).
HELP_HOVER_DELAY_MS = 250
#: Wrap widths for popover / tooltip bodies.
HELP_POPOVER_WRAP = 420
HELP_TOOLTIP_WRAP = 320

#: Presentation tokens mirroring the CIVOLINK shell palette (views.py).
HELP_ICON_FG = "#555D6B"
HELP_ICON_HOVER_BG = "#EBF3FA"
HELP_ICON_ACCENT = "#004F9D"
HELP_ICON_BORDER = "#B8D4E3"

#: guide_key -> full guide text registry (populated by views.py).
_CONTENT = {}
#: Optional callable resolving guide_key -> text (set by views.py).
_RESOLVER = None


def register_guide(key, text):
    """Register full guide text for ``key`` (display registry only)."""
    _CONTENT[str(key)] = str(text or "")


def set_guide_resolver(func):
    """Set the ``guide_key -> text`` resolver (or None to clear)."""
    global _RESOLVER
    _RESOLVER = func


def guide_text_for(key, default=""):
    """Full guide text for ``key``; ``default`` when unknown."""
    if key is None:
        return default
    if _RESOLVER is not None:
        try:
            resolved = _RESOLVER(key)
        except Exception:
            resolved = None
        if resolved:
            return str(resolved)
    return _CONTENT.get(str(key), default)


def summary_of(text, limit=160):
    """Brief 1-2 sentence summary of full guide ``text`` for tooltips."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for stop in (". ", ".\n", "! ", "? "):
        cut = cleaned.find(stop)
        if 0 < cut <= limit:
            return cleaned[:cut + 1]
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0] + "\u2026"


def _tooltip_registry():
    """Live ToolTip instances (weak refs; dead buttons vanish)."""
    import weakref
    registry = getattr(_tooltip_registry, "_registry", None)
    if registry is None:
        registry = weakref.WeakSet()
        _tooltip_registry._registry = registry
    return registry


def _guide_registry():
    """Live PopoverGuide instances (weak refs; dead pages vanish)."""
    import weakref
    registry = getattr(_guide_registry, "_registry", None)
    if registry is None:
        registry = weakref.WeakSet()
        _guide_registry._registry = registry
    return registry


#: Backwards-compatible alias (views.py delegates to this registry).
guide_registry = _guide_registry


def close_all_popovers(except_guide=None):
    """Destroy every open popover (e.g. on sidebar view switches)."""
    for guide in list(_guide_registry()):
        if guide is not except_guide:
            try:
                guide.hide()
            except Exception:
                pass


def close_all_tooltips():
    """Destroy every visible tooltip."""
    for tip in list(_tooltip_registry()):
        try:
            tip.hide()
        except Exception:
            pass


def _ensure_help_style(widget):
    """Define the flat compact Help.TButton style (best-effort)."""
    try:
        style = ttk.Style(widget)
    except Exception:
        return
    try:
        style.configure(
            HELP_BUTTON_STYLE,
            font=("TkDefaultFont", 11, "bold"),
            padding=(2, 1),
            anchor="center",
            foreground=HELP_ICON_FG,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            HELP_BUTTON_STYLE,
            background=[("active", HELP_ICON_HOVER_BG),
                        ("pressed", HELP_ICON_BORDER),
                        ("disabled", "#F4F6F9")],
            foreground=[("active", HELP_ICON_ACCENT),
                        ("pressed", HELP_ICON_ACCENT),
                        ("disabled", HELP_ICON_FG)],
            relief=[("active", "solid"), ("pressed", "solid")],
            bordercolor=[("active", HELP_ICON_ACCENT),
                         ("pressed", HELP_ICON_ACCENT)],
        )
    except Exception:
        pass


def _guides_enabled(widget):
    """Global Help -> Show Panel Instructions flag (default True)."""
    try:
        app = widget.winfo_toplevel()
        flag = getattr(app, "show_guides", None)
        return bool(flag.get()) if flag is not None else True
    except Exception:
        return True


class ToolTip:
    """Lightweight floating summary tooltip for a widget."""

    def __init__(self, widget, text="", delay_ms=HELP_HOVER_DELAY_MS):
        self.widget = widget
        self.text = str(text or "")
        self.delay_ms = int(delay_ms)
        self._after = None
        self._tip = None
        _tooltip_registry().add(self)

    def set_text(self, text):
        """Replace the tooltip body (hides any visible tooltip)."""
        self.hide()
        self.text = str(text or "")

    @property
    def is_visible(self):
        """Whether the floating tooltip window currently exists."""
        return self._tip is not None

    def schedule(self, event=None):
        """Show the tooltip after the hover delay (no-op without text)."""
        self.cancel()
        if not self.text:
            return
        try:
            self._after = self.widget.after(
                self.delay_ms, lambda: self.show(event))
        except Exception:
            self._after = None

    def cancel(self):
        """Cancel a pending delayed show (keeps a visible tooltip)."""
        pending, self._after = self._after, None
        if pending is not None:
            try:
                self.widget.after_cancel(pending)
            except Exception:
                pass

    def show(self, event=None):
        """Create the floating tooltip; None when headless."""
        self._after = None
        self.hide()
        if not self.text:
            return None
        try:
            parent = self.widget.winfo_toplevel()
            tip = tk.Toplevel(parent)
        except Exception:
            return None
        try:
            tip.wm_overrideredirect(True)
        except Exception:
            pass
        try:
            tip.transient(parent)
        except Exception:
            pass
        try:
            ttk.Label(tip, text=self.text,
                      wraplength=HELP_TOOLTIP_WRAP,
                      justify="left", background="white",
                      foreground=HELP_ICON_FG,
                      relief="solid", borderwidth=1,
                      padding=(6, 3)).pack()
            tip.update_idletasks()
            if event is not None and hasattr(event, "x_root"):
                x = int(event.x_root) + 12
                y = int(event.y_root) + 12
            else:
                x = self.widget.winfo_rootx() + 12
                y = self.widget.winfo_rooty() + 20
            sw, sh = tip.winfo_screenwidth(), tip.winfo_screenheight()
            pw, ph = tip.winfo_reqwidth(), tip.winfo_reqheight()
            tip.geometry("+%d+%d" % (max(0, min(x, sw - pw - 4)),
                                     max(0, min(y, sh - ph - 4))))
            try:
                tip.attributes("-topmost", True)
            except Exception:
                pass
        except Exception:
            try:
                tip.destroy()
            except Exception:
                pass
            return None
        self._tip = tip
        return tip

    def hide(self):
        """Destroy the floating tooltip window, if any."""
        self.cancel()
        tip, self._tip = self._tip, None
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass


class PopoverGuide:
    """Persistent floating instruction popover for an owner button."""

    _HOVER_WRAP = HELP_POPOVER_WRAP

    def __init__(self, button, text="", title="Panel Instructions"):
        self.button = button
        self.text = str(text or "")
        self.title = str(title or "Panel Instructions")
        try:
            button.guide_text = self.text
        except Exception:
            pass
        self._popover = None
        self._pinned = False
        self._outside_binding = None
        _guide_registry().add(self)

    @property
    def is_open(self):
        """Whether the floating popover window currently exists."""
        return self._popover is not None

    @property
    def is_pinned(self):
        """Whether the open popover is sticky (click-opened)."""
        return bool(self._popover is not None and self._pinned)

    def set_enabled(self, enabled):
        """Disable the button (closing any popover) or re-enable it."""
        try:
            self.button.config(state="normal" if enabled else "disabled")
        except Exception:
            pass
        if not enabled:
            self.hide()

    def toggle(self, _event=None):
        """Click handler: close a pinned popover, else pin one open."""
        if self._popover is not None and self._pinned:
            self.hide()
        elif _guides_enabled(self.button):
            self.show(pinned=True)

    def preview(self):
        """Hover handler: show unpinned preview unless one is open."""
        if self._popover is None and _guides_enabled(self.button):
            self.show(pinned=False)

    def dismiss_hover(self):
        """Hover-exit: close unpinned previews, keep sticky ones."""
        if self._popover is not None and not self._pinned:
            self.hide()

    def hide(self):
        """Destroy the floating popover window, if any."""
        pop, self._popover = self._popover, None
        self._pinned = False
        self._uninstall_outside_close()
        if pop is not None:
            try:
                pop.destroy()
            except Exception:
                pass

    #: Backwards-compatible alias (QSApp.show closes popovers).
    close = hide


    def show(self, pinned=False):
        """Create the popover beneath the button; None when headless."""
        close_all_popovers(except_guide=self)
        self.hide()
        if not _guides_enabled(self.button):
            return None
        try:
            parent = self.button.winfo_toplevel()
            pop = tk.Toplevel(parent)
        except Exception:
            return None
        try:
            pop.wm_overrideredirect(True)
        except Exception:
            pass
        try:
            pop.transient(parent)
        except Exception:
            pass
        try:
            pop.title(self.title)
        except Exception:
            pass
        try:
            frame = ttk.Frame(pop, padding=10)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=self.text,
                      wraplength=self._HOVER_WRAP,
                      justify="left").pack(anchor="w")
        except Exception:
            try:
                pop.destroy()
            except Exception:
                pass
            return None
        pop.bind("<Escape>", lambda _e: self.hide(), add="+")
        pop.bind("<FocusOut>", lambda _e: self.hide(), add="+")
        try:
            pop.update_idletasks()
            bx = self.button.winfo_rootx()
            by = self.button.winfo_rooty()
            bh = self.button.winfo_height()
            pw, ph = pop.winfo_reqwidth(), pop.winfo_reqheight()
            sw, sh = (pop.winfo_screenwidth(), pop.winfo_screenheight())
            x = min(bx, sw - pw - 8)
            y = by + bh + 4
            if y + ph > sh - 8:
                y = max(8, by - ph - 4)
            pop.geometry("+%d+%d" % (max(8, x), max(8, y)))
            pop.lift()
            try:
                pop.attributes("-topmost", True)
            except Exception:
                pass
        except Exception:
            pass
        self._popover = pop
        self._pinned = bool(pinned)
        self._install_outside_close(pop)
        return pop

    def _install_outside_close(self, popover):
        """Close the popover when clicking anywhere outside it."""
        self._uninstall_outside_close()
        try:
            top = self.button.winfo_toplevel()

            def _on_press(event):
                widget = event.widget
                try:
                    if widget is self.button or widget is popover:
                        return
                    if str(widget).startswith(str(popover)):
                        return
                    owner = str(self.button)
                    if (str(widget) == owner
                            or str(widget).startswith(owner)):
                        return
                except Exception:
                    pass
                self.hide()

            token = top.bind("<ButtonPress-1>", _on_press, add="+")
            self._outside_binding = (top, token)
        except Exception:
            self._outside_binding = None

    def _uninstall_outside_close(self):
        """Remove the outside-click binding installed by show()."""
        binding, self._outside_binding = self._outside_binding, None
        if binding is not None:
            top, token = binding
            try:
                top.unbind("<ButtonPress-1>", token)
            except Exception:
                pass



class HelpIconButton(ttk.Button):
    """Unified panel-guide icon button (circled-i / ?)."""

    def __init__(self, parent, guide_key=None, guide_text=None,
                 summary=None, severity="info",
                 tooltip_delay_ms=HELP_HOVER_DELAY_MS,
                 popup_title="Panel Instructions",
                 command=None, **kwargs):
        if guide_text is None and guide_key is not None:
            guide_text = guide_text_for(guide_key, "")
        full_text = str(guide_text or "")
        glyph = (HELP_ICON_QUESTION
                 if str(severity).lower() in ("warn", "warning",
                                              "question", "?")
                 else HELP_ICON_INFO)
        kwargs.setdefault("style", HELP_BUTTON_STYLE)
        kwargs.setdefault("width", 2)
        kwargs["text"] = glyph
        # Record interaction state first: a display-less construction
        # must still expose the same attributes as a live widget.
        self._headless = True
        self._glyph = glyph
        self.guide_key = guide_key
        self.guide_text = full_text
        self.summary = (str(summary) if summary is not None
                        else summary_of(full_text))
        self.severity = str(severity)
        self.tooltip_delay_ms = int(tooltip_delay_ms)
        self._fallback_command = command
        self._guide = None
        self._tooltip = None
        try:
            super().__init__(parent, **kwargs)
        except Exception:
            return
        self._headless = False
        _ensure_help_style(self)
        self._guide = PopoverGuide(self, full_text, title=popup_title)
        self._tooltip = ToolTip(self, self.summary,
                                delay_ms=self.tooltip_delay_ms)
        self.config(command=self.toggle)
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<Escape>", lambda _e: self.close(), add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")

    @property
    def guide(self):
        """The underlying PopoverGuide (None when headless)."""
        return self._guide

    @property
    def tooltip(self):
        """The underlying ToolTip (None when headless)."""
        return self._tooltip

    @property
    def is_open(self):
        """Whether the sticky popover is currently open."""
        try:
            return bool(self._guide is not None and self._guide.is_open)
        except Exception:
            return False

    def set_fallback_command(self, command):
        """Command invoked on click when no guide text is available."""
        self._fallback_command = command

    def toggle(self, _event=None):
        """Click: toggle the sticky popover (or run fallback)."""
        if getattr(self, "_headless", False):
            if callable(self._fallback_command):
                self._fallback_command()
            return
        self._tooltip.hide()
        if self.guide_text:
            self._guide.toggle()
        elif callable(self._fallback_command):
            try:
                self._fallback_command()
            except Exception:
                pass

    def close(self):
        """Destroy any open popover and tooltip for this button."""
        try:
            if self._guide is not None:
                self._guide.hide()
        except Exception:
            pass
        try:
            if self._tooltip is not None:
                self._tooltip.hide()
        except Exception:
            pass

    def _on_enter(self, event=None):
        """Hover enter: schedule summary tooltip (unless pinned)."""
        if getattr(self, "_headless", False):
            return
        try:
            if self._guide is not None and self._guide.is_open:
                return
            if not _guides_enabled(self):
                return
            self._tooltip.schedule(event)
        except Exception:
            pass

    def _on_leave(self, _event=None):
        """Hover exit: destroy tooltip; dismiss hover previews."""
        if getattr(self, "_headless", False):
            return
        try:
            self._tooltip.hide()
        except Exception:
            pass
        try:
            if self._guide is not None:
                self._guide.dismiss_hover()
        except Exception:
            pass

    def _on_destroy(self, _event=None):
        """Widget teardown: never leave orphan floating windows."""
        try:
            self.close()
        except Exception:
            pass


#: Backwards-compatible alias for the alternate class name.
HelpIconLabel = HelpIconButton


__all__ = [
    "HELP_ICON_INFO",
    "HELP_ICON_QUESTION",
    "HELP_BUTTON_STYLE",
    "HELP_HOVER_DELAY_MS",
    "HELP_POPOVER_WRAP",
    "HELP_TOOLTIP_WRAP",
    "HelpIconButton",
    "HelpIconLabel",
    "PopoverGuide",
    "ToolTip",
    "close_all_popovers",
    "close_all_tooltips",
    "guide_registry",
    "guide_text_for",
    "register_guide",
    "set_guide_resolver",
    "summary_of",
]

