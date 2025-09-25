# -*- coding: utf-8 -*-
import os
import csv
from datetime import datetime
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QPushButton,
                             QLabel, QMessageBox, QGroupBox, QDateEdit, QHeaderView, QTableWidgetItem)
from PyQt5.QtCore import Qt, QDate
from src.core.data_manager import DataManager
from src.core.stats import get_basic_stats, compute_yield
from src.core.utils import load_tags
from src.dialogs.yield_tag_editor import YieldTagEditor

def gather_file_info(file_path: str, gap_sec: float, rest_sec: float) -> dict:
    """收集單一檔案的摘要資訊"""
    dm = DataManager(file_path)
    df = dm.load_data()

    if df is None or df.empty:
        return {"檔案名稱": os.path.basename(file_path)}

    stats = get_basic_stats(df, gap_sec, rest_sec)
    good_tags, bad_tags = load_tags()

    boot_m, boot_s = stats.get("boot_mmss", (0, 0))
    run_m, run_s = stats.get("run_mmss", (0, 0))
    down_m, down_s = stats.get("down_mmss", (0, 0))
    rest_m, rest_s = stats.get("rest_mmss", (0, 0))

    return {
        "檔案名稱": os.path.basename(file_path),
        "IC TYPE": df["IC Type"].iloc[-1] if "IC Type" in df.columns else "—",
        "產品類別": dm.product_category or "—",
        "Operator": df["Operator"].iloc[-1] if "Operator" in df.columns else "—",
        "總數": len(df),
        "總開機時間": f"{boot_m}m {boot_s}s",
        "運行時間": f"{run_m}m {run_s}s",
        "停機時間": f"{down_m}m {down_s}s",
        "休息時間": f"{rest_m}m {rest_s}s",
        "稼動率": f"{stats.get('util', 0):.2f}%",
        "機台UPH": f"{stats.get('machine_uph', 0):.0f}",
        "實際UPH": f"{stats.get('uph', 0):.0f}",
        "良率": f"{compute_yield(df, good_tags, bad_tags):.2f}%"
    }

class FolderSummaryDialog(QDialog):
    """
    顯示資料夾內所有檔案的摘要資訊，並提供篩選和匯出功能。
    """
    def __init__(self, rows: list, folder_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("檔案摘要總覽")
        self.resize(1200, 650)

        self.all_rows = rows
        self.folder_path = folder_path
        self.headers = [
            "檔案名稱", "產品類別", "IC TYPE", "Operator",
            "總開機時間", "運行時間", "停機時間", "休息時間",
            "稼動率", "機台UPH", "實際UPH", "總數", "良率"
        ]

        # --- UI Elements ---
        self._setup_ui()
        self.populate_table(self.all_rows)

    def _setup_ui(self):
        # --- 日期篩選 ---
        box = QGroupBox("日期篩選 (依檔案最後修改時間)")
        h = QHBoxLayout(box)
        self.start_edit = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.end_edit = QDateEdit(QDate.currentDate(), calendarPopup=True)
        btn_apply = QPushButton("套用", clicked=self.apply_filter)
        btn_all = QPushButton("顯示全部", clicked=lambda: self.populate_table(self.all_rows))

        h.addWidget(QLabel("起:"))
        h.addWidget(self.start_edit)
        h.addWidget(QLabel("迄:"))
        h.addWidget(self.end_edit)
        h.addStretch()
        h.addWidget(btn_apply)
        h.addWidget(btn_all)

        # --- 表格 ---
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setSortingEnabled(True)

        # --- 按鈕 ---
        btn_export = QPushButton("匯出 CSV", clicked=self.export_csv)
        btn_tags = QPushButton("良率標籤設定", clicked=self.edit_yield_tags)

        hbtn = QHBoxLayout()
        hbtn.addStretch()
        hbtn.addWidget(btn_tags)
        hbtn.addWidget(btn_export)

        # --- 版面 ---
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addWidget(self.table, 1)
        lay.addLayout(hbtn)

    def edit_yield_tags(self):
        dlg = YieldTagEditor(self)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh_summary()

    def refresh_summary(self):
        """重新計算所有檔案的摘要並更新表格"""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            new_rows = []
            gap_sec = self.parent().get_gap_threshold()
            rest_sec = self.parent().get_rest_threshold()
            for r in self.all_rows:
                fname = r["檔案名稱"]
                fp = os.path.join(self.folder_path, fname)
                try:
                    info = gather_file_info(fp, gap_sec, rest_sec)
                    info["_mtime"] = os.path.getmtime(fp)
                    new_rows.append(info)
                except Exception as e:
                    print(f"[摘要刷新] 讀檔失敗 {fp} -> {e}")
            self.all_rows = new_rows
            self.populate_table(new_rows)
        finally:
            QApplication.restoreOverrideCursor()

    def populate_table(self, rows: list):
        """將資料填入表格中"""
        self.table.setRowCount(len(rows))
        for r, row_data in enumerate(rows):
            for c, h in enumerate(self.headers):
                val = row_data.get(h, "")
                item = QTableWidgetItem(str(val))
                # 為了排序，將數值和百分比轉為數字
                if isinstance(val, (int, float)) or (isinstance(val, str) and val.replace('.', '', 1).isdigit()):
                    item.setData(Qt.EditRole, float(val))
                elif isinstance(val, str) and val.endswith('%'):
                    item.setData(Qt.EditRole, float(val.strip('%')))

                if h in {"總數", "機台UPH", "實際UPH", "稼動率", "良率"}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(r, c, item)

    def apply_filter(self):
        """根據選擇的日期範圍過濾表格內容"""
        start_dt = self.start_edit.date().toPyDate()
        end_dt = self.end_edit.date().toPyDate()
        if start_dt > end_dt:
            QMessageBox.warning(self, "錯誤", "起始日期不可晚於結束日期！")
            return

        start_ts = datetime.combine(start_dt, datetime.min.time()).timestamp()
        end_ts = datetime.combine(end_dt, datetime.max.time()).timestamp()

        filtered = [row for row in self.all_rows if start_ts <= row.get("_mtime", 0) <= end_ts]
        self.populate_table(filtered)

    def export_csv(self):
        """將目前表格內容匯出為 CSV 檔案"""
        path, _ = QFileDialog.getSaveFileName(self, "匯出為 CSV", "summary.csv", "CSV Files (*.csv)")
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)
                for r in range(self.table.rowCount()):
                    row_data = [self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(self.table.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "完成", f"已匯出到：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"匯出失敗: {e}")