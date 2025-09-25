# -*- coding: utf-8 -*-
import os
import threading
from watchdog.events import FileSystemEventHandler

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
            try:
                current_modified_time = os.path.getmtime(self.file_path)
                if self.last_modified_time != current_modified_time:
                    self.last_modified_time = current_modified_time
                    update_event.set()
            except FileNotFoundError:
                # 檔案可能在監控期間被刪除
                print(f"檔案不存在: {self.file_path}")
                pass