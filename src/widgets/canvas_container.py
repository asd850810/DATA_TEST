# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QWidget, QVBoxLayout

class CanvasContainer(QWidget):
    """
    一個可拖放重排列的小圖容器。
    讓使用者可以透過拖放，調整小運行圖的顯示順序。
    """
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.main_window = main_window

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(5)
        self.setLayout(self.layout)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        widget_name = event.mimeData().text()
        dragged_widget = None

        for i in range(self.layout.count()):
            w = self.layout.itemAt(i).widget()
            if w and hasattr(w, "name") and w.name == widget_name:
                dragged_widget = w
                break

        if dragged_widget:
            self.layout.removeWidget(dragged_widget)
            drop_pos = event.pos()
            insert_at = 0
            for i in range(self.layout.count()):
                w = self.layout.itemAt(i).widget()
                if w and drop_pos.y() < w.pos().y() + w.height() / 2:
                    insert_at = i
                    break
                else:
                    insert_at = i + 1
            self.layout.insertWidget(insert_at, dragged_widget)

        event.accept()

        if self.main_window:
            new_order = [self.layout.itemAt(i).widget().name for i in range(self.layout.count()) if self.layout.itemAt(i).widget()]
            self.main_window.ordered_cols = new_order
            self.main_window.config_manager.set_value("ordered_cols", ",".join(new_order))