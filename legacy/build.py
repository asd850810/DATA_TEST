import os
import re
import subprocess
import platform
import shutil
import sys

MAIN_PY     = "main.py"
ICON_PATH   = "Data.ico"
VERSION_TXT = "version.txt"

def extract_version(filepath):
    """从主脚本提取 __version__ (格式 X.Y)"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(
        r"__version__\s*=\s*['\"](\d+\.\d+(?:\.\d+)?)['\"]",
        content
    )
    return m.group(1) if m else None

def generate_version_txt(product_name, version, output_path):
    """根据版本号生成 PyInstaller 需要的 version.txt"""
    major, minor, patch = version.split(".")
    version_parts = (int(major), int(minor), 0, 0)
    template = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_parts},
    prodvers={version_parts},
    mask=0x3f,
    flags=0x0,
    OS=0x4,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'MyCompany'),
          StringStruct('FileDescription', '{product_name}'),
          StringStruct('FileVersion', '{version}.0.0'),
          StringStruct('InternalName', '{product_name}'),
          StringStruct('LegalCopyright', 'Copyright © 2025'),
          StringStruct('OriginalFilename', '{product_name}.exe'),
          StringStruct('ProductName', '{product_name}'),
          StringStruct('ProductVersion', '{version}.0.0')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(template)
    print(f"✅ version.txt 已產生：{product_name} {version}")

def open_dist_folder():
    """打包完成后打开 dist 文件夹"""
    dist = os.path.abspath("dist")
    if platform.system() == "Windows":
        os.startfile(dist)
    elif platform.system() == "Darwin":
        subprocess.run(["open", dist])
    else:
        subprocess.run(["xdg-open", dist])

def sign_exe(exe_path):
    """
    可选：用 signtool 对 EXE 做数字签章，减少 SmartScreen 和 AV 误报。
    需安装 Windows 10 SDK，并在 PATH 或下方路径中找到 signtool.exe。
    """
    signtool = r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
    if not os.path.exists(signtool):
        print("⚠️ signtool.exe 未找到，跳过签名")
        return
    cmd = [
        signtool, "sign",
        "/a",
        "/fd", "SHA256",
        "/tr", "http://timestamp.digicert.com",
        "/td", "SHA256",
        exe_path
    ]
    print("🔐 开始对 EXE 签名…")
    subprocess.run(cmd, check=False)
    print("🔐 签名完成")

def build_exe():
    # 1. 提取版本号
    version = extract_version(MAIN_PY)
    if not version:
        print("❌ 无法从 main.py 提取 __version__")
        return

    exe_name = f"資料收集_{version}"
    product_name = exe_name

    # 2. 生成 version.txt
    generate_version_txt(product_name, version, VERSION_TXT)

    # 3. 清理旧的 dist 目录
    dist_dir = os.path.abspath("dist")
    if os.path.isdir(dist_dir):
        try:
            shutil.rmtree(dist_dir)
            print("✅ 已清除旧的 dist 目录")
        except Exception as e:
            print("⚠️ 无法删除 dist 目录，请关闭正在运行的 EXE：", e)

    # 4. 构造 PyInstaller 命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", exe_name,
        "--icon", ICON_PATH,
        "--version-file", VERSION_TXT,

        # 关闭 UPX，减少杀软误报
        "--noupx",

        # 精简打包体，剔除不必要的模块
        "--exclude-module", "tkinter",
        "--exclude-module", "test",
        "--exclude-module", "asyncio",
        # 不要排除 pydoc、unittest 等标准库
        MAIN_PY
    ]

    print("🚀 开始打包中…")
    subprocess.run(cmd, check=True)

    exe_path = os.path.join("dist", f"{exe_name}.exe")
    print(f"✅ 打包完成：{exe_path}")

    # 5. 可选：给 EXE 签名
    if platform.system() == "Windows":
        sign_exe(exe_path)

    # 6. 打开输出文件夹
    open_dist_folder()

if __name__ == "__main__":
    build_exe()
