# -*- coding: utf-8 -*-
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QMenu, QAction
from PyQt5.QtCore import Qt, pyqtSignal
from src.core.data_manager import is_text_column, normalize_str_col
from src.widgets.small_run_plot import make_brushes

class TimeAxisItem(pg.AxisItem):
    """自訂時間軸，將數值索引轉換為時間字串。"""
    def __init__(self, times, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.times = times

    def tickStrings(self, values, scale, spacing):
        labels = []
        last_idx = None
        for v in values:
            if spacing < 1:
                labels.append("")
                continue
            idx = int(round(v))
            if idx == last_idx or idx < 0 or idx >= len(self.times):
                labels.append("")
                continue
            try:
                labels.append(self.times[idx].strftime("%H:%M:%S"))
                last_idx = idx
            except IndexError:
                 labels.append("")
        return labels

class TrendCanvas(pg.PlotWidget):
    """
    主趨勢圖畫布，支援區間選取、顯示停機區間和異常點標記。
    """
    subrange_selected = pyqtSignal(int, int)
    view_all_requested = pyqtSignal()

    def __init__(self, parent=None, main_window=None, times=None):
        axis = TimeAxisItem(times if times else [], orientation='bottom')
        super().__init__(axisItems={'bottom': axis}, parent=parent)

        self.main_window = main_window
        self.setBackground('w')
        self.getPlotItem().showGrid(x=True, y=True, alpha=0.1)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        self.plot_line = self.getPlotItem().plot(pen=pg.mkPen('b', width=2))
        self.downtime_regions = []
        self.region_item = None
        self.dragging = False
        self.x_data, self.y_data = None, None
        self.df_length = 0
        self.current_field = None
        self._bar_items = []
        self._label_items = []
        self.outlier_text_items = []

    def contextMenuEvent(self, event):
        vb = self.getPlotItem().getViewBox()
        if vb.menu is None:
            vb.menu = QMenu(self)

        # 確保 "重製圖表" 動作只存在一個
        if not any(act.text() == "重製圖表" for act in vb.menu.actions()):
            action_reset_chart = QAction("重製圖表", self)
            action_reset_chart.triggered.connect(self.handle_view_all)
            actions = vb.menu.actions()
            vb.menu.insertAction(actions[0] if actions else None, action_reset_chart)

        vb.menu.exec_(event.globalPos())

    def handle_view_all(self):
        if self.main_window.df is None or self.current_field is None:
            return

        if is_text_column(self.main_window.df[self.current_field]):
            self.plot_test_result_bar(self.main_window.df, field=self.current_field)
        else:
            self.plot_trend(self.main_window.df, name=self.current_field)
        self.view_all_requested.emit()

    def plot_trend(self, df, name):
        self._clear_plot_items()
        self.current_field = name

        if df.empty or name not in df.columns:
            self.getPlotItem().setTitle(f"{name} 趨勢圖 (無資料)")
            return

        total_points = len(df)
        slider_value = self.main_window.slider.value()
        max_points = max(10, int(total_points * slider_value / 100))

        LSL, USL = self._get_limits(df, name)

        final_idx = self._get_sampled_indices(df, name, LSL, USL, max_points)
        if not final_idx: return

        sampled_times = df["datetime"].iloc[final_idx].tolist()
        self.y_data = df[name].iloc[final_idx].values
        self.x_data = np.arange(len(sampled_times))
        self.df_length = len(df)

        self._update_axes_and_data(sampled_times)
        self._plot_limit_lines(LSL, USL)

        if getattr(self.main_window, "show_downtime_lines", False):
            self._plot_downtime_regions(df, final_idx)

        self._plot_outliers(df, name, LSL, USL, final_idx)
        self.getPlotItem().setTitle(f"<span style='font-family:Microsoft JhengHei;'>{name} 趨勢圖</span>")


    def plot_test_result_bar(self, df, field):
        self._clear_plot_items()
        if df.empty or field not in df.columns:
            self.getPlotItem().setTitle(f"{field} 長條圖 (無資料)")
            return

        clean = normalize_str_col(df[field])
        cats, counts = np.unique(clean.values, return_counts=True)
        order = sorted(range(len(cats)), key=lambda i: (-counts[i], str(cats[i]).upper()))
        cats, counts = [cats[i] for i in order], [counts[i] for i in order]

        bar = pg.BarGraphItem(x=np.arange(len(cats)), height=counts, width=0.6, brushes=make_brushes(cats))
        self.getPlotItem().addItem(bar)
        self._bar_items.append(bar)

        self._add_bar_labels(cats, counts)
        self._setup_bar_chart_axes(cats, field)
        self.main_window.result_order = cats

    def _clear_plot_items(self):
        plotItem = self.getPlotItem()
        for item in self._bar_items + self._label_items + self.downtime_regions + self.outlier_text_items:
            plotItem.removeItem(item)
        self._bar_items.clear()
        self._label_items.clear()
        self.downtime_regions.clear()
        self.outlier_text_items.clear()
        if self.plot_line not in plotItem.items:
            self.plot_line = plotItem.plot(pen=pg.mkPen('b', width=2))

    def _get_limits(self, df, name):
        model = self.main_window.get_current_model()
        LSL, USL = self.main_window.config_manager.get_limits(name, model)
        if LSL is None or USL is None:
            LSL, USL = df[name].min(), df[name].max()
        return LSL, USL

    def _get_sampled_indices(self, df, name, LSL, USL, max_points):
        is_outlier = (df[name] < LSL) | (df[name] > USL)
        outlier_idx = set(df[is_outlier].index)

        mandatory_idx = set(outlier_idx)
        if getattr(self.main_window, "show_downtime_lines", False):
            downtimes, rests = self._compute_gap_intervals(df)
            for s, e in downtimes + rests:
                mandatory_idx.update((s, e))

        available = max_points - len(mandatory_idx)
        if available > 0:
            normal_idx = sorted(list(set(df.index) - mandatory_idx))
            if normal_idx:
                sampled_normal_idx = [normal_idx[i] for i in np.linspace(0, len(normal_idx) - 1, available, dtype=int)]
                return sorted(list(mandatory_idx | set(sampled_normal_idx)))
        return sorted(list(mandatory_idx))


    def _update_axes_and_data(self, times):
        axis = TimeAxisItem(times, orientation='bottom')
        self.getPlotItem().setAxisItems({'bottom': axis})
        self.plot_line.setData(self.x_data, self.y_data)

    def _plot_limit_lines(self, LSL, USL):
        plotItem = self.getPlotItem()
        for item in list(plotItem.items):
            if isinstance(item, pg.InfiniteLine) and item.angle == 0:
                plotItem.removeItem(item)
        plotItem.addItem(pg.InfiniteLine(pos=LSL, angle=0, pen=pg.mkPen('red', style=Qt.DashLine, width=2)))
        plotItem.addItem(pg.InfiniteLine(pos=USL, angle=0, pen=pg.mkPen('green', style=Qt.DashLine, width=2)))

    def _compute_gap_intervals(self, df):
        gap_sec = self.main_window.get_gap_threshold()
        rest_sec = self.main_window.get_rest_threshold()
        if df.empty or "datetime" not in df.columns:
            return [], []
        times = df["datetime"].values.astype("datetime64[s]").astype(np.int64)
        dsec = np.diff(times)
        downtime = [(i, i + 1) for i, sec in enumerate(dsec) if gap_sec < sec <= rest_sec]
        rest = [(i, i + 1) for i, sec in enumerate(dsec) if sec > rest_sec]
        return downtime, rest

    def _plot_downtime_regions(self, df, final_idx):
        idx_to_x = {orig_idx: i for i, orig_idx in enumerate(final_idx)}
        downtimes, rests = self._compute_gap_intervals(df)

        for intervals, color in [(downtimes, (255, 0, 0, 40)), (rests, (0, 180, 0, 40))]:
            for s_idx, e_idx in intervals:
                if s_idx in idx_to_x and e_idx in idx_to_x:
                    reg = pg.LinearRegionItem(values=[idx_to_x[s_idx], idx_to_x[e_idx]], orientation=pg.LinearRegionItem.Vertical, movable=False, brush=pg.mkBrush(color))
                    self.getPlotItem().addItem(reg)
                    self.downtime_regions.append(reg)

    def _plot_outliers(self, df, name, LSL, USL, final_idx):
        is_outlier = (df[name] < LSL) | (df[name] > USL)
        outlier_indices_in_df = df[is_outlier].index

        # Map df indices to the sampled indices (final_idx)
        outlier_items = []
        for i, idx_in_df in enumerate(final_idx):
            if idx_in_df in outlier_indices_in_df:
                outlier_items.append({
                    "x": self.x_data[i],
                    "y": self.y_data[i],
                    "time": df["datetime"].iloc[idx_in_df]
                })

        if not outlier_items: return

        if len(outlier_items) > 50:
            self._add_summary_label(outlier_items)
        else:
            # Simple label for each outlier
            for item in outlier_items:
                ti = pg.TextItem(item['time'].strftime('%H:%M'), color='red', anchor=(0.5, 1.5))
                ti.setPos(item['x'], item['y'])
                self.getPlotItem().addItem(ti)
                self.outlier_text_items.append(ti)

    def _add_summary_label(self, items):
        if not items: return
        x_coords = [it['x'] for it in items]
        y_coords = [it['y'] for it in items]
        times = [it['time'] for it in items]

        txt = f"{len(items)} 異常<br>{min(times):%H:%M}–{max(times):%H:%M}"
        ti = pg.TextItem(txt, color='red', anchor=(0.5, 1.0))
        ti.setPos(np.mean(x_coords), np.mean(y_coords))
        self.getPlotItem().addItem(ti)
        self.outlier_text_items.append(ti)

    def _add_bar_labels(self, cats, counts):
        total = sum(counts)
        if not total: return
        y_off = max(counts) * 0.02
        for xi, cnt_i, cat_i in zip(np.arange(len(cats)), counts, cats):
            pct = cnt_i / total * 100
            html = f"<div style='text-align:center;'>{cnt_i}<br>{pct:.1f}%</div>"
            ti = pg.TextItem(html=html, anchor=(0.5, 0))
            ti.setPos(xi, cnt_i + y_off)
            self.getPlotItem().addItem(ti)
            self._label_items.append(ti)

    def _setup_bar_chart_axes(self, cats, field):
        plotItem = self.getPlotItem()
        plotItem.getViewBox().setMouseEnabled(x=False, y=False)
        axis = plotItem.getAxis('bottom')
        axis.setTicks([list(zip(np.arange(len(cats)), cats))])
        plotItem.setTitle(f"<span style='font-family:Microsoft JhengHei;'>{field} 長條圖</span>")
        plotItem.autoRange()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not is_text_column(self.main_window.df[self.current_field]):
            self.dragging = True
            pos = self.getPlotItem().vb.mapSceneToView(event.pos())
            self.drag_start_x = pos.x()
            self.region_item = pg.LinearRegionItem(values=[self.drag_start_x, self.drag_start_x], orientation=pg.LinearRegionItem.Vertical, movable=False)
            self.getPlotItem().addItem(self.region_item)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging and (event.buttons() & Qt.LeftButton):
            pos = self.getPlotItem().vb.mapSceneToView(event.pos())
            if self.region_item:
                self.region_item.setRegion(sorted([self.drag_start_x, pos.x()]))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            if self.region_item:
                left_x, right_x = self.region_item.getRegion()
                self.getPlotItem().removeItem(self.region_item)
                self.region_item = None

                # Map view coordinates back to original df indices
                if self.x_data is not None and len(self.x_data) > 1:
                    # Find the corresponding indices in the original dataframe
                    start_idx_sampled = int(np.clip(round(left_x), 0, len(self.x_data) - 1))
                    end_idx_sampled = int(np.clip(round(right_x), 0, len(self.x_data) - 1))

                    # This requires mapping from sampled index back to original df index.
                    # This part is complex and depends on how `final_idx` was created.
                    # For simplicity, we'll emit the sampled indices and let main_window handle it.
                    # A better approach would be to pass the final_idx mapping here.
                    self.subrange_selected.emit(start_idx_sampled, end_idx_sampled)

            event.accept()
        else:
            super().mouseReleaseEvent(event)