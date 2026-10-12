"""
OverCut: Shortcut Overlay Manager (PyQt6)
=========================================
Press your hotkey from anywhere to summon the overlay.
Manage shortcuts by category in the manager window.
Minimises to the system tray.

Requirements:
    pip install PyQt6 keyboard
Windows:
    Run as Administrator for global hotkey support.

Design system (see the "Design tokens" section):
    - Type scale in integer pixels: 12 (caption), 13 (body), 16 (title)
    - Two weights only: Normal and DemiBold
    - Spacing scale: 4 / 8 / 12 / 16 / 24
    - Radii: 4 (controls), 6 (panels), 8 (overlay)
    - One accent colour, one border colour, three text levels
    - No font properties in the stylesheet: fonts are set in code so Qt's
      normal text pipeline (and hinting preference) is never overridden

Fonts:
    The UI uses Segoe UI Variable / Segoe UI when present. Bundled fonts in a
    fonts/ folder next to this script (or exe) are still registered and are
    used as a fallback (Inter, JetBrains Mono).
    PyInstaller: --add-data "fonts;fonts"
"""

import sys, json, os, re, html
from string import Template

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog,
    QVBoxLayout, QHBoxLayout, QStackedLayout,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QScrollArea, QFrame,
    QSystemTrayIcon, QMenu, QStackedWidget, QAbstractButton, QTextEdit,
    QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QRectF, QPointF, QSize, QTimer, QEvent,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QFontMetrics, QColor, QPalette,
    QIcon, QPixmap, QPainter, QPen, QBrush,
)

try:
    import keyboard as kb_lib
    HOTKEY_OK = True
except ImportError:
    HOTKEY_OK = False

import ctypes
import winreg

# ─────────────────────────────────────────────────────────────────────────────
#  Windows startup registry helpers
# ─────────────────────────────────────────────────────────────────────────────

_STARTUP_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_REG_NAME = "OverCut"

def _get_startup_enabled() -> bool:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, _APP_REG_NAME)
        winreg.CloseKey(key)
        return True
    except (FileNotFoundError, OSError):
        return False

def _set_startup(enabled: bool) -> None:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            exe = sys.executable
            winreg.SetValueEx(key, _APP_REG_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, _APP_REG_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError as e:
        print(f"[Startup] Registry error: {e}")


def _ensure_admin():
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1)
            sys.exit()
    except Exception:
        pass

_ensure_admin()

# ─────────────────────────────────────────────────────────────────────────────
#  Design tokens
# ─────────────────────────────────────────────────────────────────────────────

# Spacing scale
S1, S2, S3, S4, S5 = 4, 8, 12, 16, 24

# Control height and radii
CONTROL_H      = 32
RADIUS_CONTROL = 4
RADIUS_PANEL   = 6
RADIUS_MAX     = 8

# Type scale (integer pixels, DPI scaling is handled by Qt)
FS_CAPTION = 12
FS_BODY    = 13
FS_TITLE   = 16

# Palette. One accent, one background, one surface, one border.
# text / text2 / text3 are the three emphasis levels.
_THEMES = {
    "dark": {
        "bg":            "#151517",
        "surface":       "#1d1d20",
        "hover":         "#27272b",
        "border":        "#313136",
        "scrollbar":     "#3c3c42",
        "text":          "#ececef",
        "text2":         "#b4b4bc",
        "text3":         "#8a8a93",
        "accent":        "#3b72e0",
        "accent_hover":  "#4a80ec",
        "accent_pressed":"#2f5fc4",
        "accent_fg":     "#7aa2ff",
        "accent_subtle": "#1f2b46",
        "on_accent":     "#ffffff",
        "danger":        "#f0625d",
    },
    "light": {
        "bg":            "#f3f3f5",
        "surface":       "#ffffff",
        "hover":         "#ececf0",
        "border":        "#d9d9df",
        "scrollbar":     "#c9c9d1",
        "text":          "#1b1b1f",
        "text2":         "#4a4a53",
        "text3":         "#6b6b75",
        "accent":        "#2563eb",
        "accent_hover":  "#1d54d0",
        "accent_pressed":"#1a47b0",
        "accent_fg":     "#1f55d6",
        "accent_subtle": "#dce7fc",
        "on_accent":     "#ffffff",
        "danger":        "#c4302b",
    },
}

def _load_theme_pref() -> str:
    """Read theme from data file before full app init."""
    try:
        base = (os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "overcut_data.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f).get("theme", "dark")
    except Exception:
        pass
    return "dark"

CURRENT_THEME: str = _load_theme_pref()
P: dict             = _THEMES.get(CURRENT_THEME, _THEMES["dark"])

# ─────────────────────────────────────────────────────────────────────────────
#  Fonts
#  CRITICAL: call _load_bundled_fonts() AFTER QApplication(), BEFORE any widget.
# ─────────────────────────────────────────────────────────────────────────────

_LOADED_FAMILIES: list[str] = []

def _load_bundled_fonts() -> list[str]:
    """Registers every TTF/OTF in fonts/ with Qt and prints the family names."""
    if getattr(sys, "frozen", False):
        candidates = [sys._MEIPASS, os.path.dirname(sys.executable)]
    else:
        candidates = [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]

    loaded: list[str] = []
    for base in candidates:
        fonts_dir = os.path.join(base, "fonts")
        if os.path.isdir(fonts_dir):
            print(f"[Fonts] Loading from: {fonts_dir}")
            for fname in sorted(os.listdir(fonts_dir)):
                if fname.lower().endswith((".ttf", ".otf")):
                    path = os.path.join(fonts_dir, fname)
                    fid  = QFontDatabase.addApplicationFont(path)
                    if fid >= 0:
                        families = QFontDatabase.applicationFontFamilies(fid)
                        loaded.extend(families)
                        print(f"  [Fonts] OK    {fname}  ->  {families}")
                    else:
                        print(f"  [Fonts] FAIL  {fname}")
            break
    else:
        print("[Fonts] No fonts/ directory found, using system fonts.")

    return loaded

_UI_CANDIDATES   = ["Segoe UI Variable Text", "Segoe UI", "Inter"]
_MONO_CANDIDATES = ["Cascadia Mono", "Consolas", "JetBrains Mono"]

def _best_family(candidates: list[str]) -> str:
    available = set(QFontDatabase.families())
    for c in candidates:
        if c in available:
            return c
    return candidates[-1]

def _smooth(f: QFont) -> QFont:
    """Antialiased, vertically hinted text for every font in the app."""
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    f.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    return f

# role -> (pixel size, semibold, monospace)
_ROLES = {
    "caption":        (FS_CAPTION, False, False),
    "caption_strong": (FS_CAPTION, True,  False),
    "body":           (FS_BODY,    False, False),
    "strong":         (FS_BODY,    True,  False),
    "title":          (FS_TITLE,   True,  False),
    "key":            (FS_CAPTION, False, True),   # key badges
    "mono":           (FS_BODY,    False, True),   # key column, hotkey input
}

def role_font(role: str) -> QFont:
    px, bold, mono = _ROLES[role]
    f = QFont(_best_family(_MONO_CANDIDATES if mono else _UI_CANDIDATES))
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return _smooth(f)

# ─────────────────────────────────────────────────────────────────────────────
#  Palette + stylesheet (small, token driven)
# ─────────────────────────────────────────────────────────────────────────────

def build_palette() -> QPalette:
    pal = QPalette()
    c = lambda k: QColor(P[k])
    R = QPalette.ColorRole
    pal.setColor(R.Window,          c("bg"))
    pal.setColor(R.WindowText,      c("text"))
    pal.setColor(R.Base,            c("surface"))
    pal.setColor(R.AlternateBase,   c("hover"))
    pal.setColor(R.Text,            c("text"))
    pal.setColor(R.Button,          c("surface"))
    pal.setColor(R.ButtonText,      c("text"))
    pal.setColor(R.ToolTipBase,     c("surface"))
    pal.setColor(R.ToolTipText,     c("text"))
    pal.setColor(R.Highlight,       c("accent"))
    pal.setColor(R.HighlightedText, c("on_accent"))
    pal.setColor(R.PlaceholderText, c("text3"))
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, c("text3"))
    return pal


_QSS = Template("""
QToolTip {
    background: $surface; color: $text;
    border: 1px solid $border; padding: ${s1}px ${s2}px;
}

QMenu {
    background: $surface; color: $text;
    border: 1px solid $border; padding: ${s1}px;
}
QMenu::item { padding: ${s2}px ${s5}px ${s2}px ${s3}px; border-radius: ${r_control}px; }
QMenu::item:selected { background: $hover; }
QMenu::separator { height: 1px; background: $border; margin: ${s1}px 0; }

QScrollBar:vertical { background: transparent; width: ${s2}px; margin: 0; }
QScrollBar::handle:vertical {
    background: $scrollbar; border-radius: ${s1}px; min-height: ${s5}px;
}
QScrollBar::handle:vertical:hover { background: $text3; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { height: 0; }

QPushButton {
    background: $surface; color: $text;
    border: 1px solid $border; border-radius: ${r_control}px;
    padding: 0 ${s3}px;
}
QPushButton:hover    { background: $hover; }
QPushButton:pressed  { background: $border; }
QPushButton:focus    { border-color: $accent; }
QPushButton:disabled { color: $text3; background: $surface; }

QPushButton[variant="primary"] {
    background: $accent; border-color: $accent; color: $on_accent;
}
QPushButton[variant="primary"]:hover    { background: $accent_hover;   border-color: $accent_hover; }
QPushButton[variant="primary"]:pressed  { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton[variant="primary"]:focus    { border-color: $text; }
QPushButton[variant="primary"]:disabled { background: $hover; border-color: $border; color: $text3; }

QPushButton[variant="danger"]         { color: $danger; }
QPushButton[variant="danger"]:hover   { border-color: $danger; }
QPushButton[variant="danger"]:disabled { color: $text3; }

QPushButton[seg="true"] {
    background: transparent; border: none; border-radius: 3px;
    padding: 0 ${s3}px; color: $text2; min-width: ${s5}px;
}
QPushButton[seg="true"]:hover   { color: $text; background: transparent; }
QPushButton[seg="true"]:pressed { background: $hover; }
QPushButton[seg="true"]:checked { background: $accent_subtle; color: $text; }
QPushButton[seg="true"]:focus   { border: none; }

QLineEdit {
    background: $surface; border: 1px solid $border;
    border-radius: ${r_control}px; padding: 0 ${s2}px;
    selection-background-color: $accent; selection-color: $on_accent;
}
QLineEdit:focus    { border-color: $accent; }
QLineEdit:disabled { color: $text3; }
QLineEdit[listening="true"] { background: $accent_subtle; border-color: $accent; }
QLineEdit[embedded="true"]  { background: transparent; border: none; padding: 0; }

QFrame#Card {
    background: $surface; border: 1px solid $border;
    border-radius: ${r_panel}px;
}
QFrame#OverlayCard {
    background: $surface; border: 1px solid $border;
    border-radius: ${r_max}px;
}
QFrame#BarBottom { background: $surface; border: none; border-bottom: 1px solid $border; }
QFrame#BarTop    { background: $surface; border: none; border-top: 1px solid $border; }
QFrame#Divider   { background: $border; border: none; }
QFrame#Segmented {
    background: $bg; border: 1px solid $border; border-radius: ${r_control}px;
}

QListWidget#Sidebar {
    background: transparent; border: none; outline: none; padding: ${s1}px;
}
QListWidget#Sidebar::item {
    padding: 0 ${s2}px; border-radius: ${r_control}px; color: $text2;
}
QListWidget#Sidebar::item:hover    { background: $hover; color: $text; }
QListWidget#Sidebar::item:selected { background: $accent_subtle; color: $text; }

QTreeWidget#Table { background: transparent; border: none; outline: none; }
QTreeWidget#Table::item { padding: 0 ${s2}px; }
QTreeWidget#Table::item:hover    { background: $hover; }
QTreeWidget#Table::item:selected { background: $accent_subtle; color: $text; }
QHeaderView::section {
    background: transparent; color: $text3; border: none;
    border-bottom: 1px solid $border; padding: 0 ${s2}px 0 ${header_inset}px;
}

QTextEdit#Doc {
    background: $surface; border: 1px solid $border;
    border-radius: ${r_panel}px; padding: ${s2}px;
    selection-background-color: $accent; selection-color: $on_accent;
}

QWidget#Row { background: transparent; border-left: 2px solid transparent; }
QWidget#Row:hover { background: $hover; }
QWidget#Row[selected="true"] { background: $accent_subtle; border-left: 2px solid $accent; }

QLabel[badge="true"] {
    background: $hover; color: $text2;
    border: 1px solid $border; border-radius: ${r_control}px;
    padding: 0 ${s2}px;
}
QLabel[badge="true"][selected="true"] {
    background: $surface; color: $accent_fg; border-color: $accent;
}
""")

def build_qss() -> str:
    return _QSS.substitute(
        P, s1=S1, s2=S2, s3=S3, s4=S4, s5=S5,
        r_control=RADIUS_CONTROL, r_panel=RADIUS_PANEL, r_max=RADIUS_MAX,
        header_inset=S2 + 3)   # Qt adds a 3 px text margin to tree items

# ─────────────────────────────────────────────────────────────────────────────
#  Data
# ─────────────────────────────────────────────────────────────────────────────

def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(_app_dir(), "overcut_data.json")

DEFAULT_DATA = {
    "trigger_key": "ctrl+shift+space",
    "categories": {
        "Jupyter Notebook": [
            {"key": "Shift+Enter",   "action": "Run cell — move to next"},
            {"key": "Ctrl+Enter",    "action": "Run cell — stay"},
            {"key": "Alt+Enter",     "action": "Run cell — insert below"},
            {"key": "Esc",           "action": "Enter Command mode"},
            {"key": "Enter",         "action": "Enter Edit mode"},
            {"key": "A",             "action": "[CMD] Insert cell Above"},
            {"key": "B",             "action": "[CMD] Insert cell Below"},
            {"key": "D D",           "action": "[CMD] Delete cell"},
            {"key": "Z",             "action": "[CMD] Undo cell deletion"},
            {"key": "M",             "action": "[CMD] Convert to Markdown"},
            {"key": "Y",             "action": "[CMD] Convert to Code"},
            {"key": "Shift+M",       "action": "[CMD] Merge selected cells"},
            {"key": "Tab",           "action": "[EDIT] Autocomplete"},
            {"key": "Shift+Tab",     "action": "[EDIT] Show docstring"},
            {"key": "Ctrl+/",        "action": "[EDIT] Toggle comment"},
            {"key": "Ctrl+Shift+-",  "action": "[EDIT] Split cell at cursor"},
            {"key": "Ctrl+S",        "action": "Save notebook"},
        ]
    }
}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_DATA)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ─────────────────────────────────────────────────────────────────────────────
#  Hotkey thread
# ─────────────────────────────────────────────────────────────────────────────

class HotkeyThread(QThread):
    triggered = pyqtSignal()

    def __init__(self, hotkey: str):
        super().__init__()
        self.hotkey   = hotkey
        self._running = True

    def run(self):
        if not HOTKEY_OK:
            return
        try:
            kb_lib.add_hotkey(self.hotkey, self.triggered.emit)
            while self._running:
                self.msleep(100)
        except Exception as e:
            print(f"Hotkey error: {e}")

    def stop(self):
        self._running = False
        if HOTKEY_OK:
            try:
                kb_lib.remove_all_hotkeys()
            except Exception:
                pass
        self.quit()
        self.wait()

# ─────────────────────────────────────────────────────────────────────────────
#  Reusable components
# ─────────────────────────────────────────────────────────────────────────────

def set_prop(widget: QWidget, name: str, value: str) -> None:
    """Set a dynamic property and re-evaluate the stylesheet for it."""
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


_TONES = {
    "primary":   "text",
    "secondary": "text2",
    "tertiary":  "text3",
    "accent":    "accent_fg",
    "danger":    "danger",
}


class Label(QLabel):
    """Text with a type role and an emphasis tone. No stylesheet involved."""

    def __init__(self, text: str = "", role: str = "body",
                 tone: str = "primary", parent=None):
        super().__init__(text, parent)
        self.setFont(role_font(role))
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.WindowText, QColor(P[_TONES[tone]]))
        self.setPalette(pal)


class SectionHeader(Label):
    def __init__(self, text: str, parent=None):
        super().__init__(text, "caption_strong", "tertiary", parent)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class AppCard(QFrame):
    """A bordered surface. Use only where it groups content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


class AppButton(QPushButton):
    """variant: 'secondary' (default), 'primary' or 'danger'."""

    def __init__(self, text: str = "", variant: str = "secondary", parent=None):
        super().__init__(text, parent)
        self.setProperty("variant", variant)
        self.setFont(role_font("body"))
        self.setFixedHeight(CONTROL_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Keyboard focus ring only; mouse clicks should not leave a ring behind.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)


class AppLineEdit(QLineEdit):
    def __init__(self, text: str = "", placeholder: str = "", parent=None):
        super().__init__(text, parent)
        self.setPlaceholderText(placeholder)
        self.setFont(role_font("body"))
        self.setFixedHeight(CONTROL_H)


class KeyBadge(QLabel):
    """Monospace key label, e.g. Ctrl+Shift+S."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("badge", "true")
        self.setProperty("selected", "false")
        self.setFont(role_font("key"))
        self.setFixedHeight(S5 - S1)           # 20
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class IconButton(QPushButton):
    """Vector icon button (drawn with QPainter, sharp at any DPI)."""

    def __init__(self, kind: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(S5 + S1, S5 + S1)    # 28
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hot = self.underMouse() or self.hasFocus()
        if hot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(P["hover"]))
            p.drawRoundedRect(QRectF(self.rect()), RADIUS_CONTROL, RADIUS_CONTROL)
        pen = QPen(QColor(P["text"] if hot else P["text2"]), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx, cy, r = self.width() / 2, self.height() / 2, 5
        if self._kind == "close":
            p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            p.drawLine(QPointF(cx - r, cy + r), QPointF(cx + r, cy - r))
        p.end()


class SearchIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(S4, S4)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(P["text3"]), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(1.75, 1.75, 9, 9))
        p.drawLine(QPointF(9.5, 9.5), QPointF(14, 14))
        p.end()


class Switch(QAbstractButton):
    """On/off toggle. Space toggles when focused."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(36, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, on = self.width(), self.height(), self.isChecked()
        edge = P["text"] if self.hasFocus() else (P["accent"] if on else P["text3"])
        p.setPen(QPen(QColor(edge), 1))
        p.setBrush(QColor(P["accent"]) if on else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)
        d = 12
        x = w - S1 - d if on else S1
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P["on_accent"] if on else P["text3"]))
        p.drawEllipse(QRectF(x, (h - d) / 2, d, d))
        p.end()


class Segmented(QFrame):
    """Small exclusive option group, e.g. Dark | Light."""
    changed = pyqtSignal(str)

    def __init__(self, options: list[str], current: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.setFixedHeight(CONTROL_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for opt in options:
            b = QPushButton(opt)
            b.setProperty("seg", "true")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setChecked(opt == current)
            b.setFont(role_font("body"))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setSizePolicy(QSizePolicy.Policy.Preferred,
                            QSizePolicy.Policy.Expanding)
            b.clicked.connect(lambda _=False, o=opt: self.changed.emit(o))
            lay.addWidget(b)

# ─────────────────────────────────────────────────────────────────────────────
#  Key capture input
# ─────────────────────────────────────────────────────────────────────────────

class KeyCaptureInput(AppLineEdit):
    """Click to enter listening mode, press any key/mouse combo to capture it."""

    _MOUSE = {
        Qt.MouseButton.MiddleButton: "Mouse3",
        Qt.MouseButton.BackButton:   "Mouse4",
        Qt.MouseButton.ForwardButton:"Mouse5",
        Qt.MouseButton.TaskButton:   "Mouse6",
        Qt.MouseButton.ExtraButton4: "Mouse7",
        Qt.MouseButton.ExtraButton5: "Mouse8",
    }
    _NUMPAD = {
        Qt.Key.Key_0: "Num0", Qt.Key.Key_1: "Num1", Qt.Key.Key_2: "Num2",
        Qt.Key.Key_3: "Num3", Qt.Key.Key_4: "Num4", Qt.Key.Key_5: "Num5",
        Qt.Key.Key_6: "Num6", Qt.Key.Key_7: "Num7", Qt.Key.Key_8: "Num8",
        Qt.Key.Key_9: "Num9",
        Qt.Key.Key_Plus:     "Num+",  Qt.Key.Key_Minus:    "Num-",
        Qt.Key.Key_Asterisk: "Num*",  Qt.Key.Key_Slash:    "Num/",
        Qt.Key.Key_Period:   "Num.",  Qt.Key.Key_Enter:    "NumEnter",
        Qt.Key.Key_Delete:   "NumDel",Qt.Key.Key_Insert:   "Num0",
        Qt.Key.Key_Home:     "Num7",  Qt.Key.Key_End:      "Num1",
        Qt.Key.Key_PageUp:   "Num9",  Qt.Key.Key_PageDown: "Num3",
        Qt.Key.Key_Left:     "Num4",  Qt.Key.Key_Right:    "Num6",
        Qt.Key.Key_Up:       "Num8",  Qt.Key.Key_Down:     "Num2",
        Qt.Key.Key_Clear:    "Num5",
    }
    _SPECIAL = {
        Qt.Key.Key_Return:    "Enter",  Qt.Key.Key_Enter:    "NumEnter",
        Qt.Key.Key_Tab:       "Tab",    Qt.Key.Key_Backspace: "Backspace",
        Qt.Key.Key_Delete:    "Delete", Qt.Key.Key_Insert:   "Insert",
        Qt.Key.Key_Home:      "Home",   Qt.Key.Key_End:      "End",
        Qt.Key.Key_PageUp:    "PageUp", Qt.Key.Key_PageDown: "PageDown",
        Qt.Key.Key_Left:      "Left",   Qt.Key.Key_Right:    "Right",
        Qt.Key.Key_Up:        "Up",     Qt.Key.Key_Down:     "Down",
        Qt.Key.Key_Space:     "Space",
        Qt.Key.Key_F1:  "F1",  Qt.Key.Key_F2:  "F2",  Qt.Key.Key_F3:  "F3",
        Qt.Key.Key_F4:  "F4",  Qt.Key.Key_F5:  "F5",  Qt.Key.Key_F6:  "F6",
        Qt.Key.Key_F7:  "F7",  Qt.Key.Key_F8:  "F8",  Qt.Key.Key_F9:  "F9",
        Qt.Key.Key_F10: "F10", Qt.Key.Key_F11: "F11", Qt.Key.Key_F12: "F12",
        Qt.Key.Key_Print:      "PrintScr",
        Qt.Key.Key_ScrollLock: "ScrollLock",
        Qt.Key.Key_Pause:      "Pause",
        Qt.Key.Key_CapsLock:   "CapsLock",
    }
    _MODS = (
        Qt.Key.Key_Control, Qt.Key.Key_Shift,
        Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
    )

    _IDLE_HINT      = "Click to capture"
    _LISTENING_HINT = "Press a key or mouse button"

    def __init__(self, parent=None):
        super().__init__("", self._IDLE_HINT, parent)
        self.setFont(role_font("mono"))
        self.setReadOnly(True)
        self._listening = False
        self.setProperty("listening", "false")

    # ── Events ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if not self._listening:
            self._start_listening()
        # Left/right clicks are UI actions while listening: ignore them.
        event.accept()

    def keyPressEvent(self, event):
        if not self._listening:
            super().keyPressEvent(event)
            return
        key  = event.key()
        mods = event.modifiers()
        if key in self._MODS:
            return
        if key == Qt.Key.Key_Escape:
            self._cancel()
            return
        is_numpad = bool(mods & Qt.KeyboardModifier.KeypadModifier)
        clean_mods = mods & ~Qt.KeyboardModifier.KeypadModifier
        mod_str = self._mods(clean_mods)
        if is_numpad:
            key_name = self._NUMPAD.get(key, "Num?")
        else:
            key_name = self._SPECIAL.get(key) or (
                event.text().upper() if event.text().isprintable()
                else f"Key{key}")
        combo = f"{mod_str}+{key_name}" if mod_str else key_name
        self._commit(combo)

    def eventFilter(self, obj, event):
        """Global mouse filter, active only while listening."""
        if self._listening and event.type() == QEvent.Type.MouseButtonPress:
            btn = event.button()
            if btn in self._MOUSE:
                mods  = self._mods(event.modifiers())
                name  = self._MOUSE[btn]
                combo = f"{mods}+{name}" if mods else name
                self._commit(combo)
                return True  # consume event
        return False

    def focusOutEvent(self, event):
        if self._listening:
            self._cancel()
        super().focusOutEvent(event)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_listening(self, on: bool):
        self._listening = on
        self.setPlaceholderText(self._LISTENING_HINT if on else self._IDLE_HINT)
        set_prop(self, "listening", "true" if on else "false")

    def _start_listening(self):
        self.setText("")
        self._set_listening(True)
        QApplication.instance().installEventFilter(self)

    def _commit(self, combo: str):
        self.setText(combo)
        self._set_listening(False)
        QApplication.instance().removeEventFilter(self)

    def _cancel(self):
        self._set_listening(False)
        QApplication.instance().removeEventFilter(self)

    @staticmethod
    def _mods(m: Qt.KeyboardModifier) -> str:
        parts = []
        if m & Qt.KeyboardModifier.ControlModifier: parts.append("Ctrl")
        if m & Qt.KeyboardModifier.ShiftModifier:   parts.append("Shift")
        if m & Qt.KeyboardModifier.AltModifier:     parts.append("Alt")
        if m & Qt.KeyboardModifier.MetaModifier:    parts.append("Win")
        return "+".join(parts)

# ─────────────────────────────────────────────────────────────────────────────
#  Dialogs (native window frame, shared layout rules)
# ─────────────────────────────────────────────────────────────────────────────

class BaseDialog(QDialog):
    def __init__(self, parent, title: str, min_width: int = 400):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(min_width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(S5, S5, S5, S5)
        self.root.setSpacing(S4)

    @staticmethod
    def field(label: str, widget: QWidget, hint: str = "") -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S1)
        lay.addWidget(Label(label, "caption_strong", "secondary"))
        lay.addWidget(widget)
        if hint:
            h = Label(hint, "caption", "tertiary")
            h.setWordWrap(True)
            lay.addWidget(h)
        return box

    def add_buttons(self, ok_text: str, on_ok, ok_variant: str = "primary",
                    cancel_text: str | None = "Cancel") -> AppButton:
        row = QHBoxLayout()
        row.setSpacing(S2)
        row.addStretch()
        if cancel_text:
            cancel = AppButton(cancel_text)
            cancel.setAutoDefault(False)
            cancel.clicked.connect(self.reject)
            row.addWidget(cancel)
        ok = AppButton(ok_text, ok_variant)
        ok.setDefault(True)
        ok.clicked.connect(on_ok)
        row.addWidget(ok)
        self.root.addLayout(row)
        return ok


class MessageDialog(BaseDialog):
    def __init__(self, parent, title: str, text: str, confirm_text: str = "OK",
                 danger: bool = False, cancel_text: str | None = None):
        super().__init__(parent, title, 360)
        msg = Label(text, "body")
        msg.setWordWrap(True)
        self.root.addWidget(msg)
        self.add_buttons(confirm_text, self.accept,
                         "danger" if danger else "primary", cancel_text)


class InputDialog(BaseDialog):
    def __init__(self, parent, title: str, prompt: str):
        super().__init__(parent, title, 360)
        self.value = ""
        self.inp = AppLineEdit()
        self.root.addWidget(self.field(prompt, self.inp))
        self.add_buttons("OK", self._ok)

    def _ok(self):
        self.value = self.inp.text()
        self.accept()


class ShortcutDialog(BaseDialog):
    def __init__(self, parent, key: str = "", action: str = ""):
        super().__init__(parent, "Edit shortcut" if key else "New shortcut", 400)
        self.result_data = None

        self.key_inp = KeyCaptureInput()
        self.key_inp.setText(key)
        self.root.addWidget(self.field(
            "Shortcut key", self.key_inp,
            "Click the field, then press the keys."))

        self.action_inp = AppLineEdit(action)
        self.root.addWidget(self.field("Action", self.action_inp))

        self.add_buttons("Save", self._save)

    def _save(self):
        k = self.key_inp.text().strip()
        a = self.action_inp.text().strip()
        if k and a:
            self.result_data = {"key": k, "action": a}
            self.accept()


class ChangelogDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "Changelog", 560)
        self.resize(560, 480)
        view = QTextEdit()
        view.setObjectName("Doc")
        view.setReadOnly(True)
        view.setFont(role_font("body"))
        view.setHtml(self._load_changelog())
        self.root.addWidget(view, 1)
        self.add_buttons("Close", self.accept, "primary", None)

    def _load_changelog(self) -> str:
        # CHANGELOG.md is bundled in _MEIPASS or sits next to the script/exe
        for base in (
            getattr(sys, "_MEIPASS", None),
            os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None,
            os.path.dirname(os.path.abspath(__file__)),
            os.getcwd(),
        ):
            if base is None:
                continue
            path = os.path.join(base, "CHANGELOG.md")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    return self._md_to_html(f.read())
        return f"<p style='color:{P['text3']}'>CHANGELOG.md not found.</p>"

    @staticmethod
    def _md_to_html(md: str) -> str:
        """Basic markdown to HTML: handles #, ##, **, -, blank lines."""
        def inline(s: str) -> str:
            return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s))

        out = []
        for line in md.splitlines():
            if line.startswith("## "):
                out.append(
                    f'<p style="margin:{S4}px 0 {S1}px 0; color:{P["text"]}; '
                    f'font-size:{FS_BODY}px; font-weight:600;">{inline(line[3:])}</p>')
            elif line.startswith("# "):
                out.append(
                    f'<p style="margin:0 0 {S2}px 0; color:{P["text"]}; '
                    f'font-size:{FS_TITLE}px; font-weight:600;">{inline(line[2:])}</p>')
            elif line.startswith("- "):
                out.append(
                    f'<p style="margin:0 0 {S1}px {S3}px; color:{P["text2"]};">'
                    f'&bull;&nbsp; {inline(line[2:])}</p>')
            elif line.startswith("**") and line.endswith("**"):
                out.append(
                    f'<p style="margin:{S2}px 0 {S1}px 0; color:{P["text"]}; '
                    f'font-weight:600;">{inline(line[2:-2])}</p>')
            elif line.strip() == "":
                out.append(f'<p style="margin:0 0 {S1}px 0;"></p>')
            else:
                out.append(
                    f'<p style="margin:0 0 {S1}px 0; color:{P["text2"]};">{inline(line)}</p>')
        return "".join(out)

# ─────────────────────────────────────────────────────────────────────────────
#  Overlay: rows and window
# ─────────────────────────────────────────────────────────────────────────────

class ShortcutRow(QWidget):
    ROW_H = 36

    def __init__(self, key: str, action: str, key_col_w: int,
                 query: str = "", parent=None):
        super().__init__(parent)
        self.key    = key
        self.action = action
        self.setObjectName("Row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.ROW_H)
        self.setProperty("selected", "false")

        lay = QHBoxLayout(self)
        # 2 px is the selection bar, so text lines up with the header at 16
        lay.setContentsMargins(S4 - 2, 0, S4, 0)
        lay.setSpacing(S3)

        # Fixed key column: every action starts at the same x position
        key_col = QWidget()
        key_col.setFixedWidth(key_col_w)
        kl = QHBoxLayout(key_col)
        kl.setContentsMargins(0, 0, 0, 0)
        self.badge = KeyBadge(key)
        kl.addWidget(self.badge)
        kl.addStretch()

        self.action_lbl = Label("", "body", "secondary")
        self.action_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.action_lbl.setText(self._action_html(query))

        lay.addWidget(key_col)
        lay.addWidget(self.action_lbl, 1)

    def _action_html(self, query: str) -> str:
        text = self.action
        i = text.lower().find(query) if query else -1
        if i < 0:
            return html.escape(text)
        a, m, b = text[:i], text[i:i + len(query)], text[i + len(query):]
        return (f'{html.escape(a)}<span style="color:{P["accent_fg"]}; '
                f'font-weight:600;">{html.escape(m)}</span>{html.escape(b)}')

    def set_selected(self, v: bool):
        flag = "true" if v else "false"
        set_prop(self, "selected", flag)
        set_prop(self.badge, "selected", flag)
        self.action_lbl.set_tone("primary" if v else "secondary")


class CategoryHeader(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(CONTROL_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S4, 0, S4, 0)
        lay.addWidget(SectionHeader(title))
        lay.addStretch()


class OverlayWindow(QWidget):
    WIDTH, HEIGHT, MARGIN = 600, 500, S5

    def __init__(self, data: dict):
        super().__init__()
        self.data      = data
        self._rows: list[ShortcutRow] = []
        self._flat: list[tuple]       = []
        self._filtered_idx: list[int] = []
        self._sel      = 0
        self._visible  = False

        self._setup_window()
        self._build_ui()
        self._build_flat()
        self._render()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        # Translucent only so the rounded corners are clean. The card itself
        # is fully opaque, so text is never drawn on a see-through surface.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self._place()

    def _place(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - self.MARGIN,
                  screen.bottom() - self.height() - self.MARGIN)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("OverlayCard")
        root.addWidget(card)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # ── Header ──
        header = QWidget()
        header.setFixedHeight(S5 + S4)                      # 40
        hl = QHBoxLayout(header)
        hl.setContentsMargins(S4, 0, S2, 0)
        hl.setSpacing(S3)
        hl.addWidget(Label("OverCut", "strong"))
        hl.addStretch()
        hl.addWidget(Label("\u2191\u2193 navigate", "caption", "tertiary"))
        hl.addWidget(Label("Esc close", "caption", "tertiary"))
        close_btn = IconButton("close", "Close")
        close_btn.clicked.connect(self.hide_overlay)
        hl.addWidget(close_btn)
        cl.addWidget(header)
        cl.addWidget(Divider())

        # ── Search ──
        search = QWidget()
        search.setFixedHeight(S5 + S4)                      # 40
        sl = QHBoxLayout(search)
        sl.setContentsMargins(S4, 0, S4, 0)
        sl.setSpacing(S2)

        self.search_box = QLineEdit()
        self.search_box.setProperty("embedded", "true")
        self.search_box.setFont(role_font("body"))
        self.search_box.setPlaceholderText("Search shortcuts")
        self.search_box.textChanged.connect(self._on_search)

        self.match_lbl = Label("", "caption", "tertiary")

        sl.addWidget(SearchIcon())
        sl.addWidget(self.search_box, 1)
        sl.addWidget(self.match_lbl)
        cl.addWidget(search)
        cl.addWidget(Divider())

        # ── List ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, S2, 0, S2)
        self.list_layout.setSpacing(0)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.list_widget)
        self.list_widget.setAutoFillBackground(False)
        self.scroll.viewport().setAutoFillBackground(False)
        cl.addWidget(self.scroll, 1)

        # ── Footer ──
        cl.addWidget(Divider())
        footer = QWidget()
        footer.setFixedHeight(CONTROL_H)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(S4, 0, S4, 0)
        self.foot_key   = Label("", "caption", "tertiary")
        self.foot_count = Label("", "caption", "tertiary")
        fl.addWidget(self.foot_key)
        fl.addStretch()
        fl.addWidget(self.foot_count)
        cl.addWidget(footer)
        self._update_foot_key()

    def _update_foot_key(self):
        self.foot_key.setText(f"Hotkey: {self.data.get('trigger_key', '?')}")

    def _build_flat(self):
        self._flat = []
        for cat, shortcuts in self.data.get("categories", {}).items():
            for s in shortcuts:
                self._flat.append((cat, s.get("key", ""), s.get("action", "")))

    def _render(self, query: str = ""):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()            # no ghost rows while deletion is pending
                w.deleteLater()
        self._rows.clear()
        self._filtered_idx.clear()

        q = query.strip().lower()
        filtered = [
            (i, cat, key, action)
            for i, (cat, key, action) in enumerate(self._flat)
            if not q or q in key.lower() or q in action.lower() or q in cat.lower()
        ]

        # Key column is as wide as the widest badge, so actions line up
        fm = QFontMetrics(role_font("key"))
        key_w = max((fm.horizontalAdvance(k) for _, _, k, _ in filtered),
                    default=0) + 2 * S2 + 2 + S1
        key_w = max(S5 * 4, min(key_w, 240))

        current_cat = None
        for orig_i, cat, key, action in filtered:
            if cat != current_cat:
                current_cat = cat
                self.list_layout.insertWidget(
                    self.list_layout.count() - 1, CategoryHeader(cat))
            row = ShortcutRow(key, action, key_w, q)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows.append(row)
            self._filtered_idx.append(orig_i)

        if not filtered:
            empty = QWidget()
            el = QVBoxLayout(empty)
            el.setAlignment(Qt.AlignmentFlag.AlignCenter)
            el.setContentsMargins(0, S5 * 2, 0, 0)
            el.setSpacing(S1)
            t = Label("No matching shortcuts", "body", "secondary")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s = Label("Try a different search term.", "caption", "tertiary")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            el.addWidget(t)
            el.addWidget(s)
            self.list_layout.insertWidget(self.list_layout.count() - 1, empty)

        n, total = len(filtered), len(self._flat)
        self.foot_count.setText(
            f"{n} of {total}" if n != total else f"{total} shortcuts")
        self.match_lbl.setText(
            f"{n} result{'s' if n != 1 else ''}" if q else "")

        self._sel = 0
        if self._rows:
            self._rows[0].set_selected(True)

    def _on_search(self, text: str):
        self._render(text)
        self.scroll.verticalScrollBar().setValue(0)

    def _move(self, delta: int):
        if not self._rows:
            return
        self._rows[self._sel].set_selected(False)
        self._sel = (self._sel + delta) % len(self._rows)
        self._rows[self._sel].set_selected(True)
        self.scroll.ensureWidgetVisible(self._rows[self._sel], 0, S5 * 2)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self.search_box.text():
                self.search_box.clear()
            else:
                self.hide_overlay()
        elif key == Qt.Key.Key_Down:
            self._move(1)
        elif key == Qt.Key.Key_Up:
            self._move(-1)
        else:
            super().keyPressEvent(event)

    def show_overlay(self):
        self.search_box.clear()
        self._build_flat()
        self._render()
        self._place()
        self.show()
        self.raise_()
        self.activateWindow()
        self._visible = True
        QTimer.singleShot(80, self.search_box.setFocus)

    def hide_overlay(self):
        if not self._visible:
            return
        self._visible = False
        self.hide()

    def changeEvent(self, event):
        if (event.type() == QEvent.Type.ActivationChange
                and not self.isActiveWindow()
                and self._visible):
            self.hide_overlay()
        super().changeEvent(event)

    def toggle(self):
        if self._visible:
            self.hide_overlay()
        else:
            self.show_overlay()

    def refresh(self, data: dict):
        self.data = data
        self._build_flat()
        self._render(self.search_box.text())
        self._update_foot_key()

# ─────────────────────────────────────────────────────────────────────────────
#  Manager window
# ─────────────────────────────────────────────────────────────────────────────

class ManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data           = load_data()
        self._hotkey_thread = None
        self._force_quit    = False

        self.setWindowTitle("OverCut")
        self.resize(960, 640)
        self.setMinimumSize(780, 520)

        self._build_ui()
        self.overlay = OverlayWindow(self.data)
        self._setup_tray()
        self._start_hotkey()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_main_page())       # 0
        self.pages.addWidget(self._build_settings_page())   # 1
        root.addWidget(self.pages, 1)

        self._refresh_cats()

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("BarBottom")
        bar.setFixedHeight(S5 * 2)                          # 48
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(S4, 0, S4, 0)
        lay.setSpacing(S2)

        lay.addWidget(Label("OverCut", "title"))
        lay.addStretch()
        lay.addWidget(Label("Overlay hotkey", "caption", "secondary"))

        self.hotkey_inp = AppLineEdit(self.data.get("trigger_key", ""))
        self.hotkey_inp.setFont(role_font("mono"))
        self.hotkey_inp.setFixedWidth(200)

        apply_btn = AppButton("Apply")
        apply_btn.clicked.connect(self._apply_hotkey)
        settings_btn = AppButton("Settings")
        settings_btn.clicked.connect(self._open_settings)

        lay.addWidget(self.hotkey_inp)
        lay.addWidget(apply_btn)
        lay.addSpacing(S2)
        lay.addWidget(settings_btn)
        return bar

    def _build_main_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        cl = QHBoxLayout(content)
        cl.setContentsMargins(S4, S4, S4, S4)
        cl.setSpacing(S4)
        cl.addWidget(self._build_sidebar())
        cl.addWidget(self._build_table_panel(), 1)
        outer.addWidget(content, 1)

        outer.addWidget(self._build_footer())
        return page

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setFixedWidth(200)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S2)

        head = QWidget()
        head.setFixedHeight(CONTROL_H)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(SectionHeader("Categories"))
        lay.addWidget(head)

        card = AppCard()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        self.cat_list = QListWidget()
        self.cat_list.setObjectName("Sidebar")
        self.cat_list.setFont(role_font("body"))
        self.cat_list.setFrameShape(QFrame.Shape.NoFrame)
        self.cat_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cat_list.currentRowChanged.connect(self._on_cat_change)
        cl.addWidget(self.cat_list)
        lay.addWidget(card, 1)

        row = QHBoxLayout()
        row.setSpacing(S2)
        add_btn = AppButton("New")
        add_btn.clicked.connect(self._add_category)
        self.del_cat_btn = AppButton("Delete")
        self.del_cat_btn.clicked.connect(self._del_category)
        row.addWidget(add_btn, 1)
        row.addWidget(self.del_cat_btn, 1)
        lay.addLayout(row)
        return side

    def _build_table_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S2)

        head = QWidget()
        head.setFixedHeight(CONTROL_H)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(S2)
        self.cat_title = Label("", "title")
        self.cat_count = Label("", "caption", "tertiary")
        hl.addWidget(self.cat_title)
        hl.addWidget(self.cat_count)
        hl.addStretch()
        lay.addWidget(head)

        card = AppCard()
        self.table_stack = QStackedLayout(card)
        self.table_stack.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget()
        self.tree.setObjectName("Table")
        self.tree.setFont(role_font("body"))
        self.tree.setHeaderLabels(["Shortcut", "Action"])
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 200)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hdr = self.tree.header()
        hdr.setFixedHeight(CONTROL_H)
        hdr.setFont(role_font("caption_strong"))
        hdr.setStretchLastSection(True)
        hdr.setSectionsMovable(False)
        hdr.setHighlightSections(False)
        self.tree.itemSelectionChanged.connect(self._sync_buttons)
        self.table_stack.addWidget(self.tree)

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(S1)
        self.empty_title = Label("", "body", "secondary")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint = Label("", "caption", "tertiary")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(self.empty_title)
        el.addWidget(self.empty_hint)
        self.table_stack.addWidget(empty)
        lay.addWidget(card, 1)

        row = QHBoxLayout()
        row.setSpacing(S2)
        self.add_btn  = AppButton("Add shortcut", "primary")
        self.edit_btn = AppButton("Edit")
        self.del_btn  = AppButton("Delete")
        self.add_btn.clicked.connect(self._add_shortcut)
        self.edit_btn.clicked.connect(self._edit_shortcut)
        self.del_btn.clicked.connect(self._del_shortcut)
        row.addWidget(self.add_btn)
        row.addWidget(self.edit_btn)
        row.addWidget(self.del_btn)
        row.addStretch()
        lay.addLayout(row)
        return panel

    def _build_footer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("BarTop")
        bar.setFixedHeight(S5 * 2)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(S4, 0, S4, 0)
        lay.addWidget(Label(
            "Closing this window keeps OverCut running in the system tray.",
            "caption", "tertiary"))
        lay.addStretch()
        quit_btn = AppButton("Quit OverCut", "danger")
        quit_btn.clicked.connect(self._quit)
        lay.addWidget(quit_btn)
        return bar

    # ── Categories / shortcuts ────────────────────────────────────────────────

    def _refresh_cats(self, select: str | None = None):
        self.cat_list.clear()
        for cat in self.data["categories"]:
            item = QListWidgetItem(cat)
            item.setSizeHint(QSize(0, CONTROL_H))
            self.cat_list.addItem(item)
        if self.cat_list.count():
            row = 0
            if select in self.data["categories"]:
                row = list(self.data["categories"]).index(select)
            self.cat_list.setCurrentRow(row)
        else:
            self._load_shortcuts(None)

    def _current_cat(self):
        item = self.cat_list.currentItem()
        return item.text() if item else None

    def _on_cat_change(self, _=None):
        self._load_shortcuts(self._current_cat())

    def _sync_buttons(self):
        has_cat = self._current_cat() is not None
        has_row = self.tree.currentItem() is not None
        self.add_btn.setEnabled(has_cat)
        self.edit_btn.setEnabled(has_row)
        self.del_btn.setEnabled(has_row)
        self.del_cat_btn.setEnabled(has_cat)

    def _add_category(self):
        dlg = InputDialog(self, "New category", "Category name")
        if dlg.exec() and dlg.value.strip():
            name = dlg.value.strip()
            if name in self.data["categories"]:
                MessageDialog(self, "Category exists",
                              f'"{name}" already exists.').exec()
                return
            self.data["categories"][name] = []
            save_data(self.data)
            self._refresh_cats(select=name)
            self.overlay.refresh(self.data)

    def _del_category(self):
        cat = self._current_cat()
        if not cat:
            return
        dlg = MessageDialog(
            self, "Delete category",
            f'Delete "{cat}" and all its shortcuts?',
            "Delete", danger=True, cancel_text="Cancel")
        if dlg.exec():
            del self.data["categories"][cat]
            save_data(self.data)
            self._refresh_cats()
            self.overlay.refresh(self.data)

    def _load_shortcuts(self, cat):
        self.tree.clear()
        if cat is None:
            self.cat_title.setText("No category")
            self.cat_count.setText("")
            self.empty_title.setText("No categories yet")
            self.empty_hint.setText("Use New to create your first category.")
            self.table_stack.setCurrentIndex(1)
            self._sync_buttons()
            return

        items = self.data["categories"].get(cat, [])
        mono = role_font("mono")
        for s in items:
            item = QTreeWidgetItem([s["key"], s["action"]])
            item.setFont(0, mono)
            item.setSizeHint(0, QSize(0, CONTROL_H))
            item.setSizeHint(1, QSize(0, CONTROL_H))
            self.tree.addTopLevelItem(item)

        n = len(items)
        self.cat_title.setText(cat)
        self.cat_count.setText(f"{n} shortcut{'s' if n != 1 else ''}")
        self.empty_title.setText("No shortcuts in this category")
        self.empty_hint.setText("Use Add shortcut to create one.")
        self.table_stack.setCurrentIndex(0 if n else 1)
        self._sync_buttons()

    def _add_shortcut(self):
        cat = self._current_cat()
        if not cat:
            return
        dlg = ShortcutDialog(self)
        if dlg.exec() and dlg.result_data:
            self.data["categories"][cat].append(dlg.result_data)
            save_data(self.data)
            self._load_shortcuts(cat)
            self.overlay.refresh(self.data)

    def _edit_shortcut(self):
        cat = self._current_cat()
        sel = self.tree.currentItem()
        if not cat or not sel:
            return
        idx = self.tree.indexOfTopLevelItem(sel)
        ex  = self.data["categories"][cat][idx]
        dlg = ShortcutDialog(self, key=ex["key"], action=ex["action"])
        if dlg.exec() and dlg.result_data:
            self.data["categories"][cat][idx] = dlg.result_data
            save_data(self.data)
            self._load_shortcuts(cat)
            self.overlay.refresh(self.data)

    def _del_shortcut(self):
        cat = self._current_cat()
        sel = self.tree.currentItem()
        if not cat or not sel:
            return
        idx = self.tree.indexOfTopLevelItem(sel)
        del self.data["categories"][cat][idx]
        save_data(self.data)
        self._load_shortcuts(cat)
        self.overlay.refresh(self.data)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _open_settings(self):
        self.pages.setCurrentIndex(1)

    def _show_main(self):
        self.pages.setCurrentIndex(0)

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(S4, S4, S4, S4)
        lay.setSpacing(S4)

        head = QHBoxLayout()
        head.setSpacing(S3)
        back_btn = AppButton("Back")
        back_btn.clicked.connect(self._show_main)
        changelog_btn = AppButton("Changelog")
        changelog_btn.clicked.connect(lambda: ChangelogDialog(self).exec())
        head.addWidget(back_btn)
        head.addWidget(Label("Settings", "title"))
        head.addStretch()
        head.addWidget(changelog_btn)
        lay.addLayout(head)

        card = AppCard()
        card.setFixedWidth(640)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        startup = Switch(_get_startup_enabled())
        startup.toggled.connect(_set_startup)
        cl.addWidget(self._setting_row(
            "Launch at startup",
            "Start OverCut automatically when Windows boots.",
            startup))
        cl.addWidget(Divider())

        theme = Segmented(["Dark", "Light"],
                          "Light" if CURRENT_THEME == "light" else "Dark")
        theme.changed.connect(lambda t: self._apply_theme(t == "Light"))
        cl.addWidget(self._setting_row(
            "Theme", "Applies after restarting OverCut.", theme))

        lay.addWidget(card, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        return page

    def _setting_row(self, title: str, subtitle: str, control: QWidget) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(S4, S3, S4, S3)
        rl.setSpacing(S4)

        text = QVBoxLayout()
        text.setSpacing(S1)
        text.addWidget(Label(title, "body"))
        text.addWidget(Label(subtitle, "caption", "tertiary"))
        rl.addLayout(text, 1)
        rl.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _apply_theme(self, light: bool):
        """Save theme preference. The user restarts manually to apply."""
        self.data["theme"] = "light" if light else "dark"
        save_data(self.data)
        self.tray.showMessage(
            "OverCut", "Theme saved. Restart OverCut to apply.",
            QSystemTrayIcon.MessageIcon.Information, 3000)

    # ── Hotkey ────────────────────────────────────────────────────────────────

    def _apply_hotkey(self):
        k = self.hotkey_inp.text().strip()
        if not k:
            return
        self._stop_hotkey()
        self.data["trigger_key"] = k
        save_data(self.data)
        self.overlay.refresh(self.data)
        self._start_hotkey()

    def _start_hotkey(self):
        if not HOTKEY_OK:
            return
        self._hotkey_thread = HotkeyThread(
            self.data.get("trigger_key", "ctrl+shift+space"))
        self._hotkey_thread.triggered.connect(self.overlay.toggle)
        self._hotkey_thread.start()

    def _stop_hotkey(self):
        if self._hotkey_thread:
            self._hotkey_thread.stop()
            self._hotkey_thread = None

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _setup_tray(self):
        # overcut.ico: check _MEIPASS (bundled), then exe dir, then script dir
        icon = None
        for base in (
            getattr(sys, "_MEIPASS", None),
            os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None,
            os.path.dirname(os.path.abspath(__file__)),
            os.getcwd(),
        ):
            if base is None:
                continue
            ico = os.path.join(base, "overcut.ico")
            if os.path.exists(ico):
                icon = QIcon(ico)
                print(f"[Tray] Loaded icon from: {ico}")
                break

        if icon is None or icon.isNull():
            print("[Tray] overcut.ico not found, using fallback painted icon")
            px = QPixmap(16, 16)
            px.fill(QColor(0, 0, 0, 0))
            p = QPainter(px)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QBrush(QColor(P["accent"])))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, 16, 16, RADIUS_CONTROL, RADIUS_CONTROL)
            p.setPen(QPen(QColor(P["on_accent"])))
            f = role_font("caption_strong")
            p.setFont(f)
            p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "O")
            p.end()
            icon = QIcon(px)

        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()                      # styled by the global stylesheet
        menu.addAction("Show manager",   self.show)
        menu.addAction("Toggle overlay", self.overlay.toggle)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show()
            if r == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()
        self.tray.setToolTip("OverCut")

    def closeEvent(self, event):
        if self._force_quit:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "OverCut", "Running in tray. Double-click to reopen.",
            QSystemTrayIcon.MessageIcon.Information, 2000)

    def _quit(self):
        self._force_quit = True
        self._stop_hotkey()
        self.tray.hide()
        QApplication.quit()

# ─────────────────────────────────────────────────────────────────────────────
#  Entry point. ORDER IS CRITICAL:
#  1. platform options  2. QApplication  3. fonts  4. style/palette/QSS
#  5. windows
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Qt 6 already opts into Per-Monitor V2 DPI awareness. Do not call
    # SetProcessDpiAwareness yourself: forcing an older mode makes Qt's own
    # call fail and gives worse scaling.
    #
    # FreeType font engine: smoother glyphs than the default Windows engine,
    # and it supports variable fonts. Must be set BEFORE QApplication exists.
    os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")

    app = QApplication(sys.argv)
    app.setApplicationName("OverCut")
    app.setQuitOnLastWindowClosed(False)

    for _base in (
        getattr(sys, "_MEIPASS", None),
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None,
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
    ):
        if _base and os.path.exists(os.path.join(_base, "overcut.ico")):
            app.setWindowIcon(QIcon(os.path.join(_base, "overcut.ico")))
            break

    _LOADED_FAMILIES.extend(_load_bundled_fonts())
    print(f"[Fonts] Resolved UI font   : {_best_family(_UI_CANDIDATES)}")
    print(f"[Fonts] Resolved mono font : {_best_family(_MONO_CANDIDATES)}")

    app.setStyle("Fusion")              # consistent base that respects the palette
    app.setFont(role_font("body"))
    app.setPalette(build_palette())
    app.setStyleSheet(build_qss())

    if not HOTKEY_OK:
        print("Warning: 'keyboard' not installed, hotkey disabled.")

    win = ManagerWindow()
    win.show()
    sys.exit(app.exec())
