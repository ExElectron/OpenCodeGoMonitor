# -*- coding: utf-8 -*-
"""全局主题：暗色 / 亮色 QSS + matplotlib 配色联动。"""
import matplotlib

# ---- matplotlib 中文字体（Windows）----
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

DARK = {
    "bg": "#15161a", "panel": "#1e2026", "panel2": "#262931", "border": "#363a45",
    "text": "#e8eaf0", "text_dim": "#9aa0ad", "accent": "#4f8cff", "accent2": "#39d98a",
    "danger": "#ff5c5c", "warn": "#ffb020", "ok": "#39d98a",
    "input_bg": "#121318", "table_alt": "#1a1c22", "table_sel": "#2a3550",
    "table_red": "#5a2323", "table_red_text": "#ff8f8f",
}

LIGHT = {
    "bg": "#f4f6fa", "panel": "#ffffff", "panel2": "#eef1f6", "border": "#d5dae3",
    "text": "#1d2430", "text_dim": "#5d6676", "accent": "#2f6bff", "accent2": "#0fa968",
    "danger": "#d93025", "warn": "#c77700", "ok": "#0fa968",
    "input_bg": "#ffffff", "table_alt": "#f5f7fb", "table_sel": "#dbe6ff",
    "table_red": "#f9dcdc", "table_red_text": "#b3261e",
}

_MUTED = {"dark": "#8a93a5", "light": "#6b7484"}


def palette(name: str = "dark") -> dict:
    return DARK if name != "light" else LIGHT


def chart_colors(p: dict):
    """matplotlib 适配色。"""
    return {
        "bg": p["bg"], "panel": p["panel"], "text": p["text"], "dim": _MUTED[name_of(p)],
        "accent": p["accent"], "accent2": p["accent2"], "grid": p["border"],
        "warn": p["warn"], "danger": p["danger"], "ok": p["ok"],
        "series": ["#4f8cff", "#39d98a", "#ffb020", "#ff5c5c", "#c084fc", "#22d3ee", "#f472b6", "#a3e635"],
    }


def name_of(p: dict) -> str:
    return "dark" if p.get("bg") == DARK["bg"] else "light"


def _card_qss(p: dict) -> str:
    return f"""
    QFrame#card {{
        background: {p['panel']}; border: 1px solid {p['border']};
        border-radius: 10px;
    }}
    QLabel#cardTitle {{ color: {p['text_dim']}; font-size: 12px; }}
    QLabel#cardValue {{ color: {p['text']}; font-size: 22px; font-weight: 600; }}
    QLabel#cardSub   {{ color: {p['text_dim']}; font-size: 11px; }}
    QLabel#badgeOk   {{ color: {p['ok']}; background: transparent; font-weight: 600; }}
    QLabel#badgeWarn {{ color: {p['warn']}; background: transparent; font-weight: 600; }}
    QLabel#badgeOff  {{ color: {p['text_dim']}; background: transparent; }}
    QLabel#sectionTitle {{ color: {p['text']}; font-size: 15px; font-weight: 600; }}
    """


def build_stylesheet(name: str = "dark") -> str:
    p = DARK if name != "light" else LIGHT
    qss = f"""
    * {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; font-size: 13px; }}
    QMainWindow, QWidget {{ background: {p['bg']}; color: {p['text']}; }}
    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 8px; top: -1px; }}
    QTabBar::tab {{
        background: transparent; color: {p['text_dim']}; padding: 8px 18px;
        border: none; border-bottom: 2px solid transparent; font-size: 13px;
    }}
    QTabBar::tab:selected {{ color: {p['accent']}; border-bottom: 2px solid {p['accent']}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {p['text']}; }}
    QPushButton {{
        background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['border']};
        border-radius: 6px; padding: 6px 14px;
    }}
    QPushButton:hover {{ border-color: {p['accent']}; }}
    QPushButton:pressed {{ background: {p['input_bg']}; }}
    QPushButton:disabled {{ color: {p['text_dim']}; }}
    QPushButton#primary {{ background: {p['accent']}; color: white; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {p['accent']}; }}
    QPushButton#danger {{ background: {p['danger']}; color: white; border: none; }}
    QLineEdit, QComboBox, QDateTimeEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        background: {p['input_bg']}; color: {p['text']}; border: 1px solid {p['border']};
        border-radius: 6px; padding: 5px 8px; selection-background-color: {p['accent']};
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {p['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['border']};
        selection-background-color: {p['accent']};
    }}
    QTableView, QTreeView, QTableWidget {{
        background: {p['panel']}; alternate-background-color: {p['table_alt']};
        color: {p['text']}; border: 1px solid {p['border']}; border-radius: 6px;
        gridline-color: {p['border']}; selection-background-color: {p['table_sel']};
    }}
    QHeaderView::section {{
        background: {p['panel2']}; color: {p['text']}; border: none;
        border-right: 1px solid {p['border']}; border-bottom: 1px solid {p['border']};
        padding: 6px 8px; font-weight: 600;
    }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; }}
    QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 5px; min-width: 30px; }}
    QCheckBox, QRadioButton {{ spacing: 6px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px; border: 1px solid {p['border']}; border-radius: 4px;
        background: {p['input_bg']};
    }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QRadioButton::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
    QMenu {{ background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['border']}; }}
    QMenu::item {{ padding: 6px 24px; }}
    QMenu::item:selected {{ background: {p['accent']}; color: white; }}
    QToolTip {{ background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['border']}; }}
    QStatusBar {{ color: {p['text_dim']}; }}
    QProgressBar {{
        border: 1px solid {p['border']}; border-radius: 5px; text-align: center; height: 16px;
        background: {p['input_bg']}; color: {p['text']};
    }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 4px; }}
    QSplitter::handle {{ background: {p['border']}; }}
    """
    return qss + _card_qss(p)
