# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor

class SpinnerWidget(QWidget):
    """
    一個簡單的旋轉等待動畫元件。
    """
    def __init__(self, parent=None, arc_angle=90, speed=10, line_width=4, color=QColor("blue")):
        super().__init__(parent)
        self.angle = 0
        self.arc_angle = arc_angle
        self.line_width = line_width
        self.color = color
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateAngle)
        self.timer.start(speed)
        self.setMinimumSize(50, 50)

    def updateAngle(self):
        self.angle = (self.angle + 5) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)
        pen = QPen(self.color, self.line_width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        radius = min(self.width(), self.height()) / 2 - self.line_width
        draw_rect = QRectF(-radius, -radius, radius * 2, radius * 2)
        painter.drawArc(draw_rect, 0, self.arc_angle * 16)

class SplashScreen(QWidget):
    """
    應用程式啟動時顯示的等待畫面。
    """
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(300, 200)
        layout = QVBoxLayout()
        self.label = QLabel("正在啟動中...", self)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self.spinner = SpinnerWidget(arc_angle=90, speed=10, line_width=4, color=QColor("blue"))
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)
        self.setLayout(layout)