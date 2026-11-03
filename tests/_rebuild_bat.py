"""重写 start.bat（CRLF 行尾）并实测。

背景：cmd.exe 只认 CRLF，LF-only 的 bat 会读错行、报"不是内部或外部命令"。
本脚本用 Python 精确控制编码与行尾，避免 Write 工具默认写 LF。
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, "start.bat")
PROBE_DIR = os.path.join(ROOT, "tests")

PY_WB = r"C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"

BAT_LINES = [
    '@echo off',
    'chcp 65001 >nul',
    'cd /d %~dp0',
    'title Hanfeng Novel Studio',
    '',
    'REM ---------- 找 Python ----------',
    'set "PY=' + PY_WB + '"',
    'if exist "%PY%" goto probe',
    'set "PY=python"',
    'where python >nul 2>&1',
    'if "%errorlevel%"=="0" goto probe',
    '',
    'echo.',
    'echo  [错误] 找不到 Python，无法启动工作台。',
    'echo  已尝试: WorkBuddy 自带 Python、以及 PATH 中的 python',
    'echo.',
    'pause',
    'exit /b 1',
    '',
    'REM ---------- 探活 ----------',
    ':probe',
    '"%PY%" -c "import urllib.request;urllib.request.urlopen(\'http://127.0.0.1:8787/api/health\',timeout=2)" >nul 2>&1',
    'if "%errorlevel%"=="0" goto up',
    '',
    'echo.',
    'echo   寒峰小说工作台    http://127.0.0.1:8787',
    'echo.',
    'echo  [未运行] 正在启动服务，页面会自动弹出...',
    'echo  这个窗口要留着，关掉它服务就停了。',
    'echo.',
    '"%PY%" server.py',
    'pause',
    'exit /b 0',
    '',
    'REM ---------- 已在运行 ----------',
    ':up',
    'echo.',
    'echo   寒峰小说工作台    http://127.0.0.1:8787',
    'echo.',
    'echo  [已在运行] 直接打开页面...',
    'start "" "http://127.0.0.1:8787/"',
    'pause',
    'exit /b 0',
]


def write_bat(path, lines, eol):
    data = (eol.join(lines) + eol).encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return data


def run_probe(lines, eol, tag):
    """去掉 start / pause 后交给 cmd.exe 真跑一遍，看真实输出。"""
    stripped = [
        "# " + ln if ln.strip().startswith(("start ", "pause")) else ln
        for ln in lines
    ]
    path = os.path.join(PROBE_DIR, "_probe_%s.bat" % tag)
    write_bat(path, stripped, eol)
    try:
        r = subprocess.run(
            ["cmd", "/c", path], capture_output=True, input=b"\r\n",
            timeout=20, cwd=ROOT,
        )
    except subprocess.TimeoutExpired:
        return "%-22s 卡死（>%ds 跑不完）" % (tag, 20)
    txt = (r.stdout or b"").decode("gbk", "replace") + (r.stderr or b"").decode("gbk", "replace")
    keep = [ln for ln in txt.splitlines() if ln.strip()]
    body = "  |  ".join(keep) if keep else "(无输出)"
    return "%-22s exit=%d  %s" % (tag, r.returncode, body)


print("=== 1. 写正式 start.bat（CRLF / UTF-8 无 BOM）===")
data = write_bat(BAT, BAT_LINES, "\r\n")
print("  CRLF=%d  LF=%d  BOM=%s  字节=%d"
      % (data.count(b"\r\n"), data.count(b"\n"), data[:3] == b"\xef\xbb\xbf", len(data)))

print()
print("=== 2. 实测对比（已摘掉 start/pause，服务在跑）===")
print(run_probe(BAT_LINES, "\r\n", "crlf_新"))
print(run_probe(BAT_LINES, "\n", "lf_旧行尾"))

print()
print("=== 3. 清理探测文件 ===")
for f in os.listdir(PROBE_DIR):
    if f.startswith(("_probe_", "_run_probe")) and f.endswith(".bat"):
        os.remove(os.path.join(PROBE_DIR, f))
        print("  已删", f)
