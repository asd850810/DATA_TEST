# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtGui import QPainter, QColor

class CustomToggleSwitch(QWidget):
    """
    一個自訂的 ON/OFF 滑動開關。
    """
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, *, checked: bool = True):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setFixedSize(60, 28)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        checked = bool(checked)
        if self._checked != checked:
            self._checked = checked
            self.toggled.emit(self._checked)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        radius = self.height() / 2
        bg_color = QColor("#448AFF") if self._checked else QColor("#FF6666")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(self.rect(), radius, radius)

        circle_d = self.height() - 4
        circle_r = circle_d / 2
        circle_x = self.width() - circle_d - 2 if self._checked else 2
        circle_y = 2
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QPointF(circle_x + circle_r, circle_y + circle_r), circle_r, circle_r)