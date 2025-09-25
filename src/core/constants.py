# -*- coding: utf-8 -*-

# ====================================================
# 全域共用常數
# ====================================================

# ---- 顏色對應 ----
DEFAULT_COLOR_MAP = {
    "OK":  "green",  "NG": "red",
    "OK1": "orange", "OK2": "blue",
    "NG1": "purple", "測試1": "gray"
}

# ---- 良品/不良品關鍵字 ----
DEFAULT_GOOD = {"OK", "PASS", "GOOD", "O.K", "(OK)", "ＯＫ"}
DEFAULT_BAD  = {"NG", "FAIL", "BAD", "ＮＧ", "(NG)"}