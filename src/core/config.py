# -*- coding: utf-8 -*-
from PyQt5.QtCore import QSettings

class ConfigManager:
    """
    用於讀取與寫入應用程式相關設定，例如量測上下限。
    """
    def __init__(self, company="MyCompany", app_name="MyApp"):
        self.settings = QSettings(company, app_name)

    def get_limits(self, field, model=None):
        """
        取得指定欄位與機種的上下限 (LSL/USL)。
        如果找不到特定機種的設定，會回退尋找共用設定。
        """
        # 優先找特定機種的設定
        if model:
            key_prefix = f"{model}_{field}"
            lsl = self.settings.value(f"field_limits/{key_prefix}/lsl", type=float)
            usl = self.settings.value(f"field_limits/{key_prefix}/usl", type=float)
            if lsl is not None and usl is not None:
                return (lsl, usl)

        # 找不到再找共用設定
        key_prefix = field
        lsl = self.settings.value(f"field_limits/{key_prefix}/lsl", type=float)
        usl = self.settings.value(f"field_limits/{key_prefix}/usl", type=float)

        # 若都沒有，回傳 None
        if lsl is None or usl is None:
            return None, None

        return (lsl, usl)


    def set_limits(self, field, lsl, usl, model=None):
        """
        設定指定欄位與機種的上下限 (LSL/USL)。
        """
        key_prefix = f"{model}_{field}" if model else field
        self.settings.setValue(f"field_limits/{key_prefix}/lsl", lsl)
        self.settings.setValue(f"field_limits/{key_prefix}/usl", usl)
        self.settings.sync()

    def get_value(self, key, default=None, value_type=None):
        """通用 getter"""
        if value_type:
            return self.settings.value(key, default, type=value_type)
        return self.settings.value(key, default)

    def set_value(self, key, value):
        """通用 setter"""
        self.settings.setValue(key, value)
        self.settings.sync()

    def get_all_limit_keys(self):
        """取得所有與上下限相關的設定鍵"""
        return [k for k in self.settings.allKeys() if k.startswith("field_limits/")]

    def remove_limit(self, key):
        """移除指定的上下限設定"""
        self.settings.remove(key)
        self.settings.sync()

    def get_result_colors(self):
        """讀取所有已儲存的結果顏色設定"""
        colors = {}
        for k in self.settings.allKeys():
            if k.startswith("result_colors/"):
                cat = k.split('/', 1)[1]
                colors[cat] = self.settings.value(k)
        return colors

    def set_result_color(self, category, color_name):
        """設定單一結果的顏色"""
        self.settings.setValue(f"result_colors/{category}", color_name)
        self.settings.sync()