# -*- coding: utf-8 -*-
import os
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from PyQt5.QtCore import QSettings
from src.core.constants import DEFAULT_GOOD, DEFAULT_BAD

def ask_folder_until_files(parent=None, init_path="") -> str:
    """
    持續要求使用者選擇資料夾，直到選中的資料夾內包含
    TXT, CSV, 或 LOG 檔案為止。
    """
    if init_path and os.path.isdir(init_path):
        if any(f.lower().endswith((".txt", ".csv", ".log")) and os.path.isfile(os.path.join(init_path, f)) for f in os.listdir(init_path)):
            return init_path

    while True:
        path = QFileDialog.getExistingDirectory(
            parent,
            "請選擇含有 TXT / CSV / LOG 檔的資料夾",
            init_path,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if not path:
            return ""

        if any(f.lower().endswith((".txt", ".csv", ".log")) and os.path.isfile(os.path.join(path, f)) for f in os.listdir(path)):
            return path

        QMessageBox.warning(
            parent, "沒有檔案",
            "這個資料夾沒有 TXT / CSV / LOG 檔，請重新選擇。"
        )
        init_path = path

def load_tags():
    """從 QSettings 讀取良品與不良品標籤"""
    st = QSettings("MyCompany", "MyApp")
    good = set(st.value("yield_tags/good", ",".join(DEFAULT_GOOD)).split(','))
    bad = set(st.value("yield_tags/bad", ",".join(DEFAULT_BAD)).split(','))
    return {w.strip().upper() for w in good if w.strip()}, \
           {w.strip().upper() for w in bad if w.strip()}

def save_tags(good_set, bad_set):
    """將良品與不良品標籤存入 QSettings"""
    st = QSettings("MyCompany", "MyApp")
    st.setValue("yield_tags/good", ",".join(sorted(good_set)))
    st.setValue("yield_tags/bad", ",".join(sorted(bad_set)))
    st.sync()