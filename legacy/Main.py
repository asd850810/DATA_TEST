__version__ = "4.8.1"
# ---------- 標準庫 ----------
import csv, os, re, sys, threading, time
from datetime import datetime, timedelta
from pathlib import Path
# ---------- 第三方 ----------
import unicodedata
import numpy as np, pandas as pd, pyqtgraph as pg
from pandas.api.types import  is_numeric_dtype, is_string_dtype  #is_categorical_dtype,
from scipy.stats import gaussian_kde              # 核密度估計
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from utils_stats import compute_uph, compute_yield, compute_machine_uph, get_basic_stats, \
    compute_util_down_rest

# ---------- PyQt5 ----------
from PyQt5.QtCore import Qt, QDate, QMimeData, QPoint, QPointF, QSettings, QRectF, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QDrag, QIcon, QPainter, QPen
from PyQt5.QtWidgets import (
    QAction, QApplication, QDateEdit, QDesktopWidget, QDialog, QFileDialog, QGridLayout, QGroupBox, QHeaderView,
    QLabel, QListWidget, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QWidget, QInputDialog, QColorDialog,
    QListWidgetItem
)
# ====================================================
# 設定顏色
# ====================================================
# ---- (最上面 COLOR_MAP 區域) ----
DEFAULT_COLOR_MAP = {
    "OK":  "green",  "NG": "red",
    "OK1": "orange", "OK2": "blue",
    "NG1": "purple", "測試1": "gray"
}
COLOR_MAP = DEFAULT_COLOR_MAP.copy()
# ----------------------------------------------------
# 代表「良品 / 不良品」的關鍵字（通通轉成大寫比對）
# ----------------------------------------------------
DEFAULT_GOOD = {"OK", "PASS", "GOOD", "O.K", "(OK)", "ＯＫ"}
DEFAULT_BAD  = {"NG", "FAIL", "BAD", "ＮＧ", "(NG)"}
# ====================================================
# TXT 檔案解析輔助函式
# 利用正規表示式解析每一行資料，找出日期與各鍵值
# ====================================================
prefix_pattern = re.compile(
    r'^(?P<datetime>\d{4}/\d{2}/\d{2},\d{2}:\d{2}:\d{2}),機種:(?P<model>\d+),\s*(?P<rest>.*)$'
)
kv_pattern = re.compile(
    r'(?P<key>[A-Za-z0-9_\u4e00-\u9fa5\s]+?)\s*[:=]\s*'   # ← 多了 \s
    r'(?P<val>[A-Za-z0-9_\u4e00-\u9fa5\.\+\-]+)'          # ← 允許文字
)
new_line_pattern = re.compile(
    r'^\d+:'                                # 忽略流水號
    r'(?P<month>\d{2})/(?P<day>\d{2})\s+'   # 03/24
    r'(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})'  # 10:19:30
)
# ====================================================
# 全域變數與檔案監控處理
# ====================================================
# 使用 threading.Event 來檢查檔案是否更新
update_event = threading.Event()
class FileChangeHandler(FileSystemEventHandler):
    """
    檔案變更處理類別：
    當指定檔案內容被修改時，更新 last_modified_time 並觸發全域事件。
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.last_modified_time = None

    def on_modified(self, event):
        # 比對事件來源是否為我們監控的檔案
        if event.src_path == self.file_path:
            current_modified_time = os.path.getmtime(self.file_path)
            if self.last_modified_time != current_modified_time:
                self.last_modified_time = current_modified_time
                update_event.set()

class LimitEditor(QDialog):
    """
    一覽並編輯所有機種 / 共用 上下限
    """
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setWindowTitle("上下限總覽與編輯")
        self.resize(480, 400)
        self.mw = main_window          # 之後要呼叫更新用
        self.settings = main_window.config_manager.settings

        self.tbl = QTableWidget(0, 4, self)
        self.tbl.setHorizontalHeaderLabels(
            ["機種 (空=共用)", "欄位", "LSL", "USL"]
        )
        header = self.tbl.horizontalHeader()

        # 第 0 列根据内容自适应
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)

        # 第 1 列根据内容自适应
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)

        # 第 2、3 列拉伸平分剩余空间
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)


        self._load_data()

        btnSave   = QPushButton("儲存並套用")
        btnDelete = QPushButton("刪除選取列")  # ← 新增
        btnCancel = QPushButton("取消")
        btnSave.clicked.connect(self._save)
        btnDelete.clicked.connect(self._delete_rows)  # ← 綁定
        btnCancel.clicked.connect(self.reject)

        layBtn = QHBoxLayout(); layBtn.addStretch()
        layBtn.addWidget(btnDelete)
        layBtn.addWidget(btnSave); layBtn.addWidget(btnCancel)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tbl); lay.addLayout(layBtn)

    # ----------  讀取 ----------
    def _load_data(self):
        for k in self.settings.allKeys():
            # 只處理 lsl 的 key
            if not (k.startswith("field_limits/") and k.endswith("/lsl")):
                continue

            # 取出 path 和 model_field
            path = k.rsplit('/', 1)[0]  # e.g. "field_limits/1234_Picth_MD"
            model_field = path.split('/', 1)[1]  # e.g. "1234_Picth_MD"

            # --- 只有「空白」或「純數字」的機種才顯示出來 ---
            if '_' in model_field:
                model, field = model_field.split('_', 1)
                # 如果 model 不是空白也不是純數字，就跳過
                if model and not model.isdigit():
                    continue
            else:
                # 沒有底線就當作共用設定，model 為空字串
                model, field = "", model_field

            # 讀出 LSL/USL 值
            lsl = float(self.settings.value(f"{path}/lsl", 0))
            usl = float(self.settings.value(f"{path}/usl", 0))

            # 新增一列並填入資料
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            for col, text in enumerate([model, field, lsl, usl]):
                item = QTableWidgetItem(str(text))
                if col >= 2:  # LSL / USL 欄靠右對齊
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl.setItem(row, col, item)

        # 最後依內容大小調整欄寬
        self.tbl.resizeColumnsToContents()

    # ----------  刪除 ----------
    def _delete_rows(self):
        # 1. 获取所有选中行（去重并从大到小排序）
        rows = sorted({idx.row() for idx in self.tbl.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "提示", "請先在表格中選取要刪除的列")
            return

        # 2. 二次确认
        if QMessageBox.question(
                self,
                "確認刪除",
                f"確定要刪除 {len(rows)} 列？（此動作無法復原）",
                QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        # 3. 移除 QSettings 中对应的 lsl/usl，并从表格删除行
        for row in rows:
            model = self.tbl.item(row, 0).text().strip()
            field = self.tbl.item(row, 1).text().strip()
            key = f"{model}_{field}" if model else field
            for suffix in ("lsl", "usl"):
                self.settings.remove(f"field_limits/{key}/{suffix}")
            self.tbl.removeRow(row)

        # 4. 立即套用到主視窗（刷新所有小圖和當前趨勢圖）
        self.mw.field_limits.clear()
        for canvas in self.mw.small_canvases.values():
            canvas.update_run(self.mw.df)
        if self.mw.current_field:
            self.mw.switch_run_chart(self.mw.current_field)

    # ----------  儲存 ----------
    def _save(self):
        # 1. 逐列检查并写回 QSettings
        for row in range(self.tbl.rowCount()):
            model = self.tbl.item(row, 0).text().strip()
            field = self.tbl.item(row, 1).text().strip()

            # —— 只接受「空白」或「纯数字」 ——
            if model and not model.isdigit():
                continue

                # 校验并转换 LSL/USL 为浮点数
            try:
                lsl = float(self.tbl.item(row, 2).text())
                usl = float(self.tbl.item(row, 3).text())
            except (ValueError, AttributeError):
                QMessageBox.warning(
                    self, "格式錯誤",
                    f"第 {row + 1} 列的 LSL/USL 應為數字，請檢查後再試"
                )
                return

            # 写入 QSettings
            key = f"{model}_{field}" if model else field
            self.settings.setValue(f"field_limits/{key}/lsl", lsl)
            self.settings.setValue(f"field_limits/{key}/usl", usl)

        # 确保所有设置都写入磁盘
        self.settings.sync()

        # 2. 刷新 MainWindow 缓存并重绘
        self.mw.field_limits.clear()
        for canvas in self.mw.small_canvases.values():
            canvas.update_run(self.mw.df)
        if self.mw.current_field:
            self.mw.switch_run_chart(self.mw.current_field)

        # 3. 提示并关闭对话框
        QMessageBox.information(self, "完成", "已儲存並套用新的上下限")
        self.accept()
# ====================================================
# 这个 FieldPicker 对话框类的作用，是让用户从现有的测量字段中勾选自己想在小图／大图里显示的项目
# ====================================================
class FieldPicker(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.setWindowTitle("選擇要顯示的量測欄位")
        self.resize(300, 400)

        # 目前量測欄位 & 先前勾選紀錄
        self.all_cols  = [c for c in self.mw.df.columns
                          if c not in ("datetime", "機種")]
        s = self.mw.settings
        all_cols = [c for c in self.mw.df.columns if c not in ("datetime", "機種")]
        previously = main_window.enabled_cols
        self.selected = previously.copy()

        # 用 QListWidget + CheckBox
        self.listw = QListWidget(self)
        for col in all_cols:
            item = QListWidgetItem(col, self.listw)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            state = Qt.Checked if (not previously or col in previously) else Qt.Unchecked
            item.setCheckState(state)


        btn_ok  = QPushButton("套用")
        btn_all = QPushButton("全選")
        btn_none= QPushButton("全不選")
        btn_ok.clicked.connect(self.apply)
        btn_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        btn_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))

        lay_btn = QHBoxLayout(); lay_btn.addStretch()
        for b in (btn_ok,btn_all, btn_none):
            lay_btn.addWidget(b)

        lay = QVBoxLayout(self)
        lay.addWidget(self.listw); lay.addLayout(lay_btn)

    def _set_all(self, state):
        for i in range(self.listw.count()):
            self.listw.item(i).setCheckState(state)

    def apply(self):
        chosen = {self.listw.item(i).text()
                  for i in range(self.listw.count())
                  if self.listw.item(i).checkState() == Qt.Checked}

        self.mw.enabled_cols = chosen
        self.mw.settings.setValue("enabled_cols", ",".join(chosen))
        self.mw.settings.sync()

        # 只把真正要顯示的欄位交回主視窗重建
        self.mw.rebuild_small_canvases(list(chosen), fresh=True)

        # 讓小圖立即更新
        if self.mw.df is not None and not self.mw.df.empty:
            for canvas in self.mw.small_canvases.values():
                canvas.update_run(self.mw.df)

        # 切回第一個勾選的欄位（如果原本的大圖已被取消勾選）
        if chosen:  # 至少勾了一個欄位
            # 仍然顯示原來的欄位；如果它沒被勾選，就顯示第一個
            target = (self.mw.current_field
                    if self.mw.current_field in chosen
                    else next(iter(chosen)))
            self.mw.switch_run_chart(target)  # **一定** 重畫
        else:  # 全部取消
            self.mw.capability_canvas.clear_panel()
            self.mw.trend_canvas.clear()
            self.mw.current_field = None

        self.accept()

def _setup_plot_looks(plotItem, *, title=""):
    plotItem.enableAutoRange(axis=pg.ViewBox.XYAxes)
    plotItem.setTitle(f"<span style='font-family:Microsoft JhengHei;color:black;'>{title}</span>")
    plotItem.showGrid(x=True, y=True, alpha=0.1)
    for ax in ('left', 'bottom'):
        plotItem.getAxis(ax).setTextPen(pg.mkPen('black'))
        plotItem.getAxis(ax).setPen(pg.mkPen('black'))

def _add_summary_label(plotItem, items, lbl_store, *,
                       cnt=None, tmin=None, tmax=None):
    if cnt is None:          # 直接給一個列表 items
        cnt  = len(items)
        xs   = [it["x"] for it in items]
        ys   = [it["y"] for it in items]
        ts   = [it["time"] for it in items]
        x0, y0 = sum(xs)/cnt, sum(ys)/cnt
        tmin, tmax = min(ts), max(ts)
    else:                     # 已算好
        x0, y0 = items[0]["x"], items[0]["y"]

    txt = f"{cnt} 異常<br>{tmin:%H:%M}–{tmax:%H:%M}"
    ti  = pg.TextItem(txt, color='red', anchor=(0.5, 1.0))
    ti.setPos(x0, y0)
    plotItem.addItem(ti); lbl_store.append(ti)

# ====================================================
# 讓使用者一直選資料夾直到裡面有檔案 (做法 A)
# ====================================================
def ask_folder_until_files(parent=None, init_path="") -> str:
    # ① 如果 init_path 已經可用，就直接用，不開對話框
    if init_path and os.path.isdir(init_path):
        has_file = any(
            f.lower().endswith((".txt", ".csv", ".log")) and
            os.path.isfile(os.path.join(init_path, f))
            for f in os.listdir(init_path)
        )
        if has_file:
            return init_path

    # ② 其餘情況才讓使用者挑，直到挑到有檔案為止
    while True:
        path = QFileDialog.getExistingDirectory(
            parent,
            "請選擇含有 TXT / CSV / LOG 檔的資料夾",
            init_path,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if not path:              # 使用者按「取消」
            return ""

        has_file = any(
            f.lower().endswith((".txt", ".csv", ".log")) and
            os.path.isfile(os.path.join(path, f))
            for f in os.listdir(path)
        )
        if has_file:
            return path

        QMessageBox.warning(
            parent, "沒有檔案",
            "這個資料夾沒有 TXT / CSV / LOG 檔，請重新選擇。"
        )
        init_path = path          # 下次對話框就從剛剛的目錄開啟
# ====================================================
# 自訂日期時間解析函式
# 用來處理類似 "2025-02-14_11-31-27-9071" 格式的日期時間字串
# ====================================================
def parse_custom_datetime(s: str) -> datetime:
    # 將日期與時間部分切割，例如 "2025-02-14" 與 "11-31-27-9071"
    date_part, time_part = s.split('_')
    # 將日期部分轉換為 date 物件
    date_obj = datetime.strptime(date_part, "%Y-%m-%d").date()
    # 將時間部分拆解：小時、分鐘、秒、毫秒(?)部分
    hour_str, minute_str, second_str, frac_str = time_part.split('-')
    hour = int(hour_str)
    minute = int(minute_str)
    # 將秒與小數部分結合，例如秒數 + "0.9071"
    second_float = float(second_str) + float("0." + frac_str)
    # 建立 datetime 物件（初始秒設為 0，再加上真正的秒數）
    dt = datetime(date_obj.year, date_obj.month, date_obj.day,
                  hour=hour, minute=minute, second=0)
    dt += timedelta(seconds=second_float)
    return dt

# 從 QSettings 讀取良品與不良品標籤
def load_tags():
    st = QSettings("MyCompany", "MyApp")

    good = set(st.value("yield_tags/good", ",".join(DEFAULT_GOOD)).split(','))
    bad  = set(st.value("yield_tags/bad",  ",".join(DEFAULT_BAD)).split(','))

    # 避免空字串
    return {w.strip().upper() for w in good if w.strip()}, \
           {w.strip().upper() for w in bad  if w.strip()}

# 將良品與不良品標籤存入 QSettings
def save_tags(good_set, bad_set):
    st = QSettings("MyCompany", "MyApp")
    st.setValue("yield_tags/good", ",".join(sorted(good_set)))
    st.setValue("yield_tags/bad",  ",".join(sorted(bad_set)))
    st.sync()
GOOD_TAGS, BAD_TAGS = load_tags()

# 取得標籤的母類別（如 OK1→OK、NG2→NG）
def _parent_key(cat: str) -> str:
    """OK1 → OK , NG2 → NG , 其他回自己"""
    up = cat.upper()
    if up.startswith("OK"): return "OK"
    if up.startswith("NG"): return "NG"
    return cat

# 為分類產生對應顏色的 brush 列表
def make_brushes(cats):
    """依 cats 產生顏色 brush；先找精確 → 再找母類別 → 灰"""
    return [pg.mkBrush(
                COLOR_MAP.get(c) or               # 精確
                COLOR_MAP.get(_parent_key(c)) or  # 母類別
                "gray")                           # fallback
            for c in cats]

# 判斷是否為文字欄位（排除數值型別）
def is_text_column(series: pd.Series) -> bool:
    # 先排除所有真正的数值欄位
    if is_numeric_dtype(series):
        return False
    # 只有不是数值，且确实是字串或 object 才算文字欄位
    return is_string_dtype(series) or series.dtype == object

# 測試結果顏色設定的對話框
class ColorEditor(QDialog):
    def __init__(self, color_map: dict, ordered_cats, parent=None):
        super().__init__(parent)
        self.setWindowTitle("測試結果顏色設定")
        self.resize(260, 200)
        self.settings = QSettings("MyCompany", "MyApp")

        self.color_map = color_map           # 參考用
        self.labels = {}                     # 保存 label 以便更新顏色

        lay = QVBoxLayout(self)
        for cat in ordered_cats:
            h = QHBoxLayout()
            lab = QLabel(cat)
            lab.setFixedWidth(60)
            btn = QPushButton()
            btn.setFixedSize(40, 20)
            btn.setStyleSheet(f"background:{color_map[cat]}")
            btn.clicked.connect(lambda _, c=cat: self.pick_color(c))
            h.addWidget(lab); h.addWidget(btn); h.addStretch()
            lay.addLayout(h)
            self.labels[cat] = btn

        btn_ok = QPushButton("關閉")
        btn_ok.clicked.connect(self.accept)
        lay.addWidget(btn_ok, alignment=Qt.AlignRight)

    def pick_color(self, cat):
        cur = QColor(self.color_map[cat])
        new = QColorDialog.getColor(cur, self, f"{cat} 顏色")
        if new.isValid():
            css = f"background:{new.name()}"
            self.labels[cat].setStyleSheet(css)
            self.color_map[cat] = new.name()
            # 寫進 QSettings
            self.settings.setValue(f"result_colors/{cat}", new.name())
            self.settings.sync()

# 良品與不良品關鍵字編輯器對話框
class YieldTagEditor(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.good = set(GOOD_TAGS)
        self.bad  = set(BAD_TAGS)

        self.setWindowTitle("良 / 不良 關鍵字設定")
        self.resize(400, 300)

        self.lst_good = QListWidget();  self.lst_good.addItems(sorted(self.good))
        self.lst_bad  = QListWidget();  self.lst_bad.addItems(sorted(self.bad))

        # --- 按鈕 ---
        btn_add_good   = QPushButton("新增OK")
        btn_add_bad    = QPushButton("新增NG")
        btn_del_good   = QPushButton("刪除 OK")
        btn_del_bad    = QPushButton("刪除 NG")
        btn_flip       = QPushButton("OK ↔ NG")
        btn_ok         = QPushButton("儲存並關閉")

        btn_add_good.clicked.connect(lambda: self.add_tag(self.lst_good, self.good))
        btn_add_bad .clicked.connect(lambda: self.add_tag(self.lst_bad,  self.bad))
        btn_del_good.clicked.connect(lambda: self.del_tag(self.lst_good, self.good))
        btn_del_bad .clicked.connect(lambda: self.del_tag(self.lst_bad,  self.bad))
        btn_flip.clicked.connect(self.flip_tag)
        btn_ok.clicked.connect(self.apply_and_close)

        # --- 版面 ---
        hn = QHBoxLayout()
        vl = QVBoxLayout(); vl.addWidget(QLabel("GOOD (良品)")); vl.addWidget(self.lst_good); hn.addLayout(vl)
        vr = QVBoxLayout(); vr.addWidget(QLabel("BAD (不良)"));  vr.addWidget(self.lst_bad);  hn.addLayout(vr)

        vb_btn = QVBoxLayout()
        for w in (btn_add_good, btn_add_bad, btn_del_good, btn_del_bad, btn_flip, btn_ok):
            vb_btn.addWidget(w)
        hn.addLayout(vb_btn)

        self.setLayout(hn)

    # --------- 輔助 ---------
    def add_tag(self, lst, s):
        txt, ok = QInputDialog.getText(self, "新增標籤", "輸入關鍵字：")
        if ok and txt.strip():
            tag = txt.strip().upper()
            if tag in s:
                return
            s.add(tag); lst.addItem(tag)

    def del_tag(self, lst, s):
        for it in lst.selectedItems():
            s.discard(it.text()); lst.takeItem(lst.row(it))

    def flip_tag(self):
        # OK ↔ NG 集合互換
        sel_ok = [it.text() for it in self.lst_good.selectedItems()]
        sel_ng = [it.text() for it in self.lst_bad.selectedItems()]
        for t in sel_ok: self.good.discard(t); self.bad.add(t)
        for t in sel_ng: self.bad.discard(t); self.good.add(t)
        self.lst_good.clear(); self.lst_good.addItems(sorted(self.good))
        self.lst_bad .clear(); self.lst_bad .addItems(sorted(self.bad))

    def apply_and_close(self):
        save_tags(self.good, self.bad)
        # 把全域變數也更新（讓程式即時生效）
        GOOD_TAGS.clear(); GOOD_TAGS.update(self.good)
        BAD_TAGS.clear();  BAD_TAGS.update(self.bad)
        self.accept()

# ====================================================
# 配置管理類別 (ConfigManager)
# 用於讀取與寫入應用程式相關設定
# ====================================================
class ConfigManager:
    def __init__(self):
        self.settings = QSettings("MyCompany", "MyApp")

    def get_limits(self, field, model=None):
        key_prefix = f"{model}_{field}" if model else field
        lsl = self.settings.value(f"field_limits/{key_prefix}/lsl", 0.0, type=float)
        usl = self.settings.value(f"field_limits/{key_prefix}/usl", 10.0, type=float)
        return (lsl, usl)

    def set_limits(self, field, lsl, usl, model=None):
        key_prefix = f"{model}_{field}" if model else field
        self.settings.setValue(f"field_limits/{key_prefix}/lsl", lsl)
        self.settings.setValue(f"field_limits/{key_prefix}/usl", usl)

# ====================================================
# 資料管理類別 (DataManager)
# 負責根據檔案類型讀取並解析資料
# ====================================================
class DataManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.df = None  # 儲存讀取後的 DataFrame
        self.product_category = None  # 初始化屬性

    def load_data(self):
        if not os.path.isfile(self.file_path):
            print("指定的檔案不存在:", self.file_path)
            return None

        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".csv":
            return self.load_csv_data(self.file_path)
        elif ext in (".txt", ".log"):
            return self.load_txt_data(self.file_path)
        else:
            print(f"不支援的檔案格式: {ext}")
            return None

    def load_txt_data(self, file_path):
        # 嘗試以 big5 編碼讀取，若失敗則用 utf-8
        try:
            with open(file_path, "r", encoding="big5") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            print("以 big5 讀取失敗，改用 utf-8 嘗試。")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                print("使用 utf-8 讀取時也發生錯誤:", e)
                return None
        except Exception as e:
            print("读取 TXT 文件错误:", e)
            return None

        # 利用 parse_line 函式解析每一行資料，過濾掉空行
        data_rows = [row for row in (parse_line(line) for line in lines) if row]
        if not data_rows:
            return None

        df = pd.DataFrame(data_rows)
        # 將 datetime 欄位字串轉成 datetime 物件
        df["datetime"] = pd.to_datetime(df["datetime"], format="%Y/%m/%d,%H:%M:%S", errors='coerce')
        # 刪除轉換失敗的資料列
        df.dropna(subset=["datetime"], inplace=True)
        # 依照時間排序，並重設索引
        df.sort_values(by="datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)

        self.df = df
        return df

    def load_csv_data(self, file_path):
        """
        支援三種 CSV 格式：
        ① 舊版：直接有 datetime 欄
        ② 新版：分成 Date + Time 欄
        ③ 夾雜前置中文/英文標題的混合格式（Header 不一定在第 0 行）
        """
        import pandas as pd
        import os

        # ===== ❶ 確認檔案存在 =====
        if not os.path.isfile(file_path):
            print("指定的檔案不存在:", file_path)
            return None

        # ===== ❷ 先讀前幾行，找 header 在哪一行 =====
        first_lines = []
        with open(file_path, "rb") as f:
            for _ in range(5):  # 最多讀 5 行
                line = f.readline()
                if not line:
                    break
                first_lines.append(line)

        # 判斷某一行是否可能是 header
        def looks_like_header(cols):
            cols = [c.strip().lower().lstrip('\ufeff') for c in cols]
            # 舊版：有 datetime 欄
            if "datetime" in cols:
                return True
            # 新版：有 Date + Time 欄
            if {"date", "time"}.issubset(cols):
                return True
            # 你的新檔案：有 "no." 或 "test result"
            if "no." in cols or "test result" in cols:
                return True
            return False
        # 預設 header 在第 0 行
        header_row = 0
        for idx, raw in enumerate(first_lines):
            cols = raw.decode("latin-1", errors="ignore").split(',')
            if looks_like_header(cols):
                header_row = idx  # 找到 header 的行號
                break

        with open(file_path, "r", encoding="big5") as f:
            first_line = f.readline().strip()
            parts = first_line.split(',')
            # 假設「產品類別」在第八個位置，值在第九個位置
            # 根據你提供的檔案，這兩個值的索引分別是 6 和 7
            if len(parts) > 7 and parts[6] == "產品類別":
                self.product_category = parts[7]
                print(self.product_category)
            else:
                self.product_category = "未知"

        # ===== ❸ 嘗試用多種編碼讀取檔案 =====
        for enc in ("utf-8-sig", "utf-8", "big5", "cp950", "latin-1"):
            try:
                df = pd.read_csv(
                    file_path,
                    skiprows=header_row,  # 跳過 header_row 之前的行
                    encoding=enc,
                    engine="python",
                    header=0  # 告訴 pandas：現在這一行才是欄名
                )
                print(f"✅ 以 {enc} 讀取成功")
                break
            except UnicodeDecodeError:
                continue
        else:
            # 如果所有編碼都失敗
            print("❌ 無法解碼此 CSV")
            return None

        # ===== ❹ 清理欄位名稱（去掉 BOM 與空白） =====
        df.rename(columns=lambda c: str(c).strip().lstrip('\ufeff'), inplace=True)

        # ===== ❺ 如果有 Date + Time 欄，先合併成 datetime =====
        if {"Date", "Time"}.issubset(df.columns):
            df["datetime"] = (
                    df["Date"].astype(str).str.strip()
                    + " " +
                    df["Time"].astype(str).str.strip().str.rstrip(':')  # 把多餘的冒號去掉
            )
            df.drop(columns=["Date", "Time"], inplace=True)

            # 嘗試轉成 pandas 的 datetime 型別
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

        # ===== ❻ 如果直接有 datetime 欄 =====
        elif "datetime" in df.columns:
            s = df["datetime"].astype(str).str.strip()
            if s.str.contains("_").any():  # 舊格式：2025-02-14_11-23-18-0800
                dt_tmp = s.apply(parse_custom_datetime)
            else:  # 新格式：2025/05/06 09:23:59
                dt_tmp = pd.to_datetime(
                    s,
                    format="%Y/%m/%d %H:%M:%S",
                    errors="coerce"
                )
            df["datetime"] = dt_tmp

        else:
            # 如果找不到任何 datetime 欄位，就直接放棄
            print("❌ 仍找不到 datetime 欄，檔案格式可能異常")
            return None

        # ===== ❼ 其他欄位名稱修正 =====
        df.rename(columns={"Operaor": "Operator",  # 拼字錯誤修正
                           "Test Result": "測試結果"},
                  inplace=True)
        # 把不需要的欄位移除
        df.drop(columns=[c for c in ("Number", "UID Code") if c in df.columns],
                inplace=True, errors="ignore")

        # ===== ❽ 整理資料 =====
        df.dropna(subset=["datetime"], inplace=True)  # 移除沒有時間的列
        df.sort_values("datetime", inplace=True)  # 依時間排序
        df.reset_index(drop=True, inplace=True)  # 重建索引（0,1,2,...）
        # ===== ❿ 特殊欄位處理 =====
        if "厚度計(A)檢測值" in df.columns:
            df["厚度計(A)檢測值"] = (
                df["厚度計(A)檢測值"].astype(str).str.extract(r"([\d.]+)").astype(float)
            )
        # ===== ❾ 最後檢查是否有資料 =====
        if df.empty:
            print("❌ 讀到的 DataFrame 為空")
            return None

        # 把 DataFrame 存進物件
        self.df = df
        return df

    # －－－ 如果第一次判斷 header 失敗，呼叫這隻重試 －－－
    def load_csv_data_inner_retry(self, file_path, alt_skip):
        try:
            df = pd.read_csv(file_path, skiprows=alt_skip, encoding="latin-1", engine="python")
            df.rename(columns=lambda c: str(c).strip(), inplace=True)
            # 下面流程同上，為了節省篇幅可直接調用主函式邏輯
            self.file_path = file_path  # 防 recursion loop
            self.df = None  # 讓主流程重新處理
            return self.load_csv_data(file_path)
        except Exception as e:
            print("重試讀 CSV 失敗：", e)
            return None

# ====================================================
# 後台資料載入類別 (DataLoader)
# 採用 QThread 實現非同步讀取檔案，以免阻塞主執行緒
# ====================================================
class DataLoader(QThread):
    data_loaded = pyqtSignal(object)

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.stop_requested = False
    def run(self):
        if self.stop_requested:               # ← 早退放這裡
            return
        try:
            ext = os.path.splitext(self.file_path)[1].lower()
            dm = DataManager(self.file_path)
            if ext == ".csv":
                df = dm.load_csv_data(self.file_path)
            else:
                df = dm.load_txt_data(self.file_path)
            self.data_loaded.emit(df)
        except Exception as e:
            print("数据加载失败:", e)
            self.data_loaded.emit(None)

# ====================================================
# 小工具函式 (utilities)
# ====================================================
def _clean_int_str(s: pd.Series, width: int):
    """
    把 '2025.0'、' 2 '、'\ufeff03' → '2025'、'02'、'03'
    若整列空/抓不到數字就回傳空字串，最後 to_datetime 會變 NaT。
    """
    return (
        s.astype(str)                 # 確定是字串
         .str.extract(r"(\d+)", expand=False)  # 抓出第一串數字
         .fillna("")                  # Na → ''
         .str.zfill(width)            # 補零對齊
    )

# ---------------------------------------------
# 文字欄位標準化：去隱形字元、半形化、去頭尾空白
# ---------------------------------------------
def normalize_str_col(s: pd.Series) -> pd.Series:
    """
    1. 去頭尾空白（含全形空白 \u3000）
    2. 去掉 BOM (\ufeff) 等看不見的字
    3. 全形括號 → 半形
    4. NFKC 正規化，把全形 OＫ… 轉半形
    """
    return (
        s.astype(str)
         .str.strip()
         .str.replace('\u3000', '', regex=False)
         .str.replace('\ufeff', '', regex=False)
         .str.replace('（', '(',  regex=False)
         .str.replace('）', ')',  regex=False)
         # 注意：第一個參數必須是 'NFKC'
         .apply(lambda x: unicodedata.normalize('NFKC', x))
    )


# ====================================================
# 行解析輔助函式 parse_line
# 根據「舊版」與「新版」兩種格式解析單行文本
# 舊版格式範例：
#   2025/03/19,09:43:38,機種:2, Key1:123 Key2=45.6 …
# 新版格式範例：
#   123:03/19 09:43:38 Key1:123 Key2=45.6 …
# 返回字典：
#   {
#     "datetime": 字串或 datetime 物件,
#     "機種": 整數或字串（僅舊版有）,
#     key1: float 或 None,
#     ...
#   }
# 解析失敗或空行則回傳空字典 {}
# ====================================================
def parse_line(line: str):
    line = line.strip()
    if not line:
        return {}

    m_old = prefix_pattern.match(line)
    if m_old:
        datetime_str = m_old.group("datetime")
        model_str = m_old.group("model")
        rest = m_old.group("rest").replace("CCD4量測", "")

        # ★ 抓取測試結果 ★
        m_result = re.search(r"測試結果\s*[:=]\s*([A-Za-z0-9\u4e00-\u9fff]+)",  # 加入中文範圍
                             rest, re.I)
        test_result = None
        if m_result:
            test_result = m_result.group(1).upper()
            rest = rest.replace(m_result.group(0), "")

        found = kv_pattern.findall(rest)
        row = {
            "datetime": datetime_str,
            "機種": int(model_str) if model_str.isdigit() else model_str
        }
        if test_result:
            row["測試結果"] = test_result
        for key, val_str in found:
            key = key.strip()  # 去掉全形或混雜空白
            val_str = val_str.strip()
            try:
                row[key] = float(val_str)
            except ValueError:
                row[key] = val_str  # 直接留下 "OK"、"NG"…
        return row

    m = new_line_pattern.match(line)
    if m:
        now = datetime.now()
        dt = datetime(
            year=now.year,
            month=int(m.group("month")),
            day=int(m.group("day")),
            hour=int(m.group("hour")),
            minute=int(m.group("minute")),
            second=int(m.group("second"))
        )
        rest = line[m.end():]

        # ★ 抓取測試結果（新格式） ★
        m_result = re.search(r"測試結果\s*[:=]\s*(OK|NG)", rest, re.I)
        test_result = None
        if m_result:
            test_result = m_result.group(1).upper()
            rest = rest.replace(m_result.group(0), "")

        found = kv_pattern.findall(rest)
        row = {"datetime": dt}
        if test_result:
            row["測試結果"] = test_result
        for key, val_str in found:
            try:
                row[key] = float(val_str)
            except ValueError:
                row[key] = None
        return row

    return {}

# ====================================================
# 自訂拖放容器：CanvasContainer
# 用於放置顯示小運行圖的 Widget，並支援拖放調整順序
# ====================================================
class CanvasContainer(QWidget):
    """
    CanvasContainer 是一個可拖放重排列的小圖容器
    讓使用者可以透過拖放，調整小運行圖的顯示順序，
    並將新的排序儲存到主視窗設定中。
    """
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        # 儲存對主視窗的引用，用於更新排序設定
        self.main_window = main_window

        # 使用垂直佈局管理子 widget 的排列
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(5)       # 控制子 widget 之間的間距
        self.setLayout(self.layout)

        # 允許接受拖放事件
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        # 當拖入的內容包含文字（widget 的 name）時接受拖入，否則忽略
        if event.mimeData().hasText():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        # 在拖放過程中持續接受事件，確保能觸發 dropEvent
        event.accept()

    def dropEvent(self, event):
        """
        處理拖放放下時的行為：
        1. 從 mimeData 取得被拖動 widget 的 name
        2. 在佈局中找到對應的 widget
        3. 根據放置位置計算新的插入索引，並重新排列
        4. 更新主視窗的 ordered_cols，並儲存到 QSettings
        """
        # 1. 取得拖入來源 widget 的名稱
        widget_name = event.mimeData().text()
        dragged_widget = None

        # 2. 在目前佈局中尋找匹配 name 的 widget
        for i in range(self.layout.count()):
            w = self.layout.itemAt(i).widget()
            if w and hasattr(w, "name") and w.name == widget_name:
                dragged_widget = w
                break

        if dragged_widget:
            # 3a. 先移除舊位置
            self.layout.removeWidget(dragged_widget)
            drop_pos = event.pos()
            insert_at = 0

            # 3b. 根據 y 座標比較各 widget 中心，決定插入索引
            for i in range(self.layout.count()):
                w = self.layout.itemAt(i).widget()
                if w:
                    widget_center = w.pos().y() + w.height() / 2
                    if drop_pos.y() < widget_center:
                        insert_at = i
                        break
                    else:
                        insert_at = i + 1

            # 3c. 插入到新位置
            self.layout.insertWidget(insert_at, dragged_widget)

        # 接受 drop 事件
        event.accept()

        # 4. 更新主視窗的小圖順序並儲存設定
        if self.main_window:
            new_order = []
            for i in range(self.layout.count()):
                w = self.layout.itemAt(i).widget()
                if w and hasattr(w, "name"):
                    new_order.append(w.name)
            # 更新主視窗屬性並寫入 QSettings
            self.main_window.ordered_cols = new_order
            self.main_window.settings.setValue(
                "ordered_cols", ",".join(new_order)
            )

# ====================================================
# 自訂 Spinner Widget (啟動畫面上的等待動畫)
# ====================================================
class SpinnerWidget(QWidget):
    def __init__(self, parent=None, arc_angle=90, speed=10, line_width=4, color=QColor("blue")):
        super().__init__(parent)
        self.angle = 0
        self.arc_angle = arc_angle
        self.line_width = line_width
        self.color = color
        # 利用 QTimer 控制動畫更新速度
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateAngle)
        self.timer.start(speed)
        self.setMinimumSize(50, 50)

    def updateAngle(self):
        # 每次更新角度，達到旋轉效果
        self.angle = (self.angle + 5) % 360
        self.update()

    def paintEvent(self, event):
        # 使用 QPainter 畫出旋轉中的弧線
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 將繪圖中心移至 widget 中心
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)
        pen = QPen(self.color, self.line_width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        radius = min(self.width(), self.height()) / 2 - self.line_width
        draw_rect = QRectF(-radius, -radius, radius * 2, radius * 2)
        painter.drawArc(draw_rect, 0, self.arc_angle * 16)

# ====================================================
# 啟動畫面 (SplashScreen)
# ====================================================
class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        # 設定無框、置頂的視窗屬性
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(300, 200)
        layout = QVBoxLayout()
        self.label = QLabel("正在啟動中...", self)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self.spinner = SpinnerWidget(arc_angle=90, speed=10, line_width=4, color=QColor("blue"))
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)
        self.setLayout(layout)

# ====================================================
# 能力圖顯示面板 (CapabilityPanel)
# 使用 pyqtgraph 繪製直方圖與統計數據
# ====================================================
class CapabilityPanel(QWidget):
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.main_window = main_window

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # 建立 plot_widget 來繪製直方圖與核密度估計
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.getPlotItem().showGrid(x=True, y=True, alpha=0.1)
        # 禁止滑鼠拖動 ViewBox，避免誤操作
        self.plot_widget.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)

        # info_label 用來顯示統計資訊（HTML 格式）
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.info_label.setStyleSheet("""
            QLabel {
                background-color: rgba(255,255,255,180);
                border: 1px solid gray;
                padding: 5px;
            }
        """)
        # ---------- 這兩行就是「方案 B」 ----------
        self.info_label.setMinimumHeight(550)             # <-- 高度自行調整
        self.info_label.setSizePolicy(QSizePolicy.Fixed,   # 水平固定
                                      QSizePolicy.Preferred)  # 垂直可撐開
        # -----------------------------------------
        self.info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        layout.addWidget(self.plot_widget, 1)
        layout.addWidget(self.info_label)

    def clear_panel(self):
        # 清除圖表與統計資訊
        self.plot_widget.clear()
        self.info_label.clear()
    def show_info(self, header: str, main_stats: list, second_stats: list):
        """
        只顯示表格資訊，用在『測試結果』欄位。
        header            : HTML 字串，例：'<div style="font-size:18px;font-weight:bold;">測試結果</div>'
        main_stats        : [(標籤, 值), ...]   黑色字
        second_stats      : [(標籤, 值), ...]   紅色字
        """
        # 清掉舊圖
        self.plot_widget.clear()

        def stats_to_html_table(a, b):
            html = ['<table style="font-family:Microsoft JhengHei;font-size:16px;border-collapse:collapse;">']
            for lbl, val in a:
                html.append(
                    f'<tr><td style="padding:4px 10px;border-bottom:1px solid #ddd;">{lbl}</td>'
                    f'<td style="padding:4px 10px;border-bottom:1px solid #ddd;text-align:right;">{val}</td></tr>'
                )
            html.append('<tr><td colspan="2" style="height:10px;"></td></tr>')
            for lbl, val in b:
                html.append(
                    f'<tr><td style="padding:4px 10px;color:red;"><b>{lbl}</b></td>'
                    f'<td style="padding:4px 10px;color:red;text-align:right;"><b>{val}</b></td></tr>'
                )
            html.append('</table>')
            return "".join(html)

        # 把組好的 HTML 塞進 info_label
        self.info_label.setText(header + stats_to_html_table(main_stats, second_stats))

    def plot_capability(self, data_series: pd.Series, name="Unknown",
                        uph_val=None, sub_df=None, util_val=None,
                        downtime_val=None, total_time_val=None,
                        machine_uph_val=None, current_model=None,
                        rest_mmss=(0, 0)):
        # 如果原始 series 為空，直接顯示「無資料」
        if data_series is None or data_series.empty:
            self.clear_panel()
            self.plot_widget.getPlotItem().setTitle(f"{name} - 過程能力報告 (無資料)")
            self.info_label.clear()
            return

        # 清除舊圖
        self.clear_panel()

        # 1. 先過濾掉所有 NaN/Inf
        clean_series = data_series.dropna()
        clean_vals = clean_series.values
        if len(clean_vals) == 0:
            self.clear_panel()
            self.plot_widget.getPlotItem().setTitle(f"{name} - 過程能力報告 (無資料)")
            self.info_label.clear()
            return

        # 2. 繪製直方圖與核密度估計 (KDE)
        bin_num = getattr(self.main_window, 'default_bin_num', 30)
        # 用 clean_vals 而非原 data_series
        counts, bins = np.histogram(clean_vals, bins=bin_num)
        bin_width = bins[1] - bins[0]
        x_bar = bins[:-1] + bin_width * 0.5

        # 繪製直方圖
        bg = pg.BarGraphItem(
            x=x_bar, height=counts, width=bin_width * 0.9,
            brush='skyblue', pen=pg.mkPen('black')
        )
        self.plot_widget.addItem(bg)

        # 2. 繪製核密度估計線 ── 若失敗就自動加 jitter 再重試
        kde_drawn = False
        if len(clean_vals) >= 3:  # 至少 3 點才嘗試 KDE
            try:
                # 第一次嘗試（不加抖動）
                kde = gaussian_kde(clean_vals)
                kde_drawn = True
            except np.linalg.LinAlgError:
                # 加入極小隨機抖動後再試一次
                std = np.std(clean_vals)
                jitter = max(std * 0.01, 1e-6)  # 抖動幅度：1% σ 或 1e-6
                vals_jitter = clean_vals + np.random.normal(0, jitter, len(clean_vals))
                try:
                    kde = gaussian_kde(vals_jitter)
                    kde_drawn = True
                except np.linalg.LinAlgError:
                    pass  # 仍失敗就放棄 KDE

        if kde_drawn:
            x_vals = np.linspace(bins[0], bins[-1], 200)
            kde_vals = kde(x_vals) * bin_width * len(clean_vals)
            self.plot_widget.plot(x_vals, kde_vals, pen=pg.mkPen('blue', width=2))
        else:
            # 你想要也可以在標題上註記：無 KDE
            self.plot_widget.getPlotItem().setTitle(
                f"{name} 過程能力（KDE 略過）",
                **{'size': '14pt'}
            )

        # 3. 取得上下限設定
        default_lower = clean_series.min()
        default_upper = clean_series.max()
        raw_LSL, raw_USL = self.main_window.config_manager.get_limits(
            name, current_model
        )
        if raw_LSL is None or raw_USL is None:
            raw_LSL, raw_USL = default_lower, default_upper
        LSL, USL = sorted([raw_LSL, raw_USL])

        # 畫上下限線
        self.plot_widget.addItem(pg.InfiniteLine(
            pos=LSL, angle=90,
            pen=pg.mkPen('red', style=Qt.DashLine, width=3)
        ))
        self.plot_widget.addItem(pg.InfiniteLine(
            pos=USL, angle=90,
            pen=pg.mkPen('green', style=Qt.DashLine, width=3)
        ))

        # 4. 計算統計數據：平均、標準差、Cp、Cpk
        mean_val = clean_series.mean()
        std_val = clean_series.std(ddof=1)
        Cp = (USL - LSL) / (6 * std_val) if std_val else 0
        Cpk = min((USL - mean_val) / (3 * std_val),
                  (mean_val - LSL) / (3 * std_val)) if std_val else 0

        # === ★ 新增：計數超上下限 ★ ===
        over_hi = (clean_series > USL).sum()  # 高於 USL
        under_lo = (clean_series < LSL).sum()  # 低於 LSL
        over_total = over_hi + under_lo  # 總異常筆數
        # =================================

        # 5. 計算其他資訊（剃補次數差、停機、UPH 等）
        change_count = None
        if sub_df is not None and "剃補次數" in sub_df.columns and not sub_df.empty:
            change_count = sub_df["剃補次數"].max() - sub_df["剃補次數"].min()
        elif hasattr(self.main_window, "global_change_count"):
            change_count = self.main_window.global_change_count

        if total_time_val is not None and downtime_val is not None:
            boot_m, boot_s = divmod(int(total_time_val), 60)
            resttime_val = rest_mmss[0] * 60 + rest_mmss[1]
            run_time = total_time_val - downtime_val - resttime_val
            run_m, run_s = divmod(int(run_time), 60)
            down_m, down_s = divmod(int(downtime_val), 60)
        else:
            boot_m = boot_s = run_m = run_s = down_m = down_s = 0

        change_rate = (
            change_count / len(clean_series) * 100
            if change_count is not None and len(clean_series) > 0 else 0.0
        )

        # 6. 組 HTML 表格顯示資訊
        main_stats = [
            ("目前機種", current_model or "—"),
            ("取樣數", f"{len(clean_series)}"),
            ("剃補次數(全域)", f"{int(change_count) if change_count is not None else 0}"),
            ("異常(總/低/高)", f"{over_total} / {under_lo} / {over_hi}"),
            ("總開機時間", f"{boot_m}m {boot_s}s"),
            ("運行時間", f"{run_m}m {run_s}s"),
            ("停機時間", f"{down_m}m {down_s}s"),
            ("休息時間", f"{rest_mmss[0]}m {rest_mmss[1]}s"),
            ("稼動率", f"{util_val:.2f}%") if util_val is not None else ("稼動率", "0.00%"),
            ("實際UPH", f"{uph_val:.0f}") if uph_val is not None else ("UPH", "0"),
            ("平均", f"{mean_val:.3f}"),
            ("std", f"{std_val:.3f}"),
            ("Cp", f"{Cp:.3f}"),
            ("Cpk", f"{Cpk:.3f}"),
        ]
        second_stats = [
            ("剃補率", f"{change_rate:.2f}%"),
            ("機台UPH", f"{machine_uph_val:.0f}") if machine_uph_val is not None else ("機台UPH", "0"),
        ]

        def stats_to_html_table(a, b):
            html = ['<table style="font-family:Microsoft JhengHei;font-size:16px;border-collapse:collapse;">']
            for lbl, val in a:
                html.append(f'<tr><td style="padding:4px 10px;border-bottom:1px solid #ddd;">{lbl}</td>'
                            f'<td style="padding:4px 10px;border-bottom:1px solid #ddd;text-align:right;">{val}</td></tr>')
            html.append('<tr><td colspan="2" style="height:10px;"></td></tr>')
            for lbl, val in b:
                html.append(f'<tr><td style="padding:4px 10px;color:red;"><b>{lbl}</b></td>'
                            f'<td style="padding:4px 10px;color:red;text-align:right;"><b>{val}</b></td></tr>')
            html.append('</table>')
            return ''.join(html)

        header = f'<div style="font-size:18px;font-weight:bold;margin-bottom:5px;">{name}</div>'
        self.info_label.setText(header + stats_to_html_table(main_stats, second_stats))

        # 7. 最後調整軸與自動縮放
        plotItem = self.plot_widget.getPlotItem()
        for ax in ('left', 'bottom'):
            plotItem.getAxis(ax).setTextPen(pg.mkPen('black'))
            plotItem.getAxis(ax).setPen(pg.mkPen('black'))
        self.plot_widget.setTitle(f'<span style="font-family:Microsoft JhengHei;">{name} 過程能力</span>')
        plotItem.autoRange()

# ====================================================
# 小運行圖 (SmallRunPlotWidget)
# 使用 pyqtgraph 繪製簡單趨勢圖，同時支援拖放與點擊切換功能
# ====================================================
class SmallRunPlotWidget(pg.PlotWidget):
    def __init__(self, parent=None, name="SmallRun", main_window=None):
        super().__init__(parent)
        self.name = name
        self.main_window = main_window
        self.setFixedHeight(180)
        self.getPlotItem().showGrid(x=True, y=True, alpha=0.1)
        self.setBackground('w')
        # 禁止使用者在 ViewBox 中進行拖曳或縮放
        self.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)
        self.drag_start_position = None
        self.is_dragging = False

    def dragEnterEvent(self, event):
        event.ignore()

    def dragMoveEvent(self, event):
        event.ignore()

    def mousePressEvent(self, event):
        # 沒資料就保持 Qt 原行為
        if self.main_window.df is None or self.main_window.current_field is None:
            super().mousePressEvent(event)
            return

        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
            self.is_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.main_window.df is None or self.main_window.current_field is None:
            super().mouseMoveEvent(event)
            return
        if event.buttons() & Qt.LeftButton:
            distance = (event.pos() - self.drag_start_position).manhattanLength()
            # 判斷是否超過拖曳起始距離，進而觸發拖曳操作
            if distance >= QApplication.startDragDistance():
                self.is_dragging = True
                drag = QDrag(self)
                mime_data = QMimeData()
                mime_data.setText(self.name)
                drag.setMimeData(mime_data)
                # 將當前 widget 畫面作為拖曳顯示圖示
                pixmap = self.grab()
                drag.setPixmap(pixmap)
                center_point = pixmap.rect().center()
                drag.setHotSpot(center_point)
                drag.exec_(Qt.MoveAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.main_window.df is None or self.main_window.current_field is None:
            super().mouseReleaseEvent(event)  # 換成 mouseMove / mouseRelease 就寫對應的
            return

        # 若未拖曳則觸發點擊事件，進而切換大圖顯示欄位
        if event.button() == Qt.LeftButton and not self.is_dragging:
            if self.main_window:
                self.main_window.switch_run_chart(self.name)
        super().mouseReleaseEvent(event)

    def update_run(self, df: pd.DataFrame):
        if df.empty or (self.name not in df.columns):
            return
            # ★ 若是「測試結果」→ 畫長方圖 ★
        # ★ 若是「測試結果」→ 畫長方圖 ★
        if is_text_column(df[self.name]):
            max_points = 100
            total = len(df)
            step = total // max_points if total > max_points else 1
            # 先清洗再轉成字串
            vals = normalize_str_col(df[self.name]).iloc[::step].values

            # 支援中英文／任何代碼
            cats, counts = np.unique(vals, return_counts=True)
            order = np.argsort(counts)[::-1]
            cats, counts = cats[order], counts[order]
            x = np.arange(len(cats))

            # 自動柱寬：分類越多柱越窄（最小 0.2）
            width = max(0.2, 0.8 * (6 / len(cats)) if len(cats) > 6 else 0.8)

            brushes = make_brushes(cats)  # ← 用共用函式


            self.clear()
            bar = pg.BarGraphItem(
                x=x,
                height=counts,
                width=width,
                brushes=make_brushes(cats),
                pen=pg.mkPen("black")
            )
            self.addItem(bar)

            axis = self.getPlotItem().getAxis("bottom")
            axis.setTicks([list(zip(x, cats))])
            self.setTitle(
                f"<span style='font-family:Microsoft JhengHei;'>{self.name}</span>"
            )
            return

        # 1. 取抽稀後的資料 -----------------------------------
        max_points = 100
        total = len(df)
        # 直接算「等距索引」一次到位
        idx = np.linspace(0, total - 1, max_points, dtype=int) if total > max_points \
            else np.arange(total)
        values = df[self.name].iloc[idx].values
        # ----------------------------------------------------

        # 2. 取目前機種對應的上下限 ----------------------------
        model = self.main_window.get_current_model()
        LSL, USL = self.main_window.config_manager.get_limits(self.name, model)
        LSL, USL = sorted([LSL, USL])
        # ----------------------------------------------------

        # 3. 如果「資料、上下限」都沒變，就不重畫 ---------------
        same_data = hasattr(self, "last_values") and np.array_equal(values, self.last_values)
        same_limit = getattr(self, "last_LSL", None) == LSL and getattr(self, "last_USL", None) == USL
        if same_data and same_limit:
            return
        # ----------------------------------------------------

        # 4. 記錄本次狀態
        self.last_values = values
        self.last_LSL, self.last_USL = LSL, USL

        # 5. 重新繪圖 -----------------------------------------
        self.clear()
        self.plot(idx, values, pen=pg.mkPen("blue", width=2))
        self.addItem(pg.InfiniteLine(pos=LSL, angle=0,
                                     pen=pg.mkPen("red", width=2, style=Qt.DashLine)))
        self.addItem(pg.InfiniteLine(pos=USL, angle=0,
                                     pen=pg.mkPen("green", width=2, style=Qt.DashLine)))
        self.setTitle(f'<span style="font-family: Microsoft JhengHei;">{self.name}</span>')

        ax = self.getPlotItem()
        for axis in ("left", "bottom"):
            ax.getAxis(axis).setTextPen(pg.mkPen("black"))
            ax.getAxis(axis).setPen(pg.mkPen("black"))
        ax.showGrid(x=True, y=True, alpha=0.1)

# ====================================================
# 自訂滑動開關 (CustomToggleSwitch)
# ====================================================
class CustomToggleSwitch(QWidget):
    """
    輕量級 ON / OFF 滑動開關。

    Parameters
    ----------
    checked : bool, default True
        建構時是否預設為「啟動」。
    """
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, *, checked: bool = True):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setFixedSize(60, 28)
        self.setCursor(Qt.PointingHandCursor)

    # --- 公共 API -------------------------------------------------
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        checked = bool(checked)
        if self._checked != checked:
            self._checked = checked
            self.toggled.emit(self._checked)
            self.update()

    # --- 事件 -----------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    # --- 繪製 -----------------------------------------------------
    def paintEvent(self, event):
        radius = self.height() / 2
        bg_color = QColor("#448AFF") if self._checked else QColor("#FF6666")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(self.rect(), radius, radius)

        circle_d = self.height() - 4
        circle_r = circle_d / 2
        circle_x = self.width() - circle_d - 2 if self._checked else 2
        circle_y = 2
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QPointF(circle_x + circle_r, circle_y + circle_r),
                            circle_r, circle_r)


# ====================================================
# 主視窗 (MainWindow)
# 負責整合所有模組與元件，並處理主要交互邏輯
# ====================================================
class MainWindow(QMainWindow):
    def __init__(self, file_path: str):
        super().__init__()

        # ===== 1. 基本屬性／設定 =====
        self.df: pd.DataFrame | None = None
        self.file_path = Path(file_path)
        self.settings = QSettings("MyCompany", "MyApp")
        self.base_title = Path(sys.executable).stem          # 執行檔名稱
        self.setWindowTitle(self.base_title)
        self.setWindowIcon(QIcon("../../Data.ico"))

        # ---- 使用者偏好 ----
        self.enabled_cols = set(filter(None,
                                       self.settings.value("enabled_cols", "").split(',')))
        self.ordered_cols = list(filter(None,
                                        self.settings.value("ordered_cols", "").split(',')))
        self.last_folder = Path(self.settings.value("last_folder", "", type=str))

        # ---- 旗標 ----
        self.paused = False
        self.lock_to_file = False
        self.result_order: list = []
        self.current_field = None
        self.field_limits = {}
        self.small_canvases = {}
        self.data_loader = None
        self._last_update_call = 0.0

        # ===== 2. 嘗試自動鎖定最新檔案 =====
        if not self.file_path.exists() and self.last_folder.is_dir():
            txts = (list(self.last_folder.glob("*.txt")) +
                    list(self.last_folder.glob("*.csv")) +
                    list(self.last_folder.glob("*.log")))
            if txts:
                self.file_path = max(txts, key=lambda p: p.stat().st_mtime)
                print("自動載入上次資料夾中的最新檔案:", self.file_path)
            else:
                print("上次選擇的資料夾中沒有 TXT/CSV/LOG 檔案，請重新選擇資料夾")
                self.file_path = Path('')             # 空路徑表示尚未載入
        self.data_manager = DataManager(str(self.file_path))

        self.config_manager = ConfigManager()
        self.current_loaded_file = None

        # ===== 3. 建構 UI =====
        central = QWidget(self)
        self.setCentralWidget(central)

        self.main_layout = QVBoxLayout(central)  # ＊改在這裡建
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self._build_menu()             # 選單列
        self._build_function_bar()     # 上方控制區
        self._build_main_splitter()    # 左右／上下視圖
        self.resize_by_screen()        # 初始視窗大小與位置

        # ===== 4. 檔案監控與定時器 =====
        self._init_file_watch()
        self._init_timer()

        # ===== 5. 首次載入資料 =====
        self.update_charts()
        QTimer.singleShot(500, lambda: self.switch_run_chart(self.current_field))

    def _on_loader_finished(self):
        # 執行緒已自然結束，安全地清空引用
        self.data_loader = None

    # =============================================================================
    # ↓↓↓  以下輔助方法
    # =============================================================================
    def _build_menu(self):
        """建立選單列"""
        self._load_result_colors()

        menu_tools = self.menuBar().addMenu("工具")
        menu_tools.setToolTipsVisible(True)  # ① 讓選單可以顯示 Tooltip
        self.statusBar()  # ② 建立狀態列，配合 statusTip

        # ---------------- 第一個動作範例 -----------------
        act_limits = menu_tools.addAction(
            "上下限總覽與編輯",
            lambda: LimitEditor(self).exec_()
        )
        act_limits.setToolTip("一次檢視 / 編輯所有機種的 LSL / USL")  # ③ 滑鼠懸停提示
        act_limits.setStatusTip(act_limits.toolTip())  # 顯示在視窗最底端

        # ---------------- 以下照抄即可 -----------------
        act_colors = menu_tools.addAction("長條圖顏色設定", self.edit_colors)
        act_colors.setToolTip("設定『測試結果』長條圖的 OK / NG 顏色")
        act_colors.setStatusTip(act_colors.toolTip())

        act_summary = menu_tools.addAction("檔案摘要", self.show_folder_summary)
        act_summary.setToolTip("統計目前資料夾所有檔案的稼動率、UPH、良率")
        act_summary.setStatusTip(act_summary.toolTip())

        act_field = menu_tools.addAction("小圖欄位勾選", lambda: FieldPicker(self).exec_())
        act_field.setToolTip("選擇 TrendCanvas 要顯示哪些欄位")
        act_field.setStatusTip(act_field.toolTip())

        act_yield = menu_tools.addAction("良率標籤設定", lambda: YieldTagEditor(self).exec_())
        act_yield.setToolTip("設定良率計算時的 OK / NG 關鍵字")
        act_yield.setStatusTip(act_yield.toolTip())

    def _build_function_bar(self):
        """上方控制列：上下限、停機秒數、檔案 / 資料夾選擇、滑桿"""
        bar = QWidget()
        layout = QGridLayout(bar)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setHorizontalSpacing(15)

        # ---- 上下限 ----
        self.lsl_edit, self.usl_edit = QLineEdit(), QLineEdit()
        self.usl_edit.setToolTip("USL：量測上限")
        self.lsl_edit.setToolTip("LSL：量測下限")
        layout.addWidget(QLabel("上限:"), 0, 0, alignment=Qt.AlignRight)
        layout.addWidget(self.usl_edit, 0, 1)
        layout.addWidget(QLabel("下限:"), 1, 0, alignment=Qt.AlignRight)
        layout.addWidget(self.lsl_edit, 1, 1)

        # ---- 停機秒數 ----
        self.gap_threshold_edit = QLineEdit()
        self.gap_threshold_edit.setToolTip("若連續超過此秒數無資料 → 判定停機")
        self.gap_threshold_edit.setText(
            str(self.settings.value("gap_threshold", self.GAP_FALLBACK, type=float))
        )
        layout.addWidget(QLabel("停機時間設定(秒):"), 0, 2, alignment=Qt.AlignRight)
        layout.addWidget(self.gap_threshold_edit, 0, 3)

        btn_update = QPushButton("更新設定值", clicked=self.update_limits)
        btn_update.setToolTip("把上下限 / 停機 / 休息時間寫回設定並重新繪圖")
        layout.addWidget(btn_update, 1, 4)
        self.gap_threshold_edit.editingFinished.connect(self.save_gap_threshold)
        # ---- 休息分鐘 ----
        self.rest_threshold_edit = QLineEdit()
        self.rest_threshold_edit.setToolTip(
            "超過此分鐘數設定為休息時間（UPH 不計）")
        self.rest_threshold_edit.setText(
            str(self.settings.value("rest_threshold_min", 15, type=float))
        )
        layout.addWidget(QLabel("休息時間設定(分):"), 1, 2, alignment=Qt.AlignRight)
        layout.addWidget(self.rest_threshold_edit, 1, 3)
        # ---- 檔案 / 資料夾 ----
        btn_file   = QPushButton("選擇檔案",   clicked=self.select_file)
        btn_file.setToolTip("手動挑一個 TXT / CSV / LOG 並立即載入")
        btn_folder = QPushButton("選擇資料夾", clicked=self.select_folder)
        btn_folder.setToolTip("改監看整個資料夾，每次自動載入最新檔")
        layout.addWidget(btn_file,   0, 4)
        layout.addWidget(btn_folder, 0, 5)

        # ---- 自動更新開關 & 滑桿 ----
        self.toggle_switch = CustomToggleSwitch(checked=True)
        self.toggle_switch.setToolTip(
            "ON：持續監看並即時更新圖表\nOFF：暫停更新並顯示停機線")
        self.toggle_switch.toggled.connect(self.toggle_pause)
        layout.addWidget(self.toggle_switch, 0, 6)
        layout.addWidget(QLabel("解析度(%)"), 0, 7)

        self.slider = QSlider(Qt.Horizontal, minimum=1, maximum=100,
                              value=self.settings.value("slider_value", 100, int))
        self.slider.setToolTip("控制趨勢圖抽稀比例，100 %＝不抽稀")
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(10)
        self.slider.valueChanged.connect(self.slider_changed)
        layout.addWidget(self.slider, 0, 8, 1, 2)
        self.default_bin_num = max(10, self.slider.value())

        # ---- Enter 直接觸發更新 ----
        for w in (self.gap_threshold_edit,
                  self.rest_threshold_edit,
                  self.lsl_edit, self.usl_edit):
            w.returnPressed.connect(self.update_limits)

        # ---- 放進主 layout ----
        self.main_layout.addWidget(bar)

    def _build_main_splitter(self):
        """左：小圖容器；右：上下（能力圖 / 趨勢圖）"""
        splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(splitter, 1)

        # 左側小圖
        left_container = CanvasContainer(main_window=self)
        self.left_layout = left_container.layout
        scroll = QScrollArea(widgetResizable=True); scroll.setWidget(left_container)
        scroll.setMinimumWidth(200)
        splitter.addWidget(scroll)

        # 右側上下
        right = QSplitter(Qt.Vertical); right.setMinimumWidth(300)
        splitter.addWidget(right)

        #   右上：能力圖
        self.capability_canvas = CapabilityPanel(main_window=self)
        cap_w = QWidget(); cap_lay = QVBoxLayout(cap_w); cap_lay.addWidget(self.capability_canvas)
        cap_w.setMinimumHeight(200)
        right.addWidget(cap_w)

        #   右下：趨勢圖
        times = (self.df["datetime"].tolist() if self.df is not None and not self.df.empty else None)
        self.trend_canvas = TrendCanvas(main_window=self, times=times)
        self.trend_canvas.setToolTip(
            "趨勢圖滑鼠操作：\n"  
            "• 左鍵：框選區間並同步能力圖\n"
            "• 右鍵拖曳：縮放\n"
            "• 滾輪：放大 / 縮小\n"
            "• 雙擊左鍵後按住：平移"
        )
        trend_w = QWidget(); trend_lay = QVBoxLayout(trend_w); trend_lay.addWidget(self.trend_canvas)
        trend_w.setMinimumHeight(200)
        right.addWidget(trend_w)

        #   信號
        self.trend_canvas.subrange_selected.connect(self.analyze_subrange)
        self.trend_canvas.view_all_requested.connect(self.view_all_capability)

        # Stretch
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 8)
        right.setStretchFactor(0, 6)  # 能力圖佔 1 份
        right.setStretchFactor(1, 4)  # 趨勢圖佔 3 份

    def resize_by_screen(self):
        """根據螢幕大小設定初始視窗 Size & 位置"""
        scr = QDesktopWidget().availableGeometry()
        self.resize(int(scr.width() * 0.5), int(scr.height() * 0.97))
        self.move(scr.right() - self.width(), scr.top())

    def _init_file_watch(self):
        """檔案系統監控"""
        self.observer = Observer()
        if self.file_path.parent.exists():
            handler = FileChangeHandler(str(self.file_path))
            self.observer.schedule(handler, path=str(self.file_path.parent), recursive=False)
            self.observer.start()
        else:
            QMessageBox.warning(self, "錯誤", f"無法監控資料夾：{self.file_path.parent}")

    def _init_timer(self):
        self.timer = QTimer(interval=500, timeout=self.check_file_update)
        self.timer.start()

    GAP_FALLBACK = 20.0  # 全域預設
    # ---- 讀取目前有效 gap_threshold ----
    def get_gap_threshold(self) -> float:
        """
        任何地方都用這支拿 gap_threshold。
        1. 先看輸入框內容能不能轉 float
        2. 不行就讀 QSettings
        3. 再不行就用 fallback
        """
        try:
            return float(self.gap_threshold_edit.text())
        except (ValueError, AttributeError):
            return self.settings.value("gap_threshold",
                                       self.GAP_FALLBACK,
                                       type=float)

    # 回傳『休息時間門檻』秒數"""
    def get_rest_threshold(self) -> float:
        """回傳『休息時間門檻』秒數"""
        try:
            # 這裡輸入的是「分鐘」，轉秒
            return float(self.rest_threshold_edit.text()) * 60.0
        except (ValueError, AttributeError):
            return self.settings.value("rest_threshold_min", 15, type=float) * 60.0

    #    存回設定 休息時間
    def save_rest_threshold(self):
        self.settings.setValue(
            "rest_threshold_min",
            float(self.rest_threshold_edit.text() or 15)
        )
        self.settings.sync()
    # ---- 把輸入框內容寫回 QSettings（按 Enter 或按鈕「更新設定值」時呼叫）----
    def save_gap_threshold(self):
        val = self.get_gap_threshold()
        self.settings.setValue("gap_threshold", val)
        self.settings.sync()

    def _load_result_colors(self):
        st = QSettings("MyCompany", "MyApp")
        for k in st.allKeys():
            if k.startswith("result_colors/"):
                cat = k.split('/', 1)[1]
                COLOR_MAP[cat] = st.value(k)
    # ----------------------------
    # 檔案摘要：列出資料夾內所有檔案資訊
    # ----------------------------
    def show_folder_summary(self):
        folder = os.path.dirname(self.file_path)
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "錯誤", "目前檔案路徑無效，無法列出摘要！")
            return

        files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith((".txt", ".csv", ".log"))
               and os.path.isfile(os.path.join(folder, f))  # ← 加回檔案判斷
        ]
        # 依最後修改時間遞減（最新在上）
        files.sort(key=os.path.getmtime, reverse=True)

        if not files:
            QMessageBox.information(self, "提示", "此資料夾沒有 TXT/CSV/LOG 檔案。")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)  # 沙漏游標
        rows = []
        gap_val = self.get_gap_threshold()
        rest_sec = self.get_rest_threshold()
        try:
            for fp in files:
                try:
                    info = gather_file_info(fp, gap_val, rest_sec)  # ← 算一次就夠
                    info["_mtime"] = os.path.getmtime(fp)
                    rows.append(info)
                except Exception as e:
                    print(f"[摘要] 讀檔失敗 {fp} → {e}")
        finally:
            QApplication.restoreOverrideCursor()  # 一定要恢復游標

        if not rows:
            QMessageBox.warning(self, "錯誤", "無法讀取任何檔案！")
            return

        FolderSummaryDialog(rows, folder, self).exec_()

    def edit_colors(self):
        # 1. 補齊 COLOR_MAP
        text_field = self.current_field if is_text_column(self.df[self.current_field]) else None
        if text_field:
            vals = self.df[text_field].astype(str)
            counts = vals.value_counts()  # Series 由多到少
            ordered = list(counts.index)  # 取得排序好的類別
            for cat in ordered:
                COLOR_MAP.setdefault(cat, "gray")
        else:
            ordered = sorted(COLOR_MAP.keys())  # 後備

        # 2. 開對話框
        dlg = ColorEditor(COLOR_MAP, self.result_order, self)
        if dlg.exec_():
            # 重新更新所有小圖
            for canvas in self.small_canvases.values():
                canvas.update_run(self.df)

            # 如果目前欄位是文字／分類，就畫長條圖，套用新顏色
            if self.df is not None and is_text_column(self.df[self.current_field]):
                self.trend_canvas.plot_test_result_bar(self.df, field=self.current_field)
            # 否則，就依然畫走勢圖
            elif self.current_field:
                self.trend_canvas.plot_trend(self.df, name=self.current_field)

    def get_current_model(self):
        """回傳最新一筆資料的『機種』字串；若資料或欄位不存在則回 None"""
        if self.df is not None and "機種" in self.df.columns and not self.df.empty:
            return str(self.df["機種"].iloc[-1])
        return None

    # ----------------------------
    # 各種訊號處理與更新方法：滑桿變動、更新資料、切換圖表等
    # ----------------------------
    def slider_changed(self, value):
        self.settings.setValue("slider_value", value)
        self.default_bin_num = max(10, value)  # 根據滑桿設定調整直方圖柱數
        print(f"更新滑桿值：{value} 根柱子")
        if self.df is not None and not self.df.empty and self.current_field:
            self.analyze_data(self.df, self.current_field)
            self.trend_canvas.plot_trend(self.df, name=self.current_field)
        else:
            self.update_charts()

    def load_initial_limits(self):
        # 先決定欄位
        field = self.current_field if self.current_field else "Picth_MD"
        model = self.get_current_model()  # 目前最新機種
        lsl, usl = self.config_manager.get_limits(field, model)

        # 若此機種沒有專屬設定 → 改抓共用或用資料本身 min/max 當預設
        if lsl is None or usl is None:
            if self.df is not None and field in self.df.columns:
                lsl = self.df[field].min()
                usl = self.df[field].max()
            else:
                lsl, usl = 0.0, 10.0

        self.current_field = field
        self.lsl_edit.setText(str(lsl))
        self.usl_edit.setText(str(usl))

    def toggle_downtime_lines(self, checked: bool):
        # 切換是否顯示停機區間線
        self.show_downtime_lines = checked
        print(f"顯示停機線: {self.show_downtime_lines}")
        self.update_charts()

    def toggle_pause(self, is_on: bool):
        """
        控制資料更新狀態：
        is_on=True 時表示自動更新；is_on=False 時則暫停更新並顯示停機線
        """
        print(f"[toggle_pause] is_on={is_on}")
        if is_on:
            self.paused = False
            self.show_downtime_lines = False
            self.update_charts()
        else:
            self.paused = True
            self.show_downtime_lines = True
            if self.df is not None and not self.df.empty:
                self.handle_data_loaded(self.df)
        if self.df is not None and not self.df.empty and self.current_field:
            self.switch_run_chart(self.current_field)

    def check_file_update(self):
        # 若目前鎖定單檔，就不要自動換檔
        if getattr(self, "lock_to_file", False):
            return
        # 若處於暫停狀態則不檢查更新
        if self.paused:
            return
        # ---------- throttle ----------
        now = time.time()
        if now - self._last_update_call < 0.5:
            return
        self._last_update_call = now
        # ------------------------------
        if update_event.is_set():
            update_event.clear()
            self.update_charts()
        folder = os.path.dirname(self.file_path)
        files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(('.txt', '.csv', '.log'))
               and os.path.isfile(os.path.join(folder, f))
        ]
        if files:
            newest = max(files, key=os.path.getmtime)
            if newest != self.file_path:
                print("偵測到新檔案，切換至", newest)
                self.file_path = newest
                self.data_manager.file_path = newest
                self.update_charts()

    def update_charts(self):
        # 若處於暫停狀態或檔案不存在時，不更新圖表
        if self.paused or not self.file_path or not os.path.isfile(self.file_path):
            return
        current_mtime = os.path.getmtime(self.file_path)
        if hasattr(self, 'last_mtime') and self.last_mtime == current_mtime:
            return
        self.last_mtime = current_mtime

        # 使用 DataLoader 非同步讀取資料，讀取完成後觸發 handle_data_loaded
        self.data_loader = DataLoader(self.file_path)
        # 確保每次都是 fresh 的
        self.data_loader.stop_requested = False
        self.data_loader.data_loaded.connect(self.handle_data_loaded)
        self.data_loader.finished.connect(self._on_loader_finished)
        self.data_loader.start()


    def handle_data_loaded(self, df):
        # 先抓到真正發出 data_loaded 訊號的執行緒
        loader = self.sender()
        # 如果新讀入的 df 與舊 df 幾乎相同則不更新
        if self.df is not None and not self.df.empty and df is not None:
            if len(df) == len(self.df) and df["datetime"].iloc[-1] == self.df["datetime"].iloc[-1]:
                return
        if hasattr(self, "spinner"):
            self.spinner.hide()
        if df is None or df.empty:
            return
        if df is not None and not df.empty:
            base_name = os.path.basename(self.file_path)
            # 更新視窗標題：MyApp – 5101-1140206016_Hitag2…1.TXT
            self.setWindowTitle(f"{self.base_title} — {base_name}")
            # 取得完整的時間列表，更新 TrendCanvas 的底部軸
            times_list = df["datetime"].tolist()
            self.trend_canvas.getPlotItem().setAxisItems({
                'bottom': TimeAxisItem(times_list, orientation='bottom')
            })

        # 自動轉換舊版欄位設定至新版
        if self.settings.value("field_limits/Picth_MD/lsl", None) is None:
            old_lsl_x = self.settings.value("field_limits/Picth_X/lsl", None, type=float)
            old_usl_x = self.settings.value("field_limits/Picth_X/usl", None, type=float)
            if old_lsl_x is not None and old_usl_x is not None:
                self.settings.setValue("field_limits/Picth_MD/lsl", old_lsl_x)
                self.settings.setValue("field_limits/Picth_MD/usl", old_usl_x)
                self.settings.remove("field_limits/Picth_X/lsl")
                self.settings.remove("field_limits/Picth_X/usl")

        if self.settings.value("field_limits/Picth_TD/lsl", None) is None:
            old_lsl_y = self.settings.value("field_limits/Picth_Y/lsl", None, type=float)
            old_usl_y = self.settings.value("field_limits/Picth_Y/usl", None, type=float)
            if old_lsl_y is not None and old_usl_y is not None:
                self.settings.setValue("field_limits/Picth_TD/lsl", old_lsl_y)
                self.settings.setValue("field_limits/Picth_TD/usl", old_usl_y)
                self.settings.remove("field_limits/Picth_Y/lsl")
                self.settings.remove("field_limits/Picth_Y/usl")

        # 將欄位名稱轉換成新版（Picth_X -> Picth_MD, Picth_Y -> Picth_TD）
        rename_dict = {}
        if "Picth_X" in df.columns:
            rename_dict["Picth_X"] = "Picth_MD"
        if "Picth_Y" in df.columns:
            rename_dict["Picth_Y"] = "Picth_TD"
        if rename_dict:
            df.rename(columns=rename_dict, inplace=True)

        self.df = df

        self.load_initial_limits()
        base_name = os.path.basename(self.file_path)

        # 抓最新的 Operator / IC Type（如果有）
        op = df["Operator"].iloc[-1] if "Operator" in df.columns else "—"
        try:  # 先嘗試轉成整數
            op = int(op)
        except (ValueError, TypeError):
            pass  # 轉不動就保持原字串
        self.latest_operator = str(op)

        self.latest_ic_type = (
            df["IC Type"].iloc[-1] if "IC Type" in df.columns else "—"
        )

        if "剃補次數" in df.columns and not df.empty:
            self.global_change_count = df["剃補次數"].max() - df["剃補次數"].min()
        else:
            self.global_change_count = 0

        measure_cols = [c for c in self.df.columns if c not in ("datetime", "機種")]
        self.enabled_cols = {c for c in
        self.settings.value("enabled_cols", ",".join(measure_cols)).split(",") if c}


        is_new_file = (self.current_loaded_file != self.file_path)
        self.current_loaded_file = self.file_path
        self.rebuild_small_canvases(measure_cols, fresh=is_new_file)

        # 更新每個小運行圖
        for col, canvas in self.small_canvases.items():
            canvas.update_run(self.df)

        if (self.current_field not in measure_cols) and measure_cols:
            self.current_field = measure_cols[0]
        if self.current_field:
            # 直接重畫能力圖與趨勢圖 → 大圖也會跟著新檔資料
            self.switch_run_chart(self.current_field)

        if self.current_field:
            # ▲ 先算完能力圖之後，改成用 get_limits 取值
            model = self.get_current_model()
            lsl, usl = self.config_manager.get_limits(self.current_field, model)
            if lsl is None or usl is None:
                lsl, usl = self.df[self.current_field].min(), self.df[self.current_field].max()

            # 快取給其他地方用
            self.field_limits[self.current_field] = (lsl, usl)

            # 更新畫面
            self.lsl_edit.setText(str(lsl))
            self.usl_edit.setText(str(usl))


        if loader is self.data_loader:  # <─ 新增
            self.data_loader = None  # <─ 新增

    def rebuild_small_canvases(self, measure_cols, fresh=False):
        # 如果沒有任何設定 (第一次執行) 才全部選取
        chosen = {c for c in self.enabled_cols if c in measure_cols} or set(measure_cols)
        """
        根據提供的欄位清單重建或更新左側小圖，
        如果 fresh=True 則完全重建，且順序根據先前設定。
        """
        if fresh:
            for i in reversed(range(self.left_layout.count())):
                w = self.left_layout.itemAt(i).widget()
                if w:
                    self.left_layout.removeWidget(w)
                    w.setParent(None)
                    w.deleteLater()
            self.small_canvases.clear()
        # 依照 chosen 及已存順序決定 self.ordered_cols
        self.ordered_cols = [c for c in self.ordered_cols if c in chosen]
        for col in measure_cols:
            if col in chosen and col not in self.ordered_cols:
                self.ordered_cols.append(col)
        self.settings.setValue("ordered_cols", ",".join(self.ordered_cols))


        # 建立或更新每個欄位所對應的小圖
        current_model = self.get_current_model()
        for col in self.ordered_cols:
            if fresh or (col not in self.small_canvases):
                lsl, usl = self.config_manager.get_limits(col, current_model)
                if lsl is None or usl is None:
                    lsl, usl = 0.0, 10.0
                self.field_limits[col] = (lsl, usl)
                canvas = SmallRunPlotWidget(parent=None, name=col, main_window=self)
                canvas.setToolTip(
                    "小圖操作：\n"
                    "• 點擊：切換到主趨勢圖\n"
                    "• 拖曳：重新排序"
                )
                self.small_canvases[col] = canvas

        # 移除原有所有小圖，再依照正確順序加入
        for i in reversed(range(self.left_layout.count())):
            w = self.left_layout.itemAt(i).widget()
            if w:
                self.left_layout.removeWidget(w)

        for col in self.ordered_cols:
            self.left_layout.addWidget(self.small_canvases[col])

    def select_folder(self):
        # 開啟資料夾對話框以選擇新的資料夾
        folder_path = QFileDialog.getExistingDirectory(self, "選擇資料夾", self.settings.value("last_folder", ""))
        if not folder_path:
            return
        self.last_folder = folder_path
        self.settings.setValue("last_folder", folder_path)
        self.lock_to_file = False
        txt_files = []
        for f in os.listdir(folder_path):
            full_path = os.path.join(folder_path, f)
            if f.lower().endswith((".txt", ".csv", ".log")) and os.path.isfile(full_path):
                txt_files.append(full_path)
        if not txt_files:
            QMessageBox.warning(self, "警告", "該資料夾沒有 TXT、CSV 或 LOG 檔案！")
            self.capability_canvas.clear_panel()
            self.trend_canvas.clear()
            self.lsl_edit.clear()
            self.usl_edit.clear()
            for _, canvas in self.small_canvases.items():
                canvas.clear()
            return
        newest_txt = max(txt_files, key=os.path.getmtime)
        print("最新檔案:", newest_txt)
        self.file_path = newest_txt
        base_name = os.path.basename(newest_txt)
        self.setWindowTitle(f"{self.base_title} — {base_name}")
        self.data_manager.file_path = newest_txt
        self.update_charts()
        self.current_field = None
        # 更新檔案監控目錄
        self.observer.unschedule_all()
        file_dir = os.path.dirname(newest_txt)
        handler = FileChangeHandler(newest_txt)
        self.observer.schedule(handler, path=file_dir, recursive=False)

    def select_file(self):
        """
        直接挑單一 TXT/CSV/LOG 檔並載入
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇檔案", self.settings.value("last_folder", ""),
            "Data Files (*.txt *.csv *.log)"
        )
        if not path:
            return

        self.file_path = path
        self.settings.setValue("last_folder", os.path.dirname(path))
        self.settings.sync()

        base_name = os.path.basename(path)
        self.setWindowTitle(f"{self.base_title} — {base_name}")
        self.data_manager.file_path = path
        self.update_charts()

        # 更新檔案監控目錄
        self.observer.unschedule_all()
        handler = FileChangeHandler(path)
        self.observer.schedule(handler, path=os.path.dirname(path), recursive=False)
        self.lock_to_file = True

    def switch_run_chart(self, name: str, save_before_switch=False):
        """
        切換目前顯示的量測欄位 (小圖點擊或左側拖放後)
        1. 先把目前輸入框內容存回設定檔
        2. 重新繪製能力圖 / 趨勢圖
        3. 將「下限 / 上限」輸入框改成**最新機種**的設定值
        """
        if save_before_switch:
            self.update_limits()
        # ---------- 2. 基本防呆 ----------
        if self.df is None or self.df.empty or name not in self.df.columns:
            print(f"⚠️ DataFrame 中沒有欄位：{name}")
            return

        self.current_field = name
        df = self.df
        

        if is_text_column(df[name]):
            # ① 計算基本統計（UPH、稼動率……）
            gap_val = self.get_gap_threshold()

            rest_sec = self.get_rest_threshold()
            stats = get_basic_stats(df, gap_val, rest_sec)
            boot_m, boot_s = stats["boot_mmss"]
            run_m, run_s = stats["run_mmss"]
            down_m, down_s = stats["down_mmss"]
            rest_m, rest_s = stats["rest_mmss"]


            # 原來的 util_val、downtime_val、uph_val、machine_uph
            util_val = stats["util"]
            uph_val = stats["uph"]
            machine_uph = stats["machine_uph"]
            self.data_manager.load_csv_data(self.file_path)

            # ② 準備表格資料
            header = f'<div style="font-size:18px;font-weight:bold;margin-bottom:5px;">{name}</div>'
            main_stats = [
                ("目前機種", self.get_current_model() or "—"),
                ("產品類別", self.data_manager.product_category or "—"),
                ("Operator", getattr(self, "latest_operator", "—")),
                ("IC Type", getattr(self, "latest_ic_type", "—")),
                ("取樣數", f"{len(df)}"),
                ("總開機時間", f"{boot_m}m {boot_s}s"),
                ("運行時間", f"{run_m}m {run_s}s"),
                ("停機時間", f"{down_m}m {down_s}s"),
                ("休息時間", f"{rest_m}m {rest_s}s"),  # ← 放進來
                ("稼動率", f"{util_val:.2f}%"),
                ("UPH", f"{uph_val:.0f}")
            ]
            second_stats = [
                ("機台UPH", f"{machine_uph:.0f}")
            ]

            # ③ 顯示表格、清掉能力圖
            self.capability_canvas.show_info(header, main_stats, second_stats)

            # ④ 趨勢圖改畫長條圖
            self.trend_canvas.plot_test_result_bar(df, field=name)   # 傳目前欄位名稱

            # ⑤ 清空上下限輸入框
            self.lsl_edit.clear()
            self.usl_edit.clear()
            return  # 直接結束，不跑後面一般流程

        # ---------- 3. 先算一些共用統計 ----------
        gap_val = self.get_gap_threshold()

        rest_sec = self.get_rest_threshold()
        stats = get_basic_stats(df, gap_val, rest_sec)
        util_val = stats["util"]
        downtime_val = stats["downtime"]
        uph_val = stats["uph"]
        machine_uph = stats["machine_uph"]
        total_time_val = stats["total_sec"]

        # ---------- 4. 取得「最新一筆資料」的機種 ----------
        model = self.get_current_model()  # <── 這行是關鍵

        # ---------- 5. 依機種抓 LSL / USL ----------
        lsl, usl = self.config_manager.get_limits(name, model)

        # 若該機種沒有設定，就用欄位本身範圍先頂住
        if lsl is None or usl is None or usl <= lsl:
            lsl = df[name].min()
            usl = df[name].max()

        # 快取一份供小圖使用
        self.field_limits[name] = (lsl, usl)

        # ---------- 6. 畫能力圖 / 趨勢圖 ----------
        self.capability_canvas.plot_capability(
            data_series=df[name],
            name=name,
            uph_val=uph_val,
            util_val=util_val,
            downtime_val=downtime_val,
            total_time_val=total_time_val,
            machine_uph_val=machine_uph,
            current_model=model,
            rest_mmss = stats["rest_mmss"]
        )
        self.trend_canvas.plot_trend(df, name=name)

        # ---------- 7. 更新輸入框顯示 ----------
        self.lsl_edit.setText(str(lsl))
        self.usl_edit.setText(str(usl))

    def view_all_capability(self):
        # 重新分析及繪製整個數據區間的能力圖
        if self.df is not None and not self.df.empty and self.current_field:
            self.analyze_data(self.df, self.current_field)

    def update_limits(self):
        try:
            new_lsl = float(self.lsl_edit.text())
            new_usl = float(self.usl_edit.text())
        except ValueError:
            print("請輸入數字!")
            return
        field = self.current_field
        if not field:
            print("尚未選擇欄位，無法更新上下限。")
            return

        model = self.get_current_model()
        self.config_manager.set_limits(field, new_lsl, new_usl, model)
        self.field_limits[field] = (new_lsl, new_usl)

        gap_val = self.get_gap_threshold()
        self.settings.setValue("gap_threshold",gap_val)

        self.last_mtime = 0
        if self.df is not None and not self.df.empty:
            self.analyze_data(self.df, field)
            for col, canvas in self.small_canvases.items():
                canvas.update_run(self.df)
        self.trend_canvas.plot_trend(self.df, name=field)
        self.save_gap_threshold()
        self.save_rest_threshold()
        if self.current_field:
            self.switch_run_chart(self.current_field)

    def analyze_data(self, data_df: pd.DataFrame, field: str, sub_range: pd.DataFrame = None):
        if data_df is None or data_df.empty or not field:
            return

        gap_val = self.get_gap_threshold()
        rest_sec = self.get_rest_threshold()

        uph_val = compute_uph(data_df, gap_val, rest_sec)
        util_val, downtime_val, resttime_val = compute_util_down_rest(data_df, gap_val, rest_sec)
        total_time_val = (data_df["datetime"].iloc[-1] - data_df["datetime"].iloc[0]).total_seconds()
        machine_uph = compute_machine_uph(data_df, gap_val, rest_sec)

        self.capability_canvas.plot_capability(
            data_series=data_df[field],
            name=field,
            uph_val=uph_val,
            sub_df=sub_range,
            util_val=util_val,
            downtime_val=downtime_val,
            total_time_val=total_time_val,
            machine_uph_val=machine_uph,
            current_model=self.get_current_model()
        )

    def analyze_subrange(self, start_idx, end_idx):
        """
        針對目前選擇欄位，對選取的資料區間進行統計分析。
        """
        if self.df is None or self.df.empty or self.current_field not in self.df.columns:
            return

        sub_df = self.df.iloc[start_idx:end_idx + 1]
        if sub_df.empty:
            return

        print(f"選取的區間：{start_idx} ~ {end_idx}，共有 {len(sub_df)} 筆資料")
        self.analyze_data(sub_df, self.current_field, sub_df)


    def closeEvent(self, event):
        # 關閉視窗前停止計時器、監控器、以及可能還在執行的 DataLoader
        self.timer.stop()
        self.observer.stop()
        self.observer.join()
        if self.data_loader and self.data_loader.isRunning():
            self.data_loader.stop_requested = True
            self.data_loader.quit()  # 發 quit
            self.data_loader.wait(1000)  # 最多等 1 秒
        event.accept()
        super().closeEvent(event)

# ====================================================
# 資料夾檔案摘要對話框（日期範圍 + 顯示全部 + 正確排序）
# ====================================================
class FolderSummaryDialog(QDialog):
    def __init__(self, rows: list, folder_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("檔案摘要總覽")
        self.resize(1200, 650)

        self.all_rows = rows
        self.folder_path = folder_path
        self.headers = [
            "檔案名稱","產品類別" , "IC TYPE","Operator",
            "總開機時間", "運行時間", "停機時間", "休息時間",
            "稼動率", "機台UPH", "實際UPH", "總數", "良率"
        ]
        self.numeric_cols = {"總數", "機台UPH", "實際UPH", "稼動率"}  # 需要數字排序的欄
        self.numeric_cols.add("良率")
        self.numeric_cols.update({"休息時間", "良率"})

        # ---------- 日期範圍 ----------
        box = QGroupBox("日期篩選 (依檔案最後修改時間)")
        h = QHBoxLayout(box)
        self.start_edit = QDateEdit(calendarPopup=True)
        self.end_edit   = QDateEdit(calendarPopup=True)
        today = QDate.currentDate()
        self.start_edit.setDate(today)
        self.end_edit.setDate(today)

        btn_apply  = QPushButton("套用")
        btn_apply.clicked.connect(self.apply_filter)

        btn_all = QPushButton("顯示全部")          # ← 新增按鈕
        btn_all.clicked.connect(lambda: self.populate_table(self.all_rows))

        h.addWidget(QLabel("起:")); h.addWidget(self.start_edit)
        h.addWidget(QLabel("迄:")); h.addWidget(self.end_edit)
        h.addStretch()
        h.addWidget(btn_apply)
        h.addWidget(btn_all)

        # ---------- 表格 ----------
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.populate_table(self.all_rows)

        # ---------- 版面 ----------
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addWidget(self.table, 1)
        # 右下角「匯出 CSV」按鈕
        btn_export = QPushButton("匯出 CSV")
        btn_export.clicked.connect(self.export_csv)
        btn_tags = QPushButton("良率標籤設定")
        btn_tags.clicked.connect(self.edit_yield_tags)

        hbtn = QHBoxLayout()
        hbtn.addStretch()
        hbtn.addWidget(btn_tags)
        hbtn.addWidget(btn_export)
        lay.addLayout(hbtn)

    def edit_yield_tags(self):
        dlg = YieldTagEditor(self)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh_summary()

    def refresh_summary(self):
        import os
        new_rows = []
        for r in self.all_rows:  # 只需檔名即可
            fname = r["檔案名稱"]
            fp = os.path.join(self.folder_path, fname)
            try:
                info = gather_file_info(fp, self.parent().get_gap_threshold(),
                                        self.parent().get_rest_threshold())
                info["_mtime"] = os.path.getmtime(fp)
                new_rows.append(info)
            except Exception as e:
                print(f"[摘要刷新] 讀檔失敗 {fp} → {e}")
        self.all_rows = new_rows
        self.populate_table(new_rows)

    # ------------------------------------------------
    # 依 rows 重建表格
    # ------------------------------------------------
    def populate_table(self, rows: list):
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, h in enumerate(self.headers):
                txt = str(row.get(h, ""))
                if h == "Operator":
                    try:
                        txt = str(int(float(txt)))
                    except ValueError:
                        pass
                item = QTableWidgetItem(txt)
                # 左／右對齊規則保留
                if h in {"總數", "機台UPH", "實際UPH", "稼動率"}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(r, c, item)

    # ------------------------------------------------
    # 「套用篩選」- 依日期區間過濾
    # ------------------------------------------------
    def apply_filter(self):
        start_dt = self.start_edit.date().toPyDate()
        end_dt   = self.end_edit.date().toPyDate()
        if start_dt > end_dt:
            QMessageBox.warning(self, "錯誤", "起始日期不可晚於結束日期！")
            return

        start_ts = datetime.combine(start_dt, datetime.min.time()).timestamp()
        end_ts   = datetime.combine(end_dt,   datetime.max.time()).timestamp()

        filtered = [
            row for row in self.all_rows
            if start_ts <= row.get("_mtime", 0) <= end_ts
        ]
        self.populate_table(filtered)
    # ------------------------------------------------
    # 匯出目前表格內容為 CSV
    # ------------------------------------------------
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出為 CSV", "summary.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            # 標頭
            writer.writerow(self.headers)
            # 逐列寫入
            for r in range(self.table.rowCount()):
                row_data = [
                    self.table.item(r, c).text() if self.table.item(r, c) else ""
                    for c in range(self.table.columnCount())
                ]
                writer.writerow(row_data)

        QMessageBox.information(self, "完成", f"已匯出到：\n{path}")

    # ------------------------------------------------
    # 把字串 "%", "m" 之類去掉，轉成 float 供排序
    # ------------------------------------------------
    @staticmethod
    def _to_number(text: str):
        try:
            text = text.strip().replace("%", "")
            return float(text)
        except ValueError:
            return 0.0

# ====================================================
# 收集「單一檔案」的重要摘要資訊
# ====================================================
def gather_file_info(file_path: str,
                     gap_sec: float = 20.0,
                     rest_sec: float = 900.0) -> dict:
    dm = DataManager(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    df = dm.load_csv_data(file_path) if ext == ".csv" else dm.load_txt_data(file_path)
    dm .load_csv_data(file_path)
    if df is None or df.empty:
        return {"檔案名稱": os.path.basename(file_path)}

    # 共用統計 -----------------------------------------------------------
    stats = get_basic_stats(df, gap_sec, rest_sec)    # ★ 用同門檻
    boot_m, boot_s = stats["boot_mmss"]
    run_m, run_s = stats["run_mmss"]
    down_m, down_s = stats["down_mmss"]
    rest_m, rest_s = stats["rest_mmss"]

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
        "稼動率": f"{stats['util']:.2f}%",
        "機台UPH": f"{stats['machine_uph']:.0f}",
        "實際UPH": f"{stats['uph']:.0f}",
        "良率": f"{compute_yield(df, GOOD_TAGS, BAD_TAGS):.2f}%"
    }

# ====================================================
# 自訂時間軸 (TimeAxisItem)
# 使用抽稀後資料的索引對應抽稀後的時間列表，顯示格式化時間
# ====================================================
class TimeAxisItem(pg.AxisItem):
    def __init__(self, times, *args, **kwargs):
        """
        times: 一個 list 存放抽稀後各資料點建立的 datetime 物件
        """
        super().__init__(*args, **kwargs)
        self.times = times

    def tickStrings(self, values, scale, spacing):
        """
        values  = pyqtgraph 要求你顯示刻度的位置 (float)
        spacing = 兩個相鄰刻度在資料座標的距離
                  ── 小刻度 ≈ spacing < 1
                  ── 中刻度 ≈ 1 ≲ spacing < 5
                  ── 大刻度 ≈ spacing ≥ 5
        """
        labels = []
        last_idx = None

        for v in values:
            # ───────── ① 小刻度：直接留空 ─────────
            if spacing < 1:  # << 只改這一行就行
                labels.append("")
                continue

            idx = int(round(v))  # 你的 x 座標本來就 0‥n-1
            if idx == last_idx or idx < 0 or idx >= len(self.times):
                labels.append("")
                continue

            labels.append(self.times[idx].strftime("%H:%M:%S"))
            last_idx = idx

        return labels

# ====================================================
# 趨勢圖畫布 (TrendCanvas)
# 使用 pyqtgraph 繪製趨勢圖，並支援區間選取
# ====================================================
class TrendCanvas(pg.PlotWidget):
    subrange_selected = pyqtSignal(int, int)
    view_all_requested = pyqtSignal()

    def __init__(self, parent=None, main_window=None, times=None):
        # 若有傳入 times 則建立自訂時間軸
        if times is not None:
            axis = TimeAxisItem(times, orientation='bottom')
            super().__init__(axisItems={'bottom': axis}, parent=parent)
        else:
            super().__init__(parent=parent)
        self.main_window = main_window
        self.setBackground('w')
        self.getPlotItem().showGrid(x=True, y=True, alpha=0.1)
        self.getPlotItem().setLabel('bottom', "資料索引")
        self.getPlotItem().setLabel('left', "數值")
        # 初始繪製趨勢線，預設筆劃寬度為 1
        self.plot_line = self.getPlotItem().plot(pen=pg.mkPen('b', width=2))
        self.downtime_regions = []
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.region_item = None
        self.dragging = False
        self.drag_start_x = 0
        self.x_data = None
        self.y_data = None
        self.df_length = 0
        self.current_field = None
        self._bar_items = []  # ← ① 初始化
        self._label_items = []

    def compute_gap_intervals(self, df: pd.DataFrame,
                              gap_sec: float = 20.0,
                              rest_sec: float = 900.0) -> tuple[list, list]:
        """
        回傳 (downtime_list, rest_list)
          downtime：gap_sec < Δt ≤ rest_sec           →  紅色
          rest   ：Δt > rest_sec                      →  綠色
        兩個 list 皆為 [(start_index, end_index), …]
        """
        if df.empty or "datetime" not in df.columns:
            return [], []
        times = df["datetime"].values.astype("datetime64[s]").astype(np.int64)
        dsec = np.diff(times)

        downtime, rest = [], []
        for i, sec in enumerate(dsec):
            if sec > rest_sec:
                rest.append((i, i + 1))
            elif sec > gap_sec:
                downtime.append((i, i + 1))
        return downtime, rest

    def contextMenuEvent(self, event):
        """
        在右鍵選單中增加「重製圖表」功能
        """
        vb = self.getPlotItem().getViewBox()
        if vb.menu is None:
            vb.menu = QMenu(self)

        action_reset_chart = QAction("重製圖表", self)
        action_reset_chart.triggered.connect(self.handle_view_all)

        # 移除重複的「重製圖表」項目
        for act in vb.menu.actions():
            if act.text() == "重製圖表":
                vb.menu.removeAction(act)

        actions = vb.menu.actions()
        if actions:
            vb.menu.insertAction(actions[0], action_reset_chart)
        else:
            vb.menu.addAction(action_reset_chart)

        vb.menu.exec_(event.globalPos())

    def handle_view_all(self):
        # 點擊重製圖表時，重新繪製全部資料
        if is_text_column(self.main_window.df[self.main_window.current_field]):
            self.plot_test_result_bar(self.main_window.df,
                                      field=self.main_window.current_field)
            return

        self.plot_trend(self.main_window.df, name=self.main_window.current_field)
        self.view_all_requested.emit()

    def plot_trend(self, df: pd.DataFrame, name: str = "Unknown"):
        vb = self.getPlotItem().getViewBox()
        vb.setMouseEnabled(x=True, y=True)

        # ───────────────── 前置清理 ─────────────────
        plotItem = self.getPlotItem()
        for ti in getattr(self, "_label_items", []):
            plotItem.removeItem(ti)
        self._label_items.clear()
        for it in self._bar_items:
            plotItem.removeItem(it)
        self._bar_items.clear()

        # 「測試結果」→ 直接畫長條圖
        if is_text_column(df[name]):
            self.plot_test_result_bar(df, field=name)
            return
        if df.empty or name not in df.columns:
            return

        # 若 clear() 把線刪掉就補回
        if self.plot_line not in plotItem.items:
            self.plot_line = plotItem.plot(pen=pg.mkPen('b', width=2))

        self.current_field = name
        total_points = len(df)
        slider_value = self.main_window.slider.value()
        max_points = max(10, int(total_points * slider_value / 100))

        # ───── 特例：剃補次數 ────────────────────────
        if name == "剃補次數":
            final_idx = np.linspace(0, total_points - 1, max_points,
                                    dtype=int) if total_points > max_points else \
                np.arange(total_points)
            sampled_times = df["datetime"].loc[final_idx].tolist()
            y = df[name].loc[final_idx].values
            x = np.arange(len(sampled_times))

            axis = TimeAxisItem(sampled_times, orientation='bottom')
            plotItem.setAxisItems({'bottom': axis})
            self.x_data, self.y_data, self.df_length = x, y, len(x)
            if self.plot_line not in plotItem.items:
                plotItem.addItem(self.plot_line)
            self.plot_line.setData(x, y)
            _setup_plot_looks(plotItem, title=f"{name} 趨勢圖")
            if len(x) > 1:
                plotItem.setXRange(x[0], x[-1], padding=0.02)
            print(f"✅ (剃補次數欄位) 繪製筆數：{len(final_idx)} / 原始：{total_points}")
            return
        # ────────────────────────────────────────────

        # ① 取得上下限
        default_lower, default_upper = df[name].min(), df[name].max()
        raw_LSL, raw_USL = self.main_window.config_manager.get_limits(
            name, self.main_window.get_current_model()
        )
        raw_LSL = default_lower if raw_LSL is None else raw_LSL
        raw_USL = default_upper if raw_USL is None else raw_USL
        if raw_USL <= raw_LSL:
            QMessageBox.warning(self, "設定錯誤", "上限必須大於下限，請重新設定！")
            return
        LSL, USL = raw_LSL, raw_USL

        # ② 判斷異常點
        is_outlier = (df[name] < LSL) | (df[name] > USL)
        outlier_idx = set(df[is_outlier].index.tolist())
        # ★★ NEW ★★  把每段 downtime 的 start / end 也列為強制保留
        mandatory_idx = set(outlier_idx)  # 先含異常點
        if getattr(self.main_window, "show_downtime_lines", False):
            gap_val = self.main_window.get_gap_threshold()
            rest_val = self.main_window.get_rest_threshold()

            downtimes, rests = self.compute_gap_intervals(df,
                                                          gap_sec=gap_val,
                                                          rest_sec=rest_val)

            for s_idx, e_idx in downtimes:  # ─ Downtime（紅）
                mandatory_idx.update((s_idx, e_idx))

            for s_idx, e_idx in rests:  # ─ Rest（綠） ← 新增這 2 行
                mandatory_idx.update((s_idx, e_idx))

        # ③ 抽稀策略：保留所有異常，再「等距」補滿
        available = max_points - len(mandatory_idx)
        if available > 0:
            normal_idx = sorted(set(df.index) - mandatory_idx)
            if normal_idx:
                lin_idx = np.linspace(0, len(normal_idx) - 1, available,
                                      dtype=int)
                sampled_normal_idx = [normal_idx[i] for i in lin_idx]
            else:
                sampled_normal_idx = []
        else:
            sampled_normal_idx = []
        final_idx = sorted(mandatory_idx | set(sampled_normal_idx))

        # ④ 將資料轉成畫圖所需座標
        sampled_times = df["datetime"].loc[final_idx].tolist()
        y = df[name].loc[final_idx].values
        x = np.arange(len(sampled_times))
        idx_to_x = {orig_idx: i for i, orig_idx in enumerate(final_idx)}
        axis = TimeAxisItem(sampled_times, orientation='bottom')
        plotItem.setAxisItems({'bottom': axis})
        self.x_data, self.y_data, self.df_length = x, y, len(x)

        self.plot_line.setData(x, y)

        # ⑤ 基本外觀
        _setup_plot_looks(plotItem, title=f"{name} 趨勢圖")
        for item in list(plotItem.items):
            if isinstance(item, pg.InfiniteLine) and item.angle == 0:
                plotItem.removeItem(item)
        plotItem.addItem(pg.InfiniteLine(pos=LSL, angle=0,
                                         pen=pg.mkPen('red', style=Qt.DashLine, width=3)))
        plotItem.addItem(pg.InfiniteLine(pos=USL, angle=0,
                                         pen=pg.mkPen('green', style=Qt.DashLine, width=3)))

        # ⑥ 停機 / 休息 區段 ----------------------------------------------
        for reg in self.downtime_regions:
            plotItem.removeItem(reg)
        self.downtime_regions.clear()

        if getattr(self.main_window, "show_downtime_lines", False):
            gap_val = self.main_window.get_gap_threshold()
            rest_val = self.main_window.get_rest_threshold()

            downtimes, rests = self.compute_gap_intervals(df,
                                                          gap_sec=gap_val,
                                                          rest_sec=rest_val)
            # ── Downtime：紅 ─────────────────────────────
            for s_idx, e_idx in downtimes:
                if s_idx in idx_to_x and e_idx in idx_to_x:
                    lft, rgt = idx_to_x[s_idx], idx_to_x[e_idx] or idx_to_x[s_idx] + 1
                    reg = pg.LinearRegionItem(values=[lft, rgt],
                                              orientation=pg.LinearRegionItem.Vertical,
                                              movable=False,
                                              brush=pg.mkBrush(255, 0, 0, 60))
                    for ln in reg.lines:
                        ln.setPen(pg.mkPen(255, 0, 0, width=1))
                    plotItem.addItem(reg)
                    self.downtime_regions.append(reg)

            # ── Rest：綠 ────────────────────────────────
            for s_idx, e_idx in rests:
                if s_idx in idx_to_x and e_idx in idx_to_x:
                    lft, rgt = idx_to_x[s_idx], idx_to_x[e_idx] or idx_to_x[s_idx] + 1
                    reg = pg.LinearRegionItem(values=[lft, rgt],
                                              orientation=pg.LinearRegionItem.Vertical,
                                              movable=False,
                                              brush=pg.mkBrush(0, 180, 0, 60))
                    for ln in reg.lines:
                        ln.setPen(pg.mkPen(0, 180, 0, width=1))
                    plotItem.addItem(reg)
                    self.downtime_regions.append(reg)
        # ------------------------------------------------------------------

        # ⑦ 異常標籤：改用「分箱 + 聚合」 --------------------------
        for t in getattr(self, "outlier_text_items", []):
            plotItem.removeItem(t)
        self.outlier_text_items = []

        from pyqtgraph import TextItem
        outlier_items = [
            {"x": x[i], "y": y[i],
             "time": df["datetime"].iloc[idx]}
            for i, idx in enumerate(final_idx) if idx in outlier_idx
        ]
        if not outlier_items:
            return

        # 7-1. 總量 >50 直接整包標示
        if len(outlier_items) > 50:
            _add_summary_label(plotItem, outlier_items, self.outlier_text_items)
            print(f"✅ 繪製筆數：{len(final_idx)} / 原始：{total_points}（含異常 {len(outlier_idx)} 筆）")
            return

        # 7-2. 依 x 像素分箱
        arr_x = np.array([it["x"] for it in outlier_items])
        arr_y = np.array([it["y"] for it in outlier_items])
        arr_t = np.array([it["time"] for it in outlier_items])
        bin_id = (arr_x // 5).astype(int)  # 每 5 像素一箱
        for b in np.unique(bin_id):
            mask = bin_id == b
            cnt = mask.sum()
            if cnt < 5:  # 交錯排版
                offset = ((np.arange(cnt) % 2) * 2 - 1) * (arr_y.max() - arr_y.min()) * 0.01
                for x0, y0, t0, dy in zip(arr_x[mask], arr_y[mask], arr_t[mask], offset):
                    anchor = (0.5, 1.2) if y0 > USL else (0.5, -0.2)
                    ti = TextItem(t0.strftime('%H:%M:%S'),
                                  color='red', anchor=anchor)
                    ti.setPos(x0, y0 + dy)
                    plotItem.addItem(ti);
                    self.outlier_text_items.append(ti)
            else:  # 聚合
                sub_x, sub_y, sub_t = arr_x[mask], arr_y[mask], arr_t[mask]
                _add_summary_label(plotItem,
                                   [{"x": sub_x.mean(), "y": sub_y.mean()}],
                                   self.outlier_text_items,
                                   cnt=cnt, tmin=sub_t.min(), tmax=sub_t.max())
        # ----------------------------------------------------------
        print(f"✅ 繪製筆數：{len(final_idx)} / 原始：{total_points}（含異常 {len(outlier_idx)} 筆）")

    def _setup_plot_looks(plotItem, *, title=""):
        plotItem.enableAutoRange(axis=pg.ViewBox.XYAxes)
        plotItem.setTitle(f"<span style='font-family:Microsoft JhengHei;color:black;'>{title}</span>")
        plotItem.showGrid(x=True, y=True, alpha=0.1)
        for ax in ('left', 'bottom'):
            plotItem.getAxis(ax).setTextPen(pg.mkPen('black'))
            plotItem.getAxis(ax).setPen(pg.mkPen('black'))

    def _add_summary_label(plotItem, items, lbl_store, *,
                           cnt=None, tmin=None, tmax=None):
        if cnt is None:  # 直接給一個列表 items
            cnt = len(items)
            xs = [it["x"] for it in items]
            ys = [it["y"] for it in items]
            ts = [it["time"] for it in items]
            x0, y0 = sum(xs) / cnt, sum(ys) / cnt
            tmin, tmax = min(ts), max(ts)
        else:  # 已算好
            x0, y0 = items[0]["x"], items[0]["y"]

        txt = f"{cnt} 異常<br>{tmin:%H:%M}–{tmax:%H:%M}"
        ti = pg.TextItem(txt, color='red', anchor=(0.5, 1.0))
        ti.setPos(x0, y0)
        plotItem.addItem(ti);
        lbl_store.append(ti)

    def compute_downtime_intervals(self, df: pd.DataFrame, gap_threshold: float = 20.0) -> list:
        """
        根據相鄰資料紀錄的時間間隔，計算停機區間。
        若間隔大於 gap_threshold 秒，則視為停機區間。
        回傳的列表形式為 [(start_index, end_index), ...]
        """
        if df.empty or "datetime" not in df.columns:
            return []
        times = df["datetime"].values.astype("datetime64[s]").astype(np.int64)
        intervals = np.diff(times)
        downtime_indices = np.where(intervals > gap_threshold)[0]
        return [(idx, idx + 1) for idx in downtime_indices]

    def mousePressEvent(self, event):
        if self.main_window.df is None or self.main_window.current_field is None:
            super().mousePressEvent(event)  # 換成 mouseMove / mouseRelease 就寫對應的
            return

        # ★ 如果是「測試結果」直接忽略框選功能
        if is_text_column(self.main_window.df[self.main_window.current_field]):
            super().mousePressEvent(event)  # 保留其他滑鼠行為（例如右鍵選單）
            return
        # 處理滑鼠左鍵按下時的開始區域選取
        if event.button() == Qt.LeftButton:
            self.dragging = True
            point_in_data_coords = self.getPlotItem().vb.mapSceneToView(event.pos())
            self.drag_start_x = point_in_data_coords.x()
            self.region_item = pg.LinearRegionItem(
                values=[self.drag_start_x, self.drag_start_x],
                orientation=pg.LinearRegionItem.Vertical,
                movable=False
            )
            self.region_item.setZValue(100)  # 設定區域層級較高
            self.region_item.setBrush(pg.mkColor(255, 0, 0, 50))
            self.getPlotItem().addItem(self.region_item)
            event.accept()
            return
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # ← 參數統一叫 event

        # ① 若尚未載入任何資料或欄位，直接交回 Qt
        if (self.main_window.df is None
                or self.main_window.current_field is None):
            super().mouseMoveEvent(event)
            return

        # ② 如果是「測試結果」欄位，不提供框選
        if is_text_column(self.main_window.df[self.main_window.current_field]):
            super().mouseMoveEvent(event)
            return

        # ③ 真的在拖曳時才更新區域
        if self.dragging and (event.buttons() & Qt.LeftButton):
            point = self.getPlotItem().vb.mapSceneToView(event.pos())
            current_x = point.x()
            left_x, right_x = sorted([self.drag_start_x, current_x])
            if self.region_item is not None:
                self.region_item.setRegion([left_x, right_x])
            event.accept()
            return

        # ④ 其它情形照原本流程
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.main_window.df is None or self.main_window.current_field is None:
            super().mouseReleaseEvent(event)  # 換成 mouseMove / mouseRelease 就寫對應的
            return

        if is_text_column(self.main_window.df[self.main_window.current_field]):
            super().mouseReleaseEvent(event)
            return
        # 完成選取區域後發射信號並清除區域標示
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            if self.region_item is not None:
                left_x, right_x = self.region_item.getRegion()
                start_idx = int(np.clip(round(left_x), 0, self.df_length - 1))
                end_idx = int(np.clip(round(right_x), 0, self.df_length - 1))
                if end_idx <= start_idx:
                    self.getPlotItem().removeItem(self.region_item)
                    self.region_item = None
                else:
                    self.getPlotItem().setXRange(start_idx, end_idx, padding=0)
                    self.subrange_selected.emit(start_idx, end_idx)
                    self.getPlotItem().removeItem(self.region_item)
                    self.region_item = None
            event.accept()
            return
        else:
            super().mouseReleaseEvent(event)

    def plot_test_result_bar(self, df: pd.DataFrame, field: str = "測試結果"):
        plotItem = self.getPlotItem()
        # ① 清除舊圖形
        plotItem.clear()
        self._bar_items.clear()
        self._label_items = []
        # ② 檢查資料
        if df.empty or field not in df.columns:
            return

        # ③ 先把字串欄位做標準化，再統計
        clean = normalize_str_col(df[field])
        uni, cnt = np.unique(clean.values, return_counts=True)
        order = sorted(range(len(uni)),
                       key=lambda i: (-cnt[i], str(uni[i]).upper()))
        cats = [uni[i] for i in order]
        counts = [cnt[i] for i in order]

        x = np.arange(len(cats))
        width = 0.8 if len(cats) <= 6 else 0.8 * 6 / len(cats)

        bar = pg.BarGraphItem(
            x=x,
            height=counts,
            width=width,
            brushes=make_brushes(cats),
            pen=pg.mkPen("black")
        )
        plotItem.addItem(bar)
        self._bar_items.append(bar)

        # ---------- ⑤ 在柱子頂端加「數量 / 百分比」 ----------
        total = sum(counts)
        y_off = max(counts) * 0.12  # 與柱子頂端留 2 % 空隙
        for xi, cnt_i in zip(x, counts):
            pct = cnt_i / total * 100
            html = (
                f"<div style='color:red; font-weight:bold; text-align:center;'>"
                f"{cnt_i}<br>{pct:.3f}%"
                f"</div>"
            )
            ti = pg.TextItem(html=html, anchor=(0.5, -0.1), color="black")
            ti.setPos(xi , cnt_i + y_off)
            plotItem.addItem(ti)
            self._label_items.append(ti)
        # ----------------------------------------------------

        plotItem.enableAutoRange(axis=pg.ViewBox.XAxis)
        plotItem.setYRange(0, max(counts) * 1.1, padding=0)  # 上留空
        plotItem.getViewBox().setMouseEnabled(x=False, y=False)  # 禁止意外拖動

        # ④ 座標軸與標題
        ticks = list(zip(x, cats))  # ← 先組 ticks
        axis = plotItem.getAxis('bottom')
        axis.setTicks([ticks])

        plotItem.setTitle(
            f"<span style='font-family:Microsoft JhengHei;'>{field} 長條圖</span>"
        )
        plotItem.showGrid(x=True, y=True, alpha=0.1)

        # ---------- 强制刷新轴与画布 ----------
        # 1) 通知轴更新
        axis.update()
        plotItem.getAxis('left').update()
        # 2) 通知整个 PlotWidget 重画
        plotItem.vb.update()
        plotItem.update()

        for ax in ('left', 'bottom'):
            plotItem.getAxis(ax).setTextPen(pg.mkPen('black'))
            plotItem.getAxis(ax).setPen(pg.mkPen('black'))

        self.main_window.result_order = cats

# ====================================================
# 主程式啟動函式
# 選擇資料夾、讀取最新檔案並建立應用程式實例
# ====================================================
def main():
    app = QApplication(sys.argv)
    # 啟用高 DPI 相關屬性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setStyle("Fusion")

    settings = QSettings("MyCompany", "MyApp")
    last_folder = settings.value("last_folder", "", type=str)

    # --- 使用「做法 A」：一直選到有檔案為止 ---
    folder_path = ask_folder_until_files(
        parent=None,
        init_path=last_folder if os.path.isdir(last_folder) else ""
    )

    if not folder_path:  # 使用者按了「取消」
        print("❌ 沒有選資料夾，程式結束")
        sys.exit(0)

    settings.setValue("last_folder", folder_path)  # 記住新的路徑
    settings.sync()

    # 同時搜尋 .txt、.csv、.log
    files = [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if f.lower().endswith((".txt", ".csv", ".log"))
           and os.path.isfile(os.path.join(folder_path, f))
    ]
    if not files:
        QMessageBox.warning(None, "錯誤", "該資料夾沒有 TXT、CSV 或 LOG 檔案")
        sys.exit(0)

    newest_file = max(files, key=os.path.getmtime)
    print("✅ 自動載入最新檔案：", newest_file)
    return app, newest_file

# ====================================================
# 主入口
# ====================================================
if __name__ == "__main__":
    import cProfile, pstats
    profiler = cProfile.Profile()
    profiler.enable()

    app, FILE_PATH = main()
    splash = SplashScreen()
    splash.show()
    app.processEvents()

    window = MainWindow(FILE_PATH)

    def show_main_and_stop_spinner():
        # 停止啟動畫面動畫，並顯示主視窗
        splash.spinner.timer.stop()
        splash.close()
        window.show()
    QTimer.singleShot(500, show_main_and_stop_spinner)

    ret = app.exec_()

    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats('time')
    stats.print_stats(10)
    sys.exit(ret)
