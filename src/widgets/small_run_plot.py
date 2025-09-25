# -*- coding: utf-8 -*-
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QMimeData
from PyQt5.QtGui import QDrag
from src.core.data_manager import is_text_column, normalize_str_col
from src.core.constants import DEFAULT_COLOR_MAP

def make_brushes(cats):
    """根據類別列表產生對應顏色的 pg.mkBrush 列表。"""
    color_map = DEFAULT_COLOR_MAP.copy()
    # 這裡可以加入從設定檔讀取自訂顏色的邏輯

    def _parent_key(cat: str) -> str:
        up = cat.upper()
        if up.startswith("OK"): return "OK"
        if up.startswith("NG"): return "NG"
        return cat

    return [pg.mkBrush(color_map.get(c) or color_map.get(_parent_key(c)) or "gray") for c in cats]

class SmallRunPlotWidget(pg.PlotWidget):
    """
    用於顯示單一量測項目的迷你趨勢圖，支援點擊切換和拖放排序。
    """
    def __init__(self, parent=None, name="SmallRun", main_window=None):
        super().__init__(parent)
        self.name = name
        self.main_window = main_window
        self.setFixedHeight(180)
        self.getPlotItem().showGrid(x=True, y=True, alpha=0.1)
        self.setBackground('w')
        self.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)
        self.drag_start_position = None
        self.is_dragging = False

    def mousePressEvent(self, event):
        if self.main_window.df is None:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
            self.is_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.main_window.df is None:
            super().mouseMoveEvent(event)
            return
        if event.buttons() & Qt.LeftButton and self.drag_start_position:
            distance = (event.pos() - self.drag_start_position).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self.is_dragging = True
                drag = QDrag(self)
                mime_data = QMimeData()
                mime_data.setText(self.name)
                drag.setMimeData(mime_data)
                pixmap = self.grab()
                drag.setPixmap(pixmap)
                drag.setHotSpot(pixmap.rect().center())
                drag.exec_(Qt.MoveAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.main_window.df is None:
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.LeftButton and not self.is_dragging:
            if self.main_window:
                self.main_window.switch_run_chart(self.name)
        self.is_dragging = False
        super().mouseReleaseEvent(event)

    def update_run(self, df):
        if df.empty or self.name not in df.columns:
            self.clear()
            self.setTitle(f"<span style='font-family: Microsoft JhengHei;'>{self.name} (無資料)</span>")
            return

        if is_text_column(df[self.name]):
            self._plot_bar_chart(df)
        else:
            self._plot_line_chart(df)

    def _plot_bar_chart(self, df):
        vals = normalize_str_col(df[self.name]).iloc[::max(1, len(df) // 100)].values
        cats, counts = np.unique(vals, return_counts=True)
        order = np.argsort(counts)[::-1]
        cats, counts = cats[order], counts[order]

        self.clear()
        bar = pg.BarGraphItem(x=np.arange(len(cats)), height=counts, width=0.6, brushes=make_brushes(cats))
        self.addItem(bar)

        axis = self.getPlotItem().getAxis("bottom")
        axis.setTicks([list(zip(np.arange(len(cats)), cats))])
        self.setTitle(f"<span style='font-family:Microsoft JhengHei;'>{self.name}</span>")

    def _plot_line_chart(self, df):
        max_points = 100
        total = len(df)
        idx = np.linspace(0, total - 1, max_points, dtype=int) if total > max_points else np.arange(total)
        values = df[self.name].iloc[idx].values

        model = self.main_window.get_current_model()
        LSL, USL = self.main_window.config_manager.get_limits(self.name, model)
        if LSL is None or USL is None:
             LSL, USL = values.min(), values.max()

        if hasattr(self, "last_values") and np.array_equal(values, self.last_values) and \
           getattr(self, "last_LSL", None) == LSL and getattr(self, "last_USL", None) == USL:
            return

        self.last_values, self.last_LSL, self.last_USL = values, LSL, USL

        self.clear()
        self.plot(idx, values, pen=pg.mkPen("blue", width=2))
        self.addItem(pg.InfiniteLine(pos=LSL, angle=0, pen=pg.mkPen("red", width=2, style=Qt.DashLine)))
        self.addItem(pg.InfiniteLine(pos=USL, angle=0, pen=pg.mkPen("green", width=2, style=Qt.DashLine)))
        self.setTitle(f'<span style="font-family: Microsoft JhengHei;">{self.name}</span>')

        for axis in ("left", "bottom"):
            self.getPlotItem().getAxis(axis).setTextPen(pg.mkPen("black"))