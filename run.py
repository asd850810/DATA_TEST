# -*- coding: utf-8 -*-
import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer, Qt

from src.core.utils import ask_folder_until_files
from src.core.config import ConfigManager
from src.main_window import MainWindow
from src.widgets.spinner import SplashScreen

def main():
    """
    應用程式主進入點。
    """
    # --- 應用程式基本設定 ---
    app = QApplication(sys.argv)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setStyle("Fusion")

    config = ConfigManager()
    last_folder = config.get_value("last_folder", "")

    # --- 選擇資料夾 ---
    folder_path = ask_folder_until_files(init_path=last_folder)
    if not folder_path:
        sys.exit(0)
    config.set_value("last_folder", folder_path)

    # --- 尋找最新檔案 ---
    try:
        files = [p for p in Path(folder_path).iterdir() if p.is_file() and p.suffix.lower() in ['.txt', '.csv', '.log']]
        if not files:
            QMessageBox.warning(None, "沒有檔案", "此資料夾中沒有 TXT, CSV, 或 LOG 檔案。")
            sys.exit(0)
        newest_file = max(files, key=lambda p: p.stat().st_mtime)
    except Exception as e:
        QMessageBox.critical(None, "錯誤", f"無法讀取資料夾或檔案：\n{e}")
        sys.exit(1)

    # --- 啟動畫面與主視窗 ---
    splash = SplashScreen()
    splash.show()
    app.processEvents()

    main_window = MainWindow(str(newest_file))

    def show_main_and_close_splash():
        splash.spinner.timer.stop()
        splash.close()
        main_window.show()

    QTimer.singleShot(500, show_main_and_close_splash)

    sys.exit(app.exec_())

if __name__ == "__main__":
    from pathlib import Path
    main()