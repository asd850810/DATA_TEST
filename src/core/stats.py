# ====================================================
# 共用計算工具區（utils）
# ====================================================
from datetime import datetime
import numpy as np
import pandas as pd
from PyQt5.QtCore import QSettings

def _load_tags_from_qsettings():
    """
    從 QSettings 抓良/不良關鍵字
    找不到就退回 DEFAULT_GOOD / DEFAULT_BAD
    """
    st = QSettings("MyCompany", "MyApp")

    good = st.value("yield_tags/good", ",".join(DEFAULT_GOOD))
    bad  = st.value("yield_tags/bad",  ",".join(DEFAULT_BAD))

    good_set = {w.strip().upper() for w in str(good).split(',') if w.strip()}
    bad_set  = {w.strip().upper() for w in str(bad).split(',') if w.strip()}
    return good_set, bad_set

# ---------------- 共用小工具 ----------------
def _split_gaps(times, gap_sec: float, rest_sec: float):
    """
    把相鄰記錄的時間差 (gaps) 依大小劃分成
        1. run   : gap <= gap_sec                → 正常運行
        2. down  : gap_sec < gap <= rest_sec     → 一般停機
        3. rest  : gap >  rest_sec               → 休息時間
    傳回 (downtime_sec, rest_sec)
    """
    gaps = np.diff(times)
    downtime = gaps[(gaps > gap_sec) & (gaps <= rest_sec)].sum()
    resttime = gaps[gaps > rest_sec].sum()
    return float(downtime), float(resttime)
# -------- 稼動率、停機、休息 --------
def compute_util_down_rest(df: pd.DataFrame,
                           gap_sec: float = 20.0,
                           rest_sec: float = 900.0):  # 15 min 預設
    """
    回傳 (util%, downtime_sec, resttime_sec)
    util = (總時間 - downtime - resttime) / 總時間
    """
    if df.empty or "datetime" not in df.columns:
        return 0.0, 0.0, 0.0

    # 先把 datetime 轉成 int64 秒
    ts = df["datetime"].sort_values().values.astype("datetime64[s]").astype(np.int64)
    total = ts[-1] - ts[0]
    if total <= 0:
        return 0.0, 0.0, 0.0

    downtime, resttime = _split_gaps(ts, gap_sec, rest_sec)
    util = 100.0 * (total - downtime - resttime) / (total - resttime)
    return util, downtime, resttime
# -------- 機台 UPH --------
def compute_machine_uph(df: pd.DataFrame,
                        gap_sec: float = 20.0,
                        rest_sec: float = 900.0) -> float:   # ★ 多了 rest_sec
    """
    機台 UPH = 產出數 ÷ (運行時間小時)
    運行時間 = 總時間 − 停機時間 − 休息時間
    """
    if df.empty or "datetime" not in df.columns:
        return 0.0

    # 用新版 util / down / rest 的函式
    _, downtime, resttime = compute_util_down_rest(df, gap_sec, rest_sec)

    total_sec = (df["datetime"].iloc[-1] - df["datetime"].iloc[0]).total_seconds()
    run_sec   = total_sec - downtime - resttime
    return 0.0 if run_sec <= 0 else len(df) / (run_sec / 3600)

# -------- UPH（每小時產出） --------
def compute_uph(df: pd.DataFrame,
                gap_sec: float = 20.0,
                rest_sec: float = 900.0) -> float:
    """
    實際 UPH = 產出數 ÷ ((總時間 − 休息時間) / 3600)
    （停機時間算在分母，休息時間不算）
    """
    if df.empty or "datetime" not in df.columns:
        return 0.0

    ts = df["datetime"].sort_values().values.astype("datetime64[s]").astype(np.int64)
    total = ts[-1] - ts[0]
    if total <= 0:
        return 0.0

    # 只需要抓休息秒數
    _, _, resttime = compute_util_down_rest(df, gap_sec, rest_sec)

    eff_sec = total - resttime            # 分母：總時間扣休息
    return 0.0 if eff_sec <= 0 else len(df) / (eff_sec / 3600)

# -------- 良率自動偵測 --------
from src.core.constants import DEFAULT_GOOD, DEFAULT_BAD


def compute_yield(df: pd.DataFrame,
                  good_tags: set[str] | None = None,
                  bad_tags: set[str] | None = None) -> float:
    """依良/不良關鍵字計算良率 (%)，若未傳入則自動讀 QSettings。"""

    # ① 如果呼叫方沒給，就分別補上
    if good_tags is None or bad_tags is None:
        auto_good, auto_bad = _load_tags_from_qsettings()
        good_tags = good_tags or auto_good
        bad_tags = bad_tags or auto_bad

    # ② 確保都是 set（呼叫端就算給 list 也可）
    good_tags = {t.upper().strip() for t in good_tags}
    bad_tags = {t.upper().strip() for t in bad_tags}

    # ③ 空表直接回傳 0
    if df.empty:
        return 0.0

    # ④ 找出第一個字串欄來判斷良/不良
    for col in df.columns:
        if df[col].dtype == object:
            vals = df[col].astype(str).str.upper().str.strip()
            good = vals.isin(good_tags).sum()
            bad = vals.isin(bad_tags).sum()
            if good + bad:
                return 100.0 * good / (good + bad)

    # ⑤ 找不到任何「含良/不良關鍵字」的欄位，就回 0
    return 0.0


def get_basic_stats(df: pd.DataFrame,
                    gap_sec:  float = 20.0,
                    rest_sec: float = 900.0):
    if df.empty: return {}

    uph_val = compute_uph(df, gap_sec, rest_sec)
    util_val, downtime_val, rest_val = compute_util_down_rest(df, gap_sec, rest_sec)
    total_sec = (df["datetime"].iloc[-1] - df["datetime"].iloc[0]).total_seconds()
    run_sec   = total_sec - downtime_val - rest_val
    machine_uph = compute_machine_uph(df, gap_sec, rest_sec)

    def mm_ss(sec): return divmod(int(sec), 60)  # (mm, ss)

    return dict(
        uph          = uph_val,
        util         = util_val,
        downtime     = downtime_val,
        resttime     = rest_val,
        total_sec    = total_sec,
        run_sec      = run_sec,
        machine_uph  = machine_uph,
        boot_mmss    = mm_ss(total_sec),
        run_mmss     = mm_ss(run_sec),
        down_mmss    = mm_ss(downtime_val),
        rest_mmss    = mm_ss(rest_val),
    )