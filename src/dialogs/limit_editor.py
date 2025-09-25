# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (QDialog, QTableWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidgetItem, QMessageBox, QHeaderView)
from PyQt5.QtCore import Qt

class LimitEditor(QDialog):
    """
    提供一個表格介面，讓使用者可以一次性檢視、編輯和刪除所有
    共用及特定機種的量測上下限。
    """
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setWindowTitle("上下限總覽與編輯")
        self.resize(480, 400)
        self.mw = main_window
        self.config_manager = main_window.config_manager

        self.tbl = QTableWidget(0, 4, self)
        self.tbl.setHorizontalHeaderLabels(["機種 (空=共用)", "欄位", "LSL", "USL"])
        header = self.tbl.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self._load_data()

        btnSave = QPushButton("儲存並套用")
        btnDelete = QPushButton("刪除選取列")
        btnCancel = QPushButton("取消")
        btnSave.clicked.connect(self._save)
        btnDelete.clicked.connect(self._delete_rows)
        btnCancel.clicked.connect(self.reject)

        layBtn = QHBoxLayout()
        layBtn.addStretch()
        layBtn.addWidget(btnDelete)
        layBtn.addWidget(btnSave)
        layBtn.addWidget(btnCancel)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tbl)
        lay.addLayout(layBtn)

    def _load_data(self):
        """從設定檔載入所有上下限資料並填入表格。"""
        all_keys = self.config_manager.get_all_limit_keys()
        for k in all_keys:
            if not k.endswith("/lsl"):
                continue

            path = k.rsplit('/', 1)[0]
            model_field = path.split('/', 1)[1]

            if '_' in model_field:
                model, field = model_field.split('_', 1)
                if model and not model.isdigit():
                    continue
            else:
                model, field = "", model_field

            lsl = self.config_manager.get_value(f"{path}/lsl", 0.0, float)
            usl = self.config_manager.get_value(f"{path}/usl", 0.0, float)

            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            for col, text in enumerate([model, field, str(lsl), str(usl)]):
                item = QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl.setItem(row, col, item)
        self.tbl.resizeColumnsToContents()

    def _delete_rows(self):
        """刪除選中的列及其對應的設定。"""
        rows = sorted({idx.row() for idx in self.tbl.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "提示", "請先在表格中選取要刪除的列")
            return

        if QMessageBox.question(self, "確認刪除", f"確定要刪除 {len(rows)} 列？\n（此動作無法復原）",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        for row in rows:
            model = self.tbl.item(row, 0).text().strip()
            field = self.tbl.item(row, 1).text().strip()
            key = f"{model}_{field}" if model else field
            self.config_manager.remove_limit(f"field_limits/{key}/lsl")
            self.config_manager.remove_limit(f"field_limits/{key}/usl")
            self.tbl.removeRow(row)

        self.mw.field_limits.clear()
        self.mw.update_all_plots()
        QMessageBox.information(self, "完成", "已刪除指定的上下限設定。")


    def _save(self):
        """儲存表格中的所有變更到設定檔。"""
        for row in range(self.tbl.rowCount()):
            model = self.tbl.item(row, 0).text().strip()
            field = self.tbl.item(row, 1).text().strip()

            if model and not model.isdigit():
                continue

            try:
                lsl = float(self.tbl.item(row, 2).text())
                usl = float(self.tbl.item(row, 3).text())
            except (ValueError, AttributeError):
                QMessageBox.warning(self, "格式錯誤", f"第 {row + 1} 列的 LSL/USL 應為數字。")
                return

            self.config_manager.set_limits(field, lsl, usl, model)

        self.mw.field_limits.clear()
        self.mw.update_all_plots()

        QMessageBox.information(self, "完成", "已儲存並套用新的上下限。")
        self.accept()