# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QListWidgetItem
from PyQt5.QtCore import Qt

class FieldPicker(QDialog):
    """
    讓使用者從現有的量測欄位中，勾選想在小圖/大圖裡顯示的項目。
    """
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.setWindowTitle("選擇要顯示的量測欄位")
        self.resize(300, 400)

        all_cols = [c for c in self.mw.df.columns if c not in ("datetime", "機種")]
        previously_enabled = self.mw.enabled_cols

        self.listw = QListWidget(self)
        for col in all_cols:
            item = QListWidgetItem(col, self.listw)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # 如果沒有先前的設定，預設全選
            is_checked = (col in previously_enabled) if previously_enabled else True
            item.setCheckState(Qt.Checked if is_checked else Qt.Unchecked)

        btn_ok = QPushButton("套用")
        btn_all = QPushButton("全選")
        btn_none = QPushButton("全不選")
        btn_ok.clicked.connect(self.apply)
        btn_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        btn_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))

        lay_btn = QHBoxLayout()
        lay_btn.addStretch()
        lay_btn.addWidget(btn_ok)
        lay_btn.addWidget(btn_all)
        lay_btn.addWidget(btn_none)

        lay = QVBoxLayout(self)
        lay.addWidget(self.listw)
        lay.addLayout(lay_btn)

    def _set_all(self, state):
        """全選或全不選列表中的項目"""
        for i in range(self.listw.count()):
            self.listw.item(i).setCheckState(state)

    def apply(self):
        """套用選擇，更新主視窗的顯示欄位"""
        chosen = {self.listw.item(i).text() for i in range(self.listw.count()) if self.listw.item(i).checkState() == Qt.Checked}

        self.mw.enabled_cols = chosen
        self.mw.config_manager.set_value("enabled_cols", ",".join(sorted(list(chosen))))

        self.mw.rebuild_small_canvases(list(chosen), fresh=True)

        if self.mw.df is not None and not self.mw.df.empty:
            for canvas in self.mw.small_canvases.values():
                canvas.update_run(self.mw.df)

        if chosen:
            target = self.mw.current_field if self.mw.current_field in chosen else next(iter(chosen))
            self.mw.switch_run_chart(target)
        else:
            self.mw.capability_canvas.clear_panel()
            self.mw.trend_canvas.clear()
            self.mw.current_field = None

        self.accept()