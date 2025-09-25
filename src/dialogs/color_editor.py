# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QColorDialog
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QColor

class ColorEditor(QDialog):
    """
    測試結果顏色設定對話框。
    讓使用者可以為不同的測試結果類別（如 OK, NG）設定自訂顏色。
    """
    def __init__(self, color_map: dict, ordered_cats, parent=None):
        super().__init__(parent)
        self.setWindowTitle("測試結果顏色設定")
        self.resize(260, 200)
        self.settings = QSettings("MyCompany", "MyApp")

        self.color_map = color_map
        self.labels = {}

        lay = QVBoxLayout(self)
        for cat in ordered_cats:
            h = QHBoxLayout()
            lab = QLabel(cat)
            lab.setFixedWidth(60)
            btn = QPushButton()
            btn.setFixedSize(40, 20)
            btn.setStyleSheet(f"background:{color_map.get(cat, 'gray')}")
            btn.clicked.connect(lambda _, c=cat: self.pick_color(c))
            h.addWidget(lab)
            h.addWidget(btn)
            h.addStretch()
            lay.addLayout(h)
            self.labels[cat] = btn

        btn_ok = QPushButton("關閉")
        btn_ok.clicked.connect(self.accept)
        lay.addWidget(btn_ok, alignment=Qt.AlignRight)

    def pick_color(self, cat):
        """開啟顏色選擇對話框，並儲存選擇的顏色。"""
        current_color = QColor(self.color_map.get(cat, 'gray'))
        new_color = QColorDialog.getColor(current_color, self, f"{cat} 顏色")
        if new_color.isValid():
            color_name = new_color.name()
            self.labels[cat].setStyleSheet(f"background:{color_name}")
            self.color_map[cat] = color_name
            self.settings.setValue(f"result_colors/{cat}", color_name)
            self.settings.sync()
            if self.parent():
                self.parent().color_settings_changed.emit()