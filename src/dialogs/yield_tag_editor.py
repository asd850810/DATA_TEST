# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QLabel, QInputDialog)
from src.core.utils import load_tags, save_tags

class YieldTagEditor(QDialog):
    """
    良品/不良品關鍵字編輯器。
    讓使用者可以新增、刪除、或移動用於良率計算的關鍵字。
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        initial_good, initial_bad = load_tags()
        self.good_tags = set(initial_good)
        self.bad_tags = set(initial_bad)

        self.setWindowTitle("良 / 不良 關鍵字設定")
        self.resize(400, 300)

        self.lst_good = QListWidget()
        self.lst_good.addItems(sorted(self.good_tags))
        self.lst_bad = QListWidget()
        self.lst_bad.addItems(sorted(self.bad_tags))

        # --- 按鈕 ---
        btn_add_good = QPushButton("新增 OK")
        btn_add_bad = QPushButton("新增 NG")
        btn_del_good = QPushButton("刪除 OK")
        btn_del_bad = QPushButton("刪除 NG")
        btn_flip = QPushButton("OK <-> NG")
        btn_ok = QPushButton("儲存並關閉")

        btn_add_good.clicked.connect(lambda: self._add_tag(self.lst_good, self.good_tags))
        btn_add_bad.clicked.connect(lambda: self._add_tag(self.lst_bad, self.bad_tags))
        btn_del_good.clicked.connect(lambda: self._del_tag(self.lst_good, self.good_tags))
        btn_del_bad.clicked.connect(lambda: self._del_tag(self.lst_bad, self.bad_tags))
        btn_flip.clicked.connect(self._flip_tag)
        btn_ok.clicked.connect(self._apply_and_close)

        # --- 版面 ---
        hn = QHBoxLayout()
        vl = QVBoxLayout()
        vl.addWidget(QLabel("GOOD (良品)"))
        vl.addWidget(self.lst_good)
        hn.addLayout(vl)

        vr = QVBoxLayout()
        vr.addWidget(QLabel("BAD (不良)"))
        vr.addWidget(self.lst_bad)
        hn.addLayout(vr)

        vb_btn = QVBoxLayout()
        for w in (btn_add_good, btn_add_bad, btn_del_good, btn_del_bad, btn_flip, btn_ok):
            vb_btn.addWidget(w)
        hn.addLayout(vb_btn)

        self.setLayout(hn)

    def _add_tag(self, lst_widget, tag_set):
        txt, ok = QInputDialog.getText(self, "新增標籤", "輸入關鍵字：")
        if ok and txt.strip():
            tag = txt.strip().upper()
            if tag not in self.good_tags and tag not in self.bad_tags:
                tag_set.add(tag)
                lst_widget.addItem(tag)

    def _del_tag(self, lst_widget, tag_set):
        for item in lst_widget.selectedItems():
            tag_set.discard(item.text())
            lst_widget.takeItem(lst_widget.row(item))

    def _flip_tag(self):
        # 從 good list 中選中的移到 bad
        for item in self.lst_good.selectedItems():
            tag = item.text()
            self.good_tags.discard(tag)
            self.bad_tags.add(tag)

        # 從 bad list 中選中的移到 good
        for item in self.lst_bad.selectedItems():
            tag = item.text()
            self.bad_tags.discard(tag)
            self.good_tags.add(tag)

        # 重新整理兩個列表
        self._refresh_lists()

    def _refresh_lists(self):
        self.lst_good.clear()
        self.lst_good.addItems(sorted(self.good_tags))
        self.lst_bad.clear()
        self.lst_bad.addItems(sorted(self.bad_tags))

    def _apply_and_close(self):
        save_tags(self.good_tags, self.bad_tags)
        # 通知主視窗更新
        if self.parent() and hasattr(self.parent(), 'yield_tags_changed'):
            self.parent().yield_tags_changed.emit()
        self.accept()