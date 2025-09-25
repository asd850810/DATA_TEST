# -*- coding: utf-8 -*-
import os
import sys
import time
from pathlib import Path
from watchdog.observers import Observer

import pandas as pd
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QSplitter, QScrollArea,
                             QDesktopWidget, QMessageBox, QGridLayout, QLabel, QLineEdit,
                             QPushButton, QSlider)

# --- Local Imports ---
from src.core.config import ConfigManager
from src.core.data_manager import DataLoader, is_text_column
from src.core.file_monitoring import FileChangeHandler, update_event
from src.core.stats import get_basic_stats
from src.core.constants import DEFAULT_COLOR_MAP
from src.core.utils import ask_folder_until_files

from src.dialogs.color_editor import ColorEditor
from src.dialogs.field_picker import FieldPicker
from src.dialogs.limit_editor import LimitEditor
from src.dialogs.yield_tag_editor import YieldTagEditor
from src.dialogs.folder_summary import FolderSummaryDialog, gather_file_info

from src.widgets.capability_panel import CapabilityPanel
from src.widgets.canvas_container import CanvasContainer
from src.widgets.small_run_plot import SmallRunPlotWidget
from src.widgets.toggle_switch import CustomToggleSwitch
from src.widgets.trend_canvas import TrendCanvas


class MainWindow(QMainWindow):
    """
    應用程式主視窗，整合所有 UI 元件與核心邏輯。
    """
    color_settings_changed = pyqtSignal()
    yield_tags_changed = pyqtSignal()

    GAP_FALLBACK = 20.0

    def __init__(self, file_path: str):
        super().__init__()

        # --- 基本屬性 ---
        self.df: pd.DataFrame | None = None
        self.file_path = Path(file_path) if file_path else None
        self.config_manager = ConfigManager()
        self.base_title = "SPC 數據分析軟體"
        self.setWindowTitle(self.base_title)
        self.setWindowIcon(QIcon("icon.ico")) # 假設圖示在根目錄

        # --- 使用者偏好 ---
        self.enabled_cols = set(filter(None, self.config_manager.get_value("enabled_cols", "").split(',')))
        self.ordered_cols = list(filter(None, self.config_manager.get_value("ordered_cols", "").split(',')))
        self.last_folder = Path(self.config_manager.get_value("last_folder", "", str))

        # --- 狀態旗標 ---
        self.paused = False
        self.lock_to_file = False
        self.current_field = None
        self.field_limits = {}
        self.small_canvases = {}
        self.data_loader = None
        self.show_downtime_lines = False
        self._last_update_call = 0.0
        self.current_loaded_file = None

        # --- 初始化 ---
        self._load_result_colors()
        if not self.file_path or not self.file_path.exists():
            self._try_find_latest_file()

        # --- UI 建構 ---
        self._build_ui()
        self.resize_by_screen()

        # --- 監控與定時器 ---
        self._init_file_watch()
        self._init_timer()

        # --- 訊號連接 ---
        self.color_settings_changed.connect(self.update_all_plots)
        self.yield_tags_changed.connect(self.update_all_plots)

        # --- 首次載入 ---
        if self.file_path and self.file_path.exists():
            self.update_charts()
            QTimer.singleShot(500, self._initial_plot)

    # =============================================================================
    # UI 建構輔助方法
    # =============================================================================
    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self._build_menu()
        self._build_function_bar()
        self._build_main_splitter()

    def _build_menu(self):
        menu_tools = self.menuBar().addMenu("工具")
        menu_tools.setToolTipsVisible(True)
        self.statusBar()

        actions = {
            "上下限總覽與編輯": (lambda: LimitEditor(self).exec_(), "一次檢視/編輯所有機種的 LSL/USL"),
            "長條圖顏色設定": (self.edit_colors, "設定『測試結果』長條圖的 OK/NG 顏色"),
            "檔案摘要": (self.show_folder_summary, "統計目前資料夾所有檔案的稼動率、UPH、良率"),
            "小圖欄位勾選": (lambda: FieldPicker(self).exec_(), "選擇 TrendCanvas 要顯示哪些欄位"),
            "良率標籤設定": (lambda: YieldTagEditor(self).exec_(), "設定良率計算時的 OK/NG 關鍵字"),
        }
        for name, (callback, tooltip) in actions.items():
            action = menu_tools.addAction(name, callback)
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)

    def _build_function_bar(self):
        bar = QWidget()
        layout = QGridLayout(bar)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setHorizontalSpacing(15)

        self.lsl_edit, self.usl_edit = QLineEdit(), QLineEdit()
        self.gap_threshold_edit = QLineEdit(str(self.config_manager.get_value("gap_threshold", self.GAP_FALLBACK, float)))
        self.rest_threshold_edit = QLineEdit(str(self.config_manager.get_value("rest_threshold_min", 15, float)))

        layout.addWidget(QLabel("上限:"), 0, 0, Qt.AlignRight)
        layout.addWidget(self.usl_edit, 0, 1)
        layout.addWidget(QLabel("下限:"), 1, 0, Qt.AlignRight)
        layout.addWidget(self.lsl_edit, 1, 1)
        layout.addWidget(QLabel("停機(秒):"), 0, 2, Qt.AlignRight)
        layout.addWidget(self.gap_threshold_edit, 0, 3)
        layout.addWidget(QLabel("休息(分):"), 1, 2, Qt.AlignRight)
        layout.addWidget(self.rest_threshold_edit, 1, 3)

        btn_update = QPushButton("更新設定值", clicked=self.update_all_settings)
        layout.addWidget(btn_update, 1, 4)

        btn_file = QPushButton("選擇檔案", clicked=self.select_file)
        btn_folder = QPushButton("選擇資料夾", clicked=self.select_folder)
        layout.addWidget(btn_file, 0, 4)
        layout.addWidget(btn_folder, 0, 5)

        self.toggle_switch = CustomToggleSwitch(checked=True)
        self.toggle_switch.toggled.connect(self.toggle_pause)
        layout.addWidget(self.toggle_switch, 0, 6)

        layout.addWidget(QLabel("解析度(%):"), 0, 7)
        self.slider = QSlider(Qt.Horizontal, minimum=1, maximum=100, value=self.config_manager.get_value("slider_value", 100, int))
        self.slider.valueChanged.connect(self.slider_changed)
        layout.addWidget(self.slider, 0, 8, 1, 2)

        self.main_layout.addWidget(bar)

    def _build_main_splitter(self):
        splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(splitter, 1)

        left_container = CanvasContainer(main_window=self)
        self.left_layout = left_container.layout
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(left_container)
        splitter.addWidget(scroll)

        right = QSplitter(Qt.Vertical)
        splitter.addWidget(right)

        self.capability_canvas = CapabilityPanel(main_window=self)
        self.trend_canvas = TrendCanvas(main_window=self)
        right.addWidget(self.capability_canvas)
        right.addWidget(self.trend_canvas)

        self.trend_canvas.subrange_selected.connect(self.analyze_subrange)
        self.trend_canvas.view_all_requested.connect(self.view_all_capability)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 8)
        right.setStretchFactor(0, 5)
        right.setStretchFactor(1, 5)

    def resize_by_screen(self):
        scr = QDesktopWidget().availableGeometry()
        self.resize(int(scr.width() * 0.5), int(scr.height() * 0.9))
        self.move(scr.right() - self.width(), scr.top())

    # =============================================================================
    # 核心功能與事件處理
    # =============================================================================
    def _init_file_watch(self):
        self.observer = Observer()
        if self.file_path and self.file_path.parent.is_dir():
            handler = FileChangeHandler(str(self.file_path))
            self.observer.schedule(handler, path=str(self.file_path.parent), recursive=False)
            self.observer.start()

    def _init_timer(self):
        self.timer = QTimer(interval=500, timeout=self.check_file_update)
        self.timer.start()

    def _try_find_latest_file(self):
        if self.last_folder.is_dir():
            files = list(self.last_folder.glob("*.txt")) + list(self.last_folder.glob("*.csv")) + list(self.last_folder.glob("*.log"))
            if files:
                self.file_path = max(files, key=lambda p: p.stat().st_mtime)

    def _initial_plot(self):
        if self.current_field:
            self.switch_run_chart(self.current_field)
        elif self.ordered_cols:
            self.switch_run_chart(self.ordered_cols[0])

    def check_file_update(self):
        if self.paused: return
        now = time.time()
        if now - self._last_update_call < 0.5: return
        self._last_update_call = now

        if update_event.is_set():
            update_event.clear()
            self.update_charts()
            return

        if not self.lock_to_file and self.file_path:
            folder = self.file_path.parent
            files = list(folder.glob("*.txt")) + list(folder.glob("*.csv")) + list(folder.glob("*.log"))
            if files:
                newest = max(files, key=lambda p: p.stat().st_mtime)
                if newest != self.file_path:
                    self.file_path = newest
                    self._update_watcher()
                    self.update_charts()

    def update_charts(self, force_reload=False):
        if self.paused or not self.file_path or not self.file_path.is_file():
            return

        current_mtime = self.file_path.stat().st_mtime
        if not force_reload and hasattr(self, 'last_mtime') and self.last_mtime == current_mtime:
            return
        self.last_mtime = current_mtime

        if self.data_loader and self.data_loader.isRunning():
            self.data_loader.stop_requested = True
            self.data_loader.wait()

        self.data_loader = DataLoader(str(self.file_path))
        self.data_loader.data_loaded.connect(self.handle_data_loaded)
        self.data_loader.start()

    def handle_data_loaded(self, df):
        if df is None or df.empty:
            return

        if self.df is not None and len(df) == len(self.df) and df["datetime"].iloc[-1] == self.df["datetime"].iloc[-1]:
            return

        self.df = self._process_loaded_df(df)
        self.setWindowTitle(f"{self.base_title} — {self.file_path.name}")

        is_new_file = self.current_loaded_file != self.file_path
        self.current_loaded_file = self.file_path

        all_measure_cols = [c for c in self.df.columns if c not in ("datetime", "機種")]
        self.rebuild_small_canvases(all_measure_cols, fresh=is_new_file)

        self.update_all_plots()

        if is_new_file or not self.current_field:
            self.current_field = self.ordered_cols[0] if self.ordered_cols else None

        if self.current_field:
            self.switch_run_chart(self.current_field)

    def _process_loaded_df(self, df):
        rename_dict = {"Picth_X": "Picth_MD", "Picth_Y": "Picth_TD"}
        df.rename(columns=rename_dict, inplace=True)
        return df

    def update_all_plots(self):
        """重繪所有小圖和當前大圖"""
        if self.df is None: return
        for canvas in self.small_canvases.values():
            canvas.update_run(self.df)
        if self.current_field:
            self.switch_run_chart(self.current_field)

    def switch_run_chart(self, name: str):
        if self.df is None or name not in self.df.columns:
            return
        self.current_field = name

        if is_text_column(self.df[name]):
            self._display_text_column_stats(name)
        else:
            self._display_numeric_column_stats(name)

        self._update_limit_editors()

    def _display_text_column_stats(self, name):
        stats = get_basic_stats(self.df, self.get_gap_threshold(), self.get_rest_threshold())
        header = f'<div style="font-size:18px;font-weight:bold;margin-bottom:5px;">{name}</div>'
        main_stats = [
            ("目前機種", self.get_current_model() or "—"),
            ("取樣數", f"{len(self.df)}"),
            ("總開機時間", f"{stats['boot_mmss'][0]}m {stats['boot_mmss'][1]}s"),
            ("運行時間", f"{stats['run_mmss'][0]}m {stats['run_mmss'][1]}s"),
            ("停機時間", f"{stats['down_mmss'][0]}m {stats['down_mmss'][1]}s"),
            ("休息時間", f"{stats['rest_mmss'][0]}m {stats['rest_mmss'][1]}s"),
            ("稼動率", f"{stats['util']:.2f}%"),
            ("UPH", f"{stats['uph']:.0f}"),
        ]
        second_stats = [("機台UPH", f"{stats['machine_uph']:.0f}")]

        self.capability_canvas.show_info(header, main_stats, second_stats)
        self.trend_canvas.plot_test_result_bar(self.df, field=name)
        self.lsl_edit.clear()
        self.usl_edit.clear()

    def _display_numeric_column_stats(self, name):
        stats = get_basic_stats(self.df, self.get_gap_threshold(), self.get_rest_threshold())
        self.capability_canvas.plot_capability(
            data_series=self.df[name], name=name,
            uph_val=stats['uph'], util_val=stats['util'], downtime_val=stats['downtime'],
            total_time_val=stats['total_sec'], machine_uph_val=stats['machine_uph'],
            current_model=self.get_current_model(), rest_mmss=stats['rest_mmss']
        )
        self.trend_canvas.plot_trend(self.df, name=name)

    def _update_limit_editors(self):
        if self.current_field and not is_text_column(self.df[self.current_field]):
            model = self.get_current_model()
            lsl, usl = self.config_manager.get_limits(self.current_field, model)
            if lsl is None or usl is None:
                lsl, usl = self.df[self.current_field].min(), self.df[self.current_field].max()
            self.lsl_edit.setText(str(lsl))
            self.usl_edit.setText(str(usl))
        else:
            self.lsl_edit.clear()
            self.usl_edit.clear()

    def rebuild_small_canvases(self, measure_cols, fresh=False):
        if fresh:
            for i in reversed(range(self.left_layout.count())):
                w = self.left_layout.itemAt(i).widget()
                if w: w.deleteLater()
            self.small_canvases.clear()

        chosen = self.enabled_cols or set(measure_cols)

        # 維持已有的排序，新項目加在後面
        current_ordered = [c for c in self.ordered_cols if c in chosen]
        new_items = [c for c in measure_cols if c in chosen and c not in current_ordered]
        self.ordered_cols = current_ordered + new_items
        self.config_manager.set_value("ordered_cols", ",".join(self.ordered_cols))

        for col in self.ordered_cols:
            if col not in self.small_canvases:
                canvas = SmallRunPlotWidget(name=col, main_window=self)
                self.small_canvases[col] = canvas
                self.left_layout.addWidget(canvas)

    def analyze_subrange(self, start_idx, end_idx):
        if self.df is None or self.current_field not in self.df.columns: return

        # This needs rework as indices are from sampled data
        # For now, let's just re-analyze the full data
        self.view_all_capability()

    def view_all_capability(self):
        if self.df is not None and self.current_field:
            self.switch_run_chart(self.current_field)

    # =============================================================================
    # 事件/訊號回呼 (Callbacks)
    # =============================================================================
    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "選擇資料夾", str(self.last_folder))
        if not folder_path: return

        self.last_folder = Path(folder_path)
        self.config_manager.set_value("last_folder", str(self.last_folder))
        self.lock_to_file = False

        self._try_find_latest_file()
        if not self.file_path:
            QMessageBox.warning(self, "警告", "該資料夾沒有 TXT、CSV 或 LOG 檔案！")
            return

        self._update_watcher()
        self.update_charts(force_reload=True)

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇檔案", str(self.last_folder), "Data Files (*.txt *.csv *.log)")
        if not path: return

        self.file_path = Path(path)
        self.last_folder = self.file_path.parent
        self.config_manager.set_value("last_folder", str(self.last_folder))
        self.lock_to_file = True

        self._update_watcher()
        self.update_charts(force_reload=True)

    def _update_watcher(self):
        self.observer.unschedule_all()
        if self.file_path and self.file_path.parent.is_dir():
            handler = FileChangeHandler(str(self.file_path))
            self.observer.schedule(handler, path=str(self.file_path.parent), recursive=False)

    def update_all_settings(self):
        """儲存所有設定並重繪圖表"""
        try:
            new_lsl = float(self.lsl_edit.text())
            new_usl = float(self.usl_edit.text())
            if self.current_field:
                self.config_manager.set_limits(self.current_field, new_lsl, new_usl, self.get_current_model())
        except ValueError:
            # 可能是文字欄位，忽略
            pass

        self.config_manager.set_value("gap_threshold", self.get_gap_threshold())
        self.config_manager.set_value("rest_threshold_min", self.get_rest_threshold(in_minutes=True))

        self.update_all_plots()

    def slider_changed(self, value):
        self.config_manager.set_value("slider_value", value)
        self.default_bin_num = max(10, value)
        self.update_all_plots()

    def toggle_pause(self, is_on):
        self.paused = not is_on
        self.show_downtime_lines = not is_on
        if not self.paused:
            self.update_charts()
        else:
            # Re-plot with downtime lines
            self.update_all_plots()

    def edit_colors(self):
        self._load_result_colors() # 確保是最新的
        ordered_cats = self.result_order or sorted(self.color_map.keys())
        dlg = ColorEditor(self.color_map, ordered_cats, self)
        dlg.exec_()

    def show_folder_summary(self):
        if not self.file_path or not self.file_path.parent.is_dir():
            QMessageBox.warning(self, "錯誤", "目前檔案路徑無效，無法列出摘要！")
            return

        folder = self.file_path.parent
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ['.txt', '.csv', '.log']]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if not files:
            QMessageBox.information(self, "提示", "此資料夾沒有 TXT/CSV/LOG 檔案。")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rows = []
            gap_val = self.get_gap_threshold()
            rest_sec = self.get_rest_threshold()
            for fp in files:
                try:
                    info = gather_file_info(str(fp), gap_val, rest_sec)
                    info["_mtime"] = fp.stat().st_mtime
                    rows.append(info)
                except Exception as e:
                    print(f"[摘要] 讀檔失敗 {fp} → {e}")
        finally:
            QApplication.restoreOverrideCursor()

        if rows:
            FolderSummaryDialog(rows, str(folder), self).exec_()
        else:
            QMessageBox.warning(self, "錯誤", "無法讀取任何檔案！")

    # =============================================================================
    # Getter / Helper 方法
    # =============================================================================
    def get_gap_threshold(self) -> float:
        try:
            return float(self.gap_threshold_edit.text())
        except (ValueError, AttributeError):
            return self.GAP_FALLBACK

    def get_rest_threshold(self, in_minutes=False) -> float:
        try:
            val = float(self.rest_threshold_edit.text())
            return val if in_minutes else val * 60.0
        except (ValueError, AttributeError):
            return 15.0 if in_minutes else 900.0

    def get_current_model(self):
        if self.df is not None and "機種" in self.df.columns and not self.df.empty:
            return str(self.df["機種"].iloc[-1])
        return None

    def _load_result_colors(self):
        self.color_map = DEFAULT_COLOR_MAP.copy()
        custom_colors = self.config_manager.get_result_colors()
        self.color_map.update(custom_colors)

    def closeEvent(self, event):
        self.timer.stop()
        self.observer.stop()
        self.observer.join()
        if self.data_loader and self.data_loader.isRunning():
            self.data_loader.stop_requested = True
            self.data_loader.wait(1000)
        event.accept()
        super().closeEvent(event)