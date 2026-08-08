# -*- coding: utf-8 -*-
"""通用 UI 组件：指标卡片、标签徽章、表头等。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)


class Card(QFrame):
    """指标卡片：标题 + 大数值 + 副标题。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("cardTitle")
        self.value_lbl = QLabel("—")
        self.value_lbl.setObjectName("cardValue")
        self.value_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sub_lbl = QLabel("")
        self.sub_lbl.setObjectName("cardSub")
        lay.addWidget(self.title_lbl)
        lay.addWidget(self.value_lbl)
        lay.addWidget(self.sub_lbl)

    def set_value(self, text: str, sub: str = ""):
        self.value_lbl.setText(text)
        self.sub_lbl.setText(sub)

    def set_sub(self, text: str):
        self.sub_lbl.setText(text)


def badge(text: str, state: str = "ok") -> QLabel:
    """状态徽章：state ∈ ok / warn / off"""
    obj = {"ok": "badgeOk", "warn": "badgeWarn", "off": "badgeOff"}.get(state, "badgeOff")
    lbl = QLabel(text)
    lbl.setObjectName(obj)
    return lbl


def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("sectionTitle")
    return lbl


def h_line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color: #363a45;")
    return line


def label_row(key: str, value: str, parent=None) -> tuple:
    """返回 (row_widget, value_label)，用于状态键值行。"""
    row = QWidget(parent)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 2, 0, 2)
    k = QLabel(key)
    k.setObjectName("cardTitle")
    v = QLabel(value)
    v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(k)
    lay.addStretch(1)
    lay.addWidget(v)
    return row, v


class KeyValueRow(QWidget):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        self.k = QLabel(key)
        self.k.setObjectName("cardTitle")
        self.v = QLabel("—")
        self.v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.k)
        lay.addStretch(1)
        lay.addWidget(self.v)

    def set_text(self, text: str):
        self.v.setText(text)
