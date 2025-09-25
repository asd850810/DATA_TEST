# -*- coding: utf-8 -*-
import os
import re
import unicodedata
from datetime import datetime, timedelta

import pandas as pd
from PyQt5.QtCore import QThread, pyqtSignal
from pandas.api.types import is_numeric_dtype, is_string_dtype

# ====================================================
# TXT 檔案解析輔助函式
# ====================================================
prefix_pattern = re.compile(
    r'^(?P<datetime>\d{4}/\d{2}/\d{2},\d{2}:\d{2}:\d{2}),機種:(?P<model>\d+),\s*(?P<rest>.*)$'
)
kv_pattern = re.compile(
    r'(?P<key>[A-Za-z0-9_\u4e00-\u9fa5\s]+?)\s*[:=]\s*'
    r'(?P<val>[A-Za-z0-9_\u4e00-\u9fa5\.\+\-]+)'
)
new_line_pattern = re.compile(
    r'^\d+:'
    r'(?P<month>\d{2})/(?P<day>\d{2})\s+'
    r'(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})'
)

def parse_custom_datetime(s: str) -> datetime:
    try:
        date_part, time_part = s.split('_')
        date_obj = datetime.strptime(date_part, "%Y-%m-%d").date()
        hour_str, minute_str, second_str, frac_str = time_part.split('-')
        hour, minute = int(hour_str), int(minute_str)
        second_float = float(second_str) + float("0." + frac_str)
        dt = datetime(date_obj.year, date_obj.month, date_obj.day,
                      hour=hour, minute=minute, second=0)
        dt += timedelta(seconds=second_float)
        return dt
    except (ValueError, IndexError):
        return None

def normalize_str_col(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
         .str.strip()
         .str.replace('\u3000', '', regex=False)
         .str.replace('\ufeff', '', regex=False)
         .str.replace('（', '(', regex=False)
         .str.replace('）', ')', regex=False)
         .apply(lambda x: unicodedata.normalize('NFKC', x))
    )

def parse_line(line: str):
    line = line.strip()
    if not line:
        return {}

    m_old = prefix_pattern.match(line)
    if m_old:
        datetime_str = m_old.group("datetime")
        model_str = m_old.group("model")
        rest = m_old.group("rest").replace("CCD4量測", "")

        m_result = re.search(r"測試結果\s*[:=]\s*([A-Za-z0-9\u4e00-\u9fff]+)", rest, re.I)
        test_result = m_result.group(1).upper() if m_result else None
        if m_result:
            rest = rest.replace(m_result.group(0), "")

        found = kv_pattern.findall(rest)
        row = {"datetime": datetime_str, "機種": int(model_str) if model_str.isdigit() else model_str}
        if test_result:
            row["測試結果"] = test_result
        for key, val_str in found:
            key, val_str = key.strip(), val_str.strip()
            try:
                row[key] = float(val_str)
            except ValueError:
                row[key] = val_str
        return row

    m = new_line_pattern.match(line)
    if m:
        now = datetime.now()
        dt = datetime(
            year=now.year, month=int(m.group("month")), day=int(m.group("day")),
            hour=int(m.group("hour")), minute=int(m.group("minute")), second=int(m.group("second"))
        )
        rest = line[m.end():]
        m_result = re.search(r"測試結果\s*[:=]\s*(OK|NG)", rest, re.I)
        test_result = m_result.group(1).upper() if m_result else None
        if m_result:
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
# 資料管理類別 (DataManager)
# ====================================================
class DataManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.df = None
        self.product_category = None

    def load_data(self):
        if not os.path.isfile(self.file_path):
            print(f"指定的檔案不存在: {self.file_path}")
            return None

        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".csv":
            return self._load_csv_data()
        elif ext in (".txt", ".log"):
            return self._load_txt_data()
        else:
            print(f"不支援的檔案格式: {ext}")
            return None

    def _load_txt_data(self):
        try:
            with open(self.file_path, "r", encoding="big5") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                print(f"使用 utf-8 讀取時也發生錯誤: {e}")
                return None
        except Exception as e:
            print(f"读取 TXT 文件错误: {e}")
            return None

        data_rows = [row for row in (parse_line(line) for line in lines) if row]
        if not data_rows:
            return None

        df = pd.DataFrame(data_rows)
        df["datetime"] = pd.to_datetime(df["datetime"], format="%Y/%m/%d,%H:%M:%S", errors='coerce')
        df.dropna(subset=["datetime"], inplace=True)
        df.sort_values(by="datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)
        self.df = df
        return df

    def _load_csv_data(self):
        header_row = self._find_csv_header()

        with open(self.file_path, "r", encoding="big5", errors="ignore") as f:
            first_line = f.readline().strip()
            parts = first_line.split(',')
            if len(parts) > 7 and parts[6] == "產品類別":
                self.product_category = parts[7]
            else:
                self.product_category = "未知"

        for enc in ("utf-8-sig", "utf-8", "big5", "cp950", "latin-1"):
            try:
                df = pd.read_csv(self.file_path, skiprows=header_row, encoding=enc, engine="python", header=0)
                break
            except UnicodeDecodeError:
                continue
        else:
            return None

        df.rename(columns=lambda c: str(c).strip().lstrip('\ufeff'), inplace=True)
        self._process_datetime_columns(df)
        df.rename(columns={"Operaor": "Operator", "Test Result": "測試結果"}, inplace=True)
        df.drop(columns=[c for c in ("Number", "UID Code") if c in df.columns], inplace=True, errors="ignore")

        if "厚度計(A)檢測值" in df.columns:
            df["厚度計(A)檢測值"] = df["厚度計(A)檢測值"].astype(str).str.extract(r'([\d.]+)').astype(float)

        df.dropna(subset=["datetime"], inplace=True)
        df.sort_values("datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)

        if df.empty:
            return None

        self.df = df
        return df

    def _find_csv_header(self):
        try:
            with open(self.file_path, "rb") as f:
                first_lines = [f.readline() for _ in range(5)]
        except FileNotFoundError:
            return 0

        def looks_like_header(cols):
            cols = [c.strip().lower().lstrip('\ufeff') for c in cols]
            return "datetime" in cols or {"date", "time"}.issubset(cols) or "no." in cols or "test result" in cols

        for idx, raw in enumerate(first_lines):
            try:
                cols = raw.decode("latin-1", errors="ignore").split(',')
                if looks_like_header(cols):
                    return idx
            except:
                continue
        return 0

    def _process_datetime_columns(self, df):
        if {"Date", "Time"}.issubset(df.columns):
            df["datetime"] = pd.to_datetime(
                df["Date"].astype(str).str.strip() + " " + df["Time"].astype(str).str.strip().str.rstrip(':'),
                errors="coerce"
            )
            df.drop(columns=["Date", "Time"], inplace=True)
        elif "datetime" in df.columns:
            s = df["datetime"].astype(str).str.strip()
            if s.str.contains("_").any():
                df["datetime"] = s.apply(parse_custom_datetime)
            else:
                df["datetime"] = pd.to_datetime(s, format="%Y/%m/%d %H:%M:%S", errors="coerce")

# ====================================================
# 後台資料載入執行緒 (DataLoader)
# ====================================================
class DataLoader(QThread):
    data_loaded = pyqtSignal(object)

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.stop_requested = False

    def run(self):
        if self.stop_requested:
            return
        try:
            dm = DataManager(self.file_path)
            df = dm.load_data()
            self.data_loaded.emit(df)
        except Exception as e:
            print(f"資料載入失敗: {e}")
            self.data_loaded.emit(None)

def is_text_column(series: pd.Series) -> bool:
    if is_numeric_dtype(series):
        return False
    return is_string_dtype(series) or series.dtype == object