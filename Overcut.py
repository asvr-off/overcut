"""
OverCut — Shortcut Overlay Manager  (PyQt6)
============================================
Press your hotkey from anywhere to summon the overlay.
Manage shortcuts by category in the manager window.
Minimises to system tray.

Requirements:
    pip install PyQt6 keyboard
Windows:
    Run as Administrator for global hotkey support.

Font setup:
    Drop TTF files into a fonts/ folder next to this script (or next to the exe).
    Recommended:
        Inter-Regular.ttf  +  Inter-Bold.ttf
            https://fonts.google.com/specimen/Inter
        JetBrainsMono-Regular.ttf
            https://www.jetbrains.com/lp/mono/
    PyInstaller: --add-data "fonts;fonts"  (already in your build command)

    After launching, check the console for lines like:
        [Fonts] OK  Inter-Regular.ttf  ->  ['Inter']
    Use EXACTLY that family name string in QFont / QSS.
"""

import sys, json, os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog,
    QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QListWidget,
    QTreeWidget, QTreeWidgetItem, QScrollArea, QFrame,
    QSystemTrayIcon, QMenu, QMessageBox,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QRect, QTimer,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QColor,
    QIcon, QPixmap, QPainter, QPen, QBrush,
    QCursor, QLinearGradient,
)

try:
    import keyboard as kb_lib
    HOTKEY_OK = True
except ImportError:
    HOTKEY_OK = False

import ctypes

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
#  Spacing scale
# ─────────────────────────────────────────────────────────────────────────────

SP  = 8
SP2 = 16
SP3 = 24

# ─────────────────────────────────────────────────────────────────────────────
#  Font loader
#  CRITICAL: call AFTER QApplication(), BEFORE any widget is created.
# ─────────────────────────────────────────────────────────────────────────────

_LOADED_FAMILIES: list[str] = []

def _load_bundled_fonts() -> list[str]:
    """
    Scans fonts/ directory and registers every TTF/OTF with Qt.
    Prints the exact family name Qt gives each font — use that in QFont/QSS.
    """
    if getattr(sys, "frozen", False):
        # _MEIPASS  = PyInstaller temp dir where --add-data lands
        # executable dir = persistent exe location (for data files)
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
        print("[Fonts] No fonts/ directory found — using system fonts.")

    return loaded


# ─────────────────────────────────────────────────────────────────────────────
#  Typography helpers — call after _load_bundled_fonts()
# ─────────────────────────────────────────────────────────────────────────────

_UI_CANDIDATES   = ["Inter", "DM Sans", "Segoe UI Variable Text", "Segoe UI"]
_MONO_CANDIDATES = ["JetBrains Mono", "Cascadia Code", "Consolas"]

def _best_family(candidates: list[str]) -> str:
    available = QFontDatabase.families()
    for c in candidates:
        if c in available:
            return c
    return candidates[-1]

def ui_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(_best_family(_UI_CANDIDATES), size, weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f

def mono_font(size: int) -> QFont:
    return QFont(_best_family(_MONO_CANDIDATES), size)

def display_font(size: int, weight: QFont.Weight = QFont.Weight.Black) -> QFont:
    return QFont("Zalando Sans Expanded", size, weight)

def condensed_font(size: int, weight: QFont.Weight = QFont.Weight.Bold) -> QFont:
    return QFont("Roboto Condensed", size, weight)


# ─────────────────────────────────────────────────────────────────────────────
#  Palette
# ─────────────────────────────────────────────────────────────────────────────

P = {
    "base":         "#080809",
    "surface":      "#0f0f11",
    "raised":       "#161618",
    "overlay_bg":   "#111113",
    "input":        "#1a1a1d",
    "hover":        "#1e1e21",
    "active":       "#252528",
    "border":       "#232326",
    "border_hi":    "#38383d",
    "text":         "#ededef",
    "text2":        "#8f8f99",
    "muted":        "#4a4a52",
    "accent":       "#4c7fff",
    "accent_dim":   "#1c2e55",
    "accent_hi":    "#7ba3ff",
    "amber":        "#f0a030",
    "red":          "#e84040",
    "green":        "#34c769",
    "badge_bg":     "#1a1a1e",
    "badge_fg":     "#7a8599",
    "sel_bg":       "#182040",
    "sel_border":   "#3060cc",
}

QSS_GLOBAL = f"""
* {{
    font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 10pt;
    color: {P["text"]};
    outline: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 5px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {P["border_hi"]};
    border-radius: 2px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {P["muted"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ height: 0; }}
QToolTip {{
    background: {P["raised"]};
    color: {P["text2"]};
    border: 1px solid {P["border_hi"]};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 9pt;
}}
"""

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
#  Reusable widgets
# ─────────────────────────────────────────────────────────────────────────────

class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {P['border']}; border: none;")


class GhostButton(QPushButton):
    def __init__(self, text, parent=None, accent=False):
        super().__init__(text, parent)
        if accent:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {P['accent']};
                    color: #ffffff;
                    border: none;
                    border-radius: 6px;
                    padding: 7px 16px;
                    font-weight: 600;
                    font-size: 9pt;
                }}
                QPushButton:hover {{ background: {P['accent_hi']}; }}
                QPushButton:pressed {{ background: {P['accent_dim']}; }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {P['input']};
                    color: {P['text2']};
                    border: 1px solid {P['border']};
                    border-radius: 6px;
                    padding: 7px 14px;
                    font-size: 9pt;
                }}
                QPushButton:hover {{
                    background: {P['hover']};
                    color: {P['text']};
                    border-color: {P['border_hi']};
                }}
                QPushButton:pressed {{ background: {P['active']}; }}
            """)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))


class StyledInput(QLineEdit):
    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setStyleSheet(f"""
            QLineEdit {{
                background: {P['input']};
                color: {P['text']};
                border: 1px solid {P['border']};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 10pt;
                selection-background-color: {P['accent_dim']};
            }}
            QLineEdit:focus {{ border-color: {P['accent']}; }}
        """)

# ─────────────────────────────────────────────────────────────────────────────
#  Overlay — ShortcutRow / CategoryHeader
# ─────────────────────────────────────────────────────────────────────────────

class ShortcutRow(QWidget):
    ROW_H = 42

    def __init__(self, key: str, action: str, parent=None):
        super().__init__(parent)
        self.key       = key
        self.action    = action
        self._selected = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.ROW_H)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP2, 0, SP2, 0)
        lay.setSpacing(SP + 4)

        self.badge = QLabel(self.key)
        self.badge.setFont(mono_font(8))
        self.badge.setFixedHeight(22)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(f"""
            QLabel {{
                background: {P['badge_bg']};
                color: {P['badge_fg']};
                border: 1px solid {P['border']};
                border-radius: 4px;
                padding: 0px 8px;
                min-width: 64px;
            }}
        """)

        self.action_lbl = QLabel(self.action)
        self.action_lbl.setFont(ui_font(9))
        self.action_lbl.setStyleSheet(
            f"color: {P['text2']}; background: transparent;")

        lay.addWidget(self.badge)
        lay.addWidget(self.action_lbl, 1)
        self._refresh_style()

    def set_selected(self, v: bool):
        self._selected = v
        self._refresh_style()

    def set_highlight(self, query: str):
        q = query.strip().lower()
        if q and (q in self.key.lower() or q in self.action.lower()):
            self.badge.setStyleSheet(f"""
                QLabel {{
                    background: #2a1f00;
                    color: {P['amber']};
                    border: 1px solid #5a3a00;
                    border-radius: 4px;
                    padding: 0px 8px;
                    min-width: 64px;
                }}
            """)
            self.action_lbl.setStyleSheet(
                f"color: {P['amber']}; background: transparent;")
        else:
            self._refresh_style()

    def _refresh_style(self):
        if self._selected:
            self.setStyleSheet(f"""
                ShortcutRow {{
                    background: {P['sel_bg']};
                    border-left: 2px solid {P['accent']};
                }}
            """)
            self.badge.setStyleSheet(f"""
                QLabel {{
                    background: {P['accent']};
                    color: #ffffff;
                    border: none;
                    border-radius: 4px;
                    padding: 0px 8px;
                    min-width: 64px;
                    font-weight: 600;
                }}
            """)
            self.action_lbl.setStyleSheet(
                f"color: {P['text']}; background: transparent; font-weight: 500;")
        else:
            self.setStyleSheet(f"""
                ShortcutRow {{
                    background: transparent;
                    border-left: 2px solid transparent;
                }}
                ShortcutRow:hover {{ background: {P['hover']}; }}
            """)
            self.badge.setStyleSheet(f"""
                QLabel {{
                    background: {P['badge_bg']};
                    color: {P['badge_fg']};
                    border: 1px solid {P['border']};
                    border-radius: 4px;
                    padding: 0px 8px;
                    min-width: 64px;
                }}
            """)
            self.action_lbl.setStyleSheet(
                f"color: {P['text2']}; background: transparent;")


class CategoryHeader(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(32)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP2, 0, SP2, 0)

        dot = QLabel("◆")
        dot.setFont(ui_font(7))
        dot.setStyleSheet(f"color: {P['accent']}; background: transparent;")

        lbl = QLabel(f"  {title.upper()}")
        lbl.setFont(ui_font(7, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {P['muted']}; background: transparent;")

        lay.addWidget(dot)
        lay.addWidget(lbl)
        lay.addStretch()

# ─────────────────────────────────────────────────────────────────────────────
#  Overlay Window
# ─────────────────────────────────────────────────────────────────────────────

class OverlayWindow(QWidget):
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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(600, 500)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 52,
                  screen.bottom() - self.height() - 60)

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame()
        self.card.setObjectName("OverlayCard")
        self.card.setStyleSheet(f"""
            QFrame#OverlayCard {{
                background: {P['overlay_bg']};
                border: 1px solid {P['border_hi']};
                border-radius: 12px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        root_layout.addWidget(self.card)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── Header ──
        header = QWidget()
        header.setFixedHeight(54)
        header.setStyleSheet(f"""
            background: {P['surface']};
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(SP2 + 2, 0, SP + 6, 0)

        icon_lbl = QLabel("⌨")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 14))
        icon_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")

        title_lbl = QLabel("OverCut")
        title_lbl.setFont(ui_font(13, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['text']}; background: transparent;")
        

        hint_frame = QWidget()
        hint_frame.setStyleSheet("background: transparent;")
        hint_lay = QHBoxLayout(hint_frame)
        hint_lay.setContentsMargins(0, 0, 0, 0)
        hint_lay.setSpacing(4)

        for txt in ["↑ ↓  nav", "scroll", "Esc"]:
            pill = QLabel(txt)
            pill.setFont(mono_font(7))
            pill.setStyleSheet(f"""
                color: {P['muted']};
                background: {P['raised']};
                border: 1px solid {P['border']};
                border-radius: 4px;
                padding: 2px 7px;
            """)
            hint_lay.addWidget(pill)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(28, 28)
        close_btn.setFont(ui_font(14))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {P['muted']};
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {P['red']}22;
                color: {P['red']};
            }}
        """)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self.hide_overlay)

        h_lay.addWidget(icon_lbl)
        h_lay.addWidget(title_lbl)
        h_lay.addSpacing(SP)
        h_lay.addStretch()
        h_lay.addWidget(hint_frame)
        h_lay.addSpacing(SP)
        h_lay.addWidget(close_btn)

        card_layout.addWidget(header)
        card_layout.addWidget(Divider())

        # ── Search ──
        search_wrap = QWidget()
        search_wrap.setFixedHeight(50)
        search_wrap.setStyleSheet(f"background: {P['raised']}; border: none;")
        s_lay = QHBoxLayout(search_wrap)
        s_lay.setContentsMargins(SP2, SP, SP2, SP)
        s_lay.setSpacing(SP + 2)

        search_icon = QLabel("⌕")
        search_icon.setFont(ui_font(14))
        search_icon.setStyleSheet(
            f"color: {P['muted']}; background: transparent;")

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search shortcuts…")
        self.search_box.setFont(ui_font(10))
        self.search_box.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                color: {P['text']};
                border: none;
                padding: 0;
                selection-background-color: {P['accent_dim']};
            }}
        """)
        self.search_box.textChanged.connect(self._on_search)

        self.match_lbl = QLabel("")
        self.match_lbl.setFont(ui_font(8))
        self.match_lbl.setStyleSheet(
            f"color: {P['muted']}; background: transparent;")

        s_lay.addWidget(search_icon)
        s_lay.addWidget(self.search_box, 1)
        s_lay.addWidget(self.match_lbl)

        card_layout.addWidget(search_wrap)
        card_layout.addWidget(Divider())

        # ── Scroll area ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            f"background: {P['overlay_bg']}; border: none;")

        self.list_widget = QWidget()
        self.list_widget.setStyleSheet(
            f"background: {P['overlay_bg']}; border: none;")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, SP - 2, 0, SP - 2)
        self.list_layout.setSpacing(0)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.list_widget)
        card_layout.addWidget(self.scroll, 1)

        # ── Footer ──
        card_layout.addWidget(Divider())
        footer = QWidget()
        footer.setFixedHeight(36)
        footer.setStyleSheet(f"""
            background: {P['surface']};
            border-bottom-left-radius: 12px;
            border-bottom-right-radius: 12px;
        """)
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(SP2 + 2, 0, SP2 + 2, 0)

        self.foot_key = QLabel()
        self.foot_key.setFont(mono_font(8))
        self.foot_key.setStyleSheet(
            f"color: {P['muted']}; background: transparent;")
        self._update_foot_key()

        self.foot_count = QLabel()
        self.foot_count.setFont(ui_font(8))
        self.foot_count.setStyleSheet(
            f"color: {P['muted']}; background: transparent;")

        f_lay.addWidget(self.foot_key)
        f_lay.addStretch()
        f_lay.addWidget(self.foot_count)

        card_layout.addWidget(footer)

    def _update_foot_key(self):
        self.foot_key.setText(f"hotkey  {self.data.get('trigger_key', '?')}")

    def _build_flat(self):
        self._flat = []
        for cat, shortcuts in self.data.get("categories", {}).items():
            for s in shortcuts:
                self._flat.append((cat, s.get("key", ""), s.get("action", "")))

    def _render(self, query: str = ""):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._filtered_idx.clear()

        q = query.strip().lower()
        filtered = [
            (i, cat, key, action)
            for i, (cat, key, action) in enumerate(self._flat)
            if not q or q in key.lower() or q in action.lower() or q in cat.lower()
        ]

        current_cat = None
        for orig_i, cat, key, action in filtered:
            if cat != current_cat:
                current_cat = cat
                self.list_layout.insertWidget(
                    self.list_layout.count() - 1, CategoryHeader(cat))
            row = ShortcutRow(key, action)
            if q:
                row.set_highlight(q)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows.append(row)
            self._filtered_idx.append(orig_i)

        if not filtered:
            empty = QWidget()
            empty.setStyleSheet("background: transparent;")
            e_lay = QVBoxLayout(empty)
            e_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t = QLabel("Nothing found")
            t.setFont(ui_font(11))
            t.setStyleSheet(f"color: {P['muted']}; background: transparent;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s = QLabel("Try a different search term")
            s.setFont(ui_font(9))
            s.setStyleSheet(f"color: {P['muted']}; background: transparent;")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_lay.addWidget(t)
            e_lay.addWidget(s)
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
        self.scroll.ensureWidgetVisible(self._rows[self._sel], 0, 60)

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
        screen = QApplication.primaryScreen().availableGeometry()
        w, h    = self.width(), self.height()
        x       = screen.right() - w - 52
        y_end   = screen.bottom() - h - 60
        y_start = y_end + 20

        self.search_box.clear()
        self._build_flat()
        self._render()

        self.setGeometry(x, y_start, w, h)
        self.show()
        self.raise_()
        self.activateWindow()
        self._visible = True

        self._anim.setStartValue(QRect(x, y_start, w, h))
        self._anim.setEndValue(QRect(x, y_end, w, h))
        self._anim.start()

        QTimer.singleShot(80, self.search_box.setFocus)

    def hide_overlay(self):
        self._visible = False
        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setDuration(120)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(lambda: (self.hide(), self.setWindowOpacity(1.0)))
        self._fade_out.start()

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
#  Shortcut Dialog
# ─────────────────────────────────────────────────────────────────────────────

class ShortcutDialog(QDialog):
    def __init__(self, parent, key="", action=""):
        super().__init__(parent)
        self.result_data = None
        self.setWindowTitle("Shortcut")
        self.setFixedWidth(420)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"""
            QDialog {{
                background: {P['surface']};
                border: 1px solid {P['border_hi']};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP3, SP2 + 4, SP3, SP2 + 4)
        lay.setSpacing(SP2)

        title = QLabel("Edit Shortcut" if key else "New Shortcut")
        title.setFont(ui_font(13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['text']};")
        lay.addWidget(title)
        lay.addWidget(Divider())

        def field(label_text, value):
            w  = QWidget()
            w.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(w)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(5)
            lbl = QLabel(label_text)
            lbl.setFont(ui_font(8, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {P['muted']}; letter-spacing: 1px;")
            inp = StyledInput()
            inp.setText(value)
            fl.addWidget(lbl)
            fl.addWidget(inp)
            lay.addWidget(w)
            return inp

        self.key_inp    = field("SHORTCUT KEY",       key)
        self.action_inp = field("ACTION DESCRIPTION", action)
        lay.addWidget(Divider())

        btn_row = QWidget()
        btn_row.setStyleSheet("background: transparent;")
        b_lay = QHBoxLayout(btn_row)
        b_lay.setContentsMargins(0, 0, 0, 0)
        b_lay.addStretch()
        cancel = GhostButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = GhostButton("Save", accent=True)
        save.clicked.connect(self._save)
        b_lay.addWidget(cancel)
        b_lay.addSpacing(SP)
        b_lay.addWidget(save)
        lay.addWidget(btn_row)

    def _save(self):
        k = self.key_inp.text().strip()
        a = self.action_inp.text().strip()
        if k and a:
            self.result_data = {"key": k, "action": a}
            self.accept()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._save()
        elif e.key() == Qt.Key.Key_Escape:
            self.reject()

# ─────────────────────────────────────────────────────────────────────────────
#  Animated top bar
# ─────────────────────────────────────────────────────────────────────────────

class AnimatedTopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        self._pos   = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._pos = (self._pos + 0.0018) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.fillRect(0, 0, w, 2, QColor(P["border"]))
        cx   = int(self._pos * (w + 300)) - 150
        span = 220
        grad = QLinearGradient(cx - span, 0, cx + span, 0)
        grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
        grad.setColorAt(0.35, QColor(P["accent"]))
        grad.setColorAt(0.5,  QColor(P["accent_hi"]))
        grad.setColorAt(0.65, QColor(P["accent"]))
        grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.fillRect(cx - span, 0, span * 2, 2, grad)
        p.end()

# ─────────────────────────────────────────────────────────────────────────────
#  Manager Window
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
        self.setStyleSheet(f"QMainWindow {{ background: {P['base']}; }}")

        self._build_ui()
        self.overlay = OverlayWindow(self.data)
        self._setup_tray()
        self._start_hotkey()

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background: {P['base']};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(AnimatedTopBar())

        # ── Titlebar ──
        titlebar = QWidget()
        titlebar.setFixedHeight(76)
        titlebar.setStyleSheet(f"""
            background: {P['surface']};
            border-bottom: 1px solid {P['base']};
        """)
        tb_lay = QHBoxLayout(titlebar)
        tb_lay.setContentsMargins(SP3, 0, SP2 + 4, 0)
        tb_lay.setSpacing(0)

        title_block = QWidget()
        title_block.setStyleSheet("background: transparent;")
        tb_vlay = QVBoxLayout(title_block)
        tb_vlay.setContentsMargins(0, 0, 0, 0)
        tb_vlay.setSpacing(2)
        title_lbl = QLabel("OVERCUT")
        title_lbl.setStyleSheet(f"""
            color: {P['text']};
            background: transparent;
            letter-spacing: 8px;
            font-family: "Zalando Sans Expanded";
            font-weight: 900;
            font-size: 19pt;
        """)
        tb_vlay.addWidget(title_lbl)
        tb_lay.addWidget(title_block)
        tb_lay.addStretch()

        hk_lbl = QLabel("HOTKEY")
        hk_font = ui_font(7, QFont.Weight.Bold)
        hk_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        hk_lbl.setFont(condensed_font(7, QFont.Weight.Bold))
        hk_lbl.setStyleSheet(f"""
            color: {P['muted']};
            background: transparent;
            font-family: "Roboto Condensed";
            font-weight: 700;
            font-size: 7pt;
        """)

        self.hotkey_inp = QLineEdit(self.data.get("trigger_key", ""))
        self.hotkey_inp.setFont(mono_font(10))
        self.hotkey_inp.setFixedWidth(210)
        self.hotkey_inp.setFixedHeight(34)
        self.hotkey_inp.setStyleSheet(f"""
            QLineEdit {{
                background: {P['input']};
                color: {P['accent_hi']};
                border: 1px solid {P['border']};
                border-radius: 6px;
                padding: 0 12px;
                selection-background-color: {P['accent_dim']};
                font-family: "JetBrains Mono";
                font-size: 10pt;
            }}
            QLineEdit:focus {{ border-color: {P['accent']}; }}
        """)

        apply_btn = GhostButton("Apply")
        apply_btn.setFixedHeight(34)
        apply_btn.clicked.connect(self._apply_hotkey)

        tb_lay.addWidget(hk_lbl)
        tb_lay.addSpacing(SP + 2)
        tb_lay.addWidget(self.hotkey_inp)
        tb_lay.addSpacing(SP)
        tb_lay.addWidget(apply_btn)
        root.addWidget(titlebar)

        # ── Body ──
        body = QWidget()
        body.setStyleSheet(f"background: {P['base']};")
        b_lay = QHBoxLayout(body)
        b_lay.setContentsMargins(SP2 + 4, SP2 + 4, SP2 + 4, SP2 + 4)
        b_lay.setSpacing(SP2)

        # ─ Sidebar ─
        sidebar = QWidget()
        sidebar.setFixedWidth(210)
        sidebar.setStyleSheet("background: transparent;")
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(SP)

        cat_lbl = QLabel("CATEGORIES")
        cat_font = ui_font(7, QFont.Weight.Bold)
        cat_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        cat_lbl.setFont(condensed_font(7, QFont.Weight.Bold))
        cat_lbl.setStyleSheet(f"""
            color: {P['muted']};
            background: transparent;
            font-family: "Roboto Condensed";
            font-weight: 700;
            font-size: 7pt;
        """)
        sb_lay.addWidget(cat_lbl)

        self.cat_list = QListWidget()
        self.cat_list.setStyleSheet(f"""
            QListWidget {{
                background: {P['surface']};
                border: 1px solid {P['border']};
                border-radius: 10px;
                outline: none;
                padding: 4px 0;
            }}
            QListWidget::item {{
                color: {P['text2']};
                padding: 9px 14px;
                border-left: 2px solid transparent;
                font-size: 10pt;
            }}
            QListWidget::item:hover {{
                background: {P['hover']};
                color: {P['text']};
            }}
            QListWidget::item:selected {{
                background: {P['active']};
                color: {P['text']};
                border-left: 2px solid {P['accent']};
            }}
        """)
        self.cat_list.currentRowChanged.connect(self._on_cat_change)
        sb_lay.addWidget(self.cat_list, 1)

        cb = QWidget()
        cb.setStyleSheet("background: transparent;")
        cb_lay = QVBoxLayout(cb)
        cb_lay.setContentsMargins(0, 0, 0, 0)
        cb_lay.setSpacing(6)
        add_cat_btn = GhostButton("New Category")
        add_cat_btn.clicked.connect(self._add_category)
        del_cat_btn = GhostButton("Delete Category")
        del_cat_btn.clicked.connect(self._del_category)
        cb_lay.addWidget(add_cat_btn)
        cb_lay.addWidget(del_cat_btn)
        sb_lay.addWidget(cb)
        b_lay.addWidget(sidebar)

        # ─ Main panel ─
        main_panel = QWidget()
        main_panel.setStyleSheet("background: transparent;")
        mp_lay = QVBoxLayout(main_panel)
        mp_lay.setContentsMargins(0, 0, 0, 0)
        mp_lay.setSpacing(SP)

        sc_lbl = QLabel("SHORTCUTS")
        sc_font = ui_font(7, QFont.Weight.Bold)
        sc_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        sc_lbl.setFont(condensed_font(7, QFont.Weight.Bold))    
        sc_lbl.setStyleSheet(f"""
            color: {P['muted']};
            background: transparent;
            font-family: "Roboto Condensed";
            font-weight: 700;
            font-size: 7pt;
        """)
        mp_lay.addWidget(sc_lbl)

        tree_container = QWidget()
        tree_container.setStyleSheet(f"""
            background: {P['surface']};
            border: 1px solid {P['border']};
            border-radius: 10px;
        """)
        tc_lay = QVBoxLayout(tree_container)
        tc_lay.setContentsMargins(0, 0, 0, 0)
        tc_lay.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Shortcut Key", "Action"])
        self.tree.setColumnWidth(0, 190)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background: transparent;
                border: none;
                outline: none;
                font-size: 10pt;
                color: {P['text2']};
            }}
            QTreeWidget::item {{
                padding: 8px 10px;
                border-bottom: 1px solid {P['border']};
            }}
            QTreeWidget::item:hover {{
                background: {P['hover']};
                color: {P['text']};
            }}
            QTreeWidget::item:selected {{
                background: {P['accent_dim']};
                color: {P['text']};
                border-bottom: 1px solid {P['border']};
            }}
            QHeaderView::section {{
                background: {P['raised']};
                color: {P['muted']};
                border: none;
                border-bottom: 1px solid {P['border']};
                border-right: 1px solid {P['border']};
                padding: 6px 10px;
                font-size: 8pt;
                font-weight: bold;
                letter-spacing: 1px;
            }}
        """)
        tc_lay.addWidget(self.tree, 1)

        act_bar = QWidget()
        act_bar.setFixedHeight(54)
        act_bar.setStyleSheet(f"""
            background: {P['raised']};
            border-top: 1px solid {P['border']};
            border-bottom-left-radius: 10px;
            border-bottom-right-radius: 10px;
        """)
        ab_lay = QHBoxLayout(act_bar)
        ab_lay.setContentsMargins(SP + 6, 0, SP + 6, 0)
        ab_lay.setSpacing(SP)

        btn_font = ui_font(9, QFont.Weight.Medium)
        add_btn  = GhostButton("Add Shortcut", accent=True)
        edit_btn = GhostButton("Edit")
        del_btn  = GhostButton("Delete")
        stop_btn = GhostButton("Stop Service")
        stop_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {P['red']};
                border: 1px solid {P['border']};
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 9pt;
            }}
            QPushButton:hover {{
                background: {P['red']}18;
                border-color: {P['red']};
            }}
            QPushButton:pressed {{ background: {P['red']}30; }}
        """)
        stop_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        for b in (add_btn, edit_btn, del_btn, stop_btn):
            b.setFont(btn_font)

        add_btn.clicked.connect(self._add_shortcut)
        edit_btn.clicked.connect(self._edit_shortcut)
        del_btn.clicked.connect(self._del_shortcut)
        stop_btn.clicked.connect(self._quit)

        ab_lay.addWidget(add_btn)
        ab_lay.addWidget(edit_btn)
        ab_lay.addWidget(del_btn)
        ab_lay.addSpacing(SP + 4)
        ab_lay.addWidget(stop_btn)
        ab_lay.addStretch()

        tc_lay.addWidget(act_bar)
        mp_lay.addWidget(tree_container, 1)
        b_lay.addWidget(main_panel, 1)
        root.addWidget(body, 1)

        self._refresh_cats()

    def _refresh_cats(self):
        self.cat_list.clear()
        for cat in self.data["categories"]:
            self.cat_list.addItem(cat)
        if self.cat_list.count():
            self.cat_list.setCurrentRow(0)

    def _current_cat(self):
        item = self.cat_list.currentItem()
        return item.text() if item else None

    def _on_cat_change(self, _=None):
        cat = self._current_cat()
        if cat:
            self._load_shortcuts(cat)

    def _add_category(self):
        dlg = _InputDialog(self, "New Category", "Category name:")
        if dlg.exec() and dlg.value.strip():
            name = dlg.value.strip()
            if name in self.data["categories"]:
                QMessageBox.warning(self, "Exists", f'"{name}" already exists.')
                return
            self.data["categories"][name] = []
            save_data(self.data)
            self._refresh_cats()
            self.overlay.refresh(self.data)

    def _del_category(self):
        cat = self._current_cat()
        if not cat:
            return
        mb = QMessageBox(self)
        mb.setWindowTitle("Delete")
        mb.setText(f'Delete "{cat}" and all its shortcuts?')
        mb.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        mb.setStyleSheet(f"""
            QMessageBox {{ background: {P['surface']}; }}
            QLabel {{ color: {P['text']}; }}
        """)
        if mb.exec() == QMessageBox.StandardButton.Yes:
            del self.data["categories"][cat]
            save_data(self.data)
            self._refresh_cats()
            self.overlay.refresh(self.data)

    def _load_shortcuts(self, cat):
        self.tree.clear()
        for s in self.data["categories"].get(cat, []):
            item = QTreeWidgetItem([s["key"], s["action"]])
            self.tree.addTopLevelItem(item)

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

    def _setup_tray(self):
        px = QPixmap(16, 16)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(P["accent"])))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 16, 16, 3, 3)
        p.setPen(QPen(QColor("#ffffff")))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "K")
        p.end()

        self.tray = QSystemTrayIcon(QIcon(px), self)
        menu = QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background: {P['surface']};
                border: 1px solid {P['border_hi']};
                border-radius: 8px;
                padding: 4px;
                color: {P['text']};
                font-size: 10pt;
            }}
            QMenu::item {{ padding: 7px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {P['hover']}; }}
            QMenu::separator {{ height: 1px; background: {P['border']}; margin: 4px 0; }}
        """)
        menu.addAction("Show Manager",   self.show)
        menu.addAction("Toggle Overlay", self.overlay.toggle)
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
#  Input dialog
# ─────────────────────────────────────────────────────────────────────────────

class _InputDialog(QDialog):
    def __init__(self, parent, title, prompt):
        super().__init__(parent)
        self.value = ""
        self.setWindowTitle(title)
        self.setFixedWidth(340)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"""
            QDialog {{
                background: {P['surface']};
                border: 1px solid {P['border_hi']};
                border-radius: 10px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP2 + 4, SP2 + 2, SP2 + 4, SP2 + 2)
        lay.setSpacing(SP + 4)

        lbl = QLabel(prompt)
        lbl.setFont(ui_font(10))
        lbl.setStyleSheet(f"color: {P['text']};")
        lay.addWidget(lbl)

        self.inp = StyledInput()
        lay.addWidget(self.inp)

        btns = QWidget()
        btns.setStyleSheet("background: transparent;")
        b = QHBoxLayout(btns)
        b.setContentsMargins(0, 0, 0, 0)
        b.addStretch()
        cancel = GhostButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = GhostButton("OK", accent=True)
        ok.clicked.connect(self._ok)
        b.addWidget(cancel)
        b.addSpacing(SP)
        b.addWidget(ok)
        lay.addWidget(btns)

    def _ok(self):
        self.value = self.inp.text()
        self.accept()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._ok()
        elif e.key() == Qt.Key.Key_Escape:
            self.reject()

# ─────────────────────────────────────────────────────────────────────────────
#  Entry point — ORDER IS CRITICAL
#  1. QApplication
#  2. _load_bundled_fonts()  <- MUST be here, after app, before any widget
#  3. setStyleSheet
#  4. Create windows
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("OverCut")
    app.setQuitOnLastWindowClosed(False)

    # Step 2 — load fonts before any widget touches QFont
    _LOADED_FAMILIES.extend(_load_bundled_fonts())
    print(f"[Fonts] Resolved UI font   : {_best_family(_UI_CANDIDATES)}")
    print(f"[Fonts] Resolved mono font : {_best_family(_MONO_CANDIDATES)}")

    # Step 3 — stylesheet after fonts are registered
    app.setStyleSheet(QSS_GLOBAL)

    if not HOTKEY_OK:
        print("Warning: 'keyboard' not installed — hotkey disabled.")

    # Step 4 — windows
    win = ManagerWindow()
    win.show()
    sys.exit(app.exec())