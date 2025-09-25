# -*- coding: utf-8 -*-
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt
from scipy.stats import gaussian_kde

class CapabilityPanel(QWidget):
    """
    能力圖顯示面板，包含一個直方圖和一個顯示統計資訊的標籤。
    """
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.main_window = main_window

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.getPlotItem().showGrid(x=True, y=True, alpha=0.1)
        self.plot_widget.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)

        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.info_label.setStyleSheet(
            "QLabel { background-color: rgba(255,255,255,180); border: 1px solid gray; padding: 5px; }"
        )
        self.info_label.setMinimumHeight(550)
        self.info_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        layout.addWidget(self.plot_widget, 1)
        layout.addWidget(self.info_label)

    def clear_panel(self):
        self.plot_widget.clear()
        self.info_label.clear()

    def show_info(self, header: str, main_stats: list, second_stats: list):
        """僅顯示表格資訊，用於文字類欄位。"""
        self.plot_widget.clear()
        html = self._create_html_table(main_stats, second_stats)
        self.info_label.setText(header + html)

    def plot_capability(self, data_series, name="Unknown", uph_val=None, util_val=None,
                        downtime_val=None, total_time_val=None, machine_uph_val=None,
                        current_model=None, rest_mmss=(0, 0)):
        if data_series is None or data_series.empty:
            self.clear_panel()
            self.plot_widget.getPlotItem().setTitle(f"{name} - 過程能力報告 (無資料)")
            return

        clean_series = data_series.dropna()
        if clean_series.empty:
            self.clear_panel()
            self.plot_widget.getPlotItem().setTitle(f"{name} - 過程能力報告 (無資料)")
            return

        self.clear_panel()
        self._plot_histogram_and_kde(clean_series, name)

        LSL, USL = self._get_and_plot_limits(name, current_model, clean_series)

        stats_html = self._calculate_and_format_stats(
            clean_series, name, LSL, USL, uph_val, util_val, downtime_val,
            total_time_val, machine_uph_val, current_model, rest_mmss
        )
        self.info_label.setText(stats_html)

        self._finalize_plot_appearance(name)

    def _plot_histogram_and_kde(self, series, name):
        bin_num = getattr(self.main_window, 'default_bin_num', 30)
        counts, bins = np.histogram(series, bins=bin_num)
        bin_width = bins[1] - bins[0]

        bg = pg.BarGraphItem(x=bins[:-1], height=counts, width=bin_width * 0.9, brush='skyblue', pen=pg.mkPen('black'))
        self.plot_widget.addItem(bg)

        if len(series) >= 3:
            try:
                kde = gaussian_kde(series)
                x_vals = np.linspace(bins[0], bins[-1], 200)
                kde_vals = kde(x_vals) * bin_width * len(series)
                self.plot_widget.plot(x_vals, kde_vals, pen=pg.mkPen('blue', width=2))
            except np.linalg.LinAlgError:
                try:
                    jitter = max(np.std(series) * 0.01, 1e-6)
                    vals_jitter = series + np.random.normal(0, jitter, len(series))
                    kde = gaussian_kde(vals_jitter)
                    x_vals = np.linspace(bins[0], bins[-1], 200)
                    kde_vals = kde(x_vals) * bin_width * len(series)
                    self.plot_widget.plot(x_vals, kde_vals, pen=pg.mkPen('blue', width=2))
                except np.linalg.LinAlgError:
                    self.plot_widget.getPlotItem().setTitle(f"{name} 過程能力（KDE 略過）")


    def _get_and_plot_limits(self, name, model, series):
        LSL, USL = self.main_window.config_manager.get_limits(name, model)
        if LSL is None or USL is None:
            LSL, USL = series.min(), series.max()

        self.plot_widget.addItem(pg.InfiniteLine(pos=LSL, angle=90, pen=pg.mkPen('red', style=Qt.DashLine, width=3)))
        self.plot_widget.addItem(pg.InfiniteLine(pos=USL, angle=90, pen=pg.mkPen('green', style=Qt.DashLine, width=3)))
        return LSL, USL

    def _calculate_and_format_stats(self, series, name, LSL, USL, uph_val, util_val, downtime_val,
                                  total_time_val, machine_uph_val, current_model, rest_mmss):
        mean_val = series.mean()
        std_val = series.std(ddof=1)
        Cp = (USL - LSL) / (6 * std_val) if std_val else 0
        Cpk = min((USL - mean_val) / (3 * std_val), (mean_val - LSL) / (3 * std_val)) if std_val else 0

        over_hi = (series > USL).sum()
        under_lo = (series < LSL).sum()

        boot_m, boot_s = divmod(int(total_time_val or 0), 60)
        run_m, run_s = divmod(int((total_time_val or 0) - (downtime_val or 0) - (rest_mmss[0] * 60 + rest_mmss[1])), 60)
        down_m, down_s = divmod(int(downtime_val or 0), 60)

        main_stats = [
            ("目前機種", current_model or "—"),
            ("取樣數", f"{len(series)}"),
            ("異常(總/低/高)", f"{over_hi + under_lo} / {under_lo} / {over_hi}"),
            ("總開機時間", f"{boot_m}m {boot_s}s"),
            ("運行時間", f"{run_m}m {run_s}s"),
            ("停機時間", f"{down_m}m {down_s}s"),
            ("休息時間", f"{rest_mmss[0]}m {rest_mmss[1]}s"),
            ("稼動率", f"{util_val:.2f}%" if util_val is not None else "0.00%"),
            ("實際UPH", f"{uph_val:.0f}" if uph_val is not None else "0"),
            ("平均", f"{mean_val:.3f}"), ("std", f"{std_val:.3f}"),
            ("Cp", f"{Cp:.3f}"), ("Cpk", f"{Cpk:.3f}"),
        ]
        second_stats = [
            ("機台UPH", f"{machine_uph_val:.0f}" if machine_uph_val is not None else "0"),
        ]

        header = f'<div style="font-size:18px;font-weight:bold;margin-bottom:5px;">{name}</div>'
        return header + self._create_html_table(main_stats, second_stats)

    def _create_html_table(self, main_stats, second_stats):
        html = ['<table style="font-family:Microsoft JhengHei;font-size:16px;border-collapse:collapse;">']
        for lbl, val in main_stats:
            html.append(f'<tr><td style="padding:4px 10px;border-bottom:1px solid #ddd;">{lbl}</td>'
                        f'<td style="padding:4px 10px;border-bottom:1px solid #ddd;text-align:right;">{val}</td></tr>')
        if second_stats:
            html.append('<tr><td colspan="2" style="height:10px;"></td></tr>')
            for lbl, val in second_stats:
                html.append(f'<tr><td style="padding:4px 10px;color:red;"><b>{lbl}</b></td>'
                            f'<td style="padding:4px 10px;color:red;text-align:right;"><b>{val}</b></td></tr>')
        html.append('</table>')
        return ''.join(html)

    def _finalize_plot_appearance(self, name):
        plotItem = self.plot_widget.getPlotItem()
        for ax in ('left', 'bottom'):
            plotItem.getAxis(ax).setTextPen(pg.mkPen('black'))
        self.plot_widget.setTitle(f'<span style="font-family:Microsoft JhengHei;">{name} 過程能力</span>')
        plotItem.autoRange()