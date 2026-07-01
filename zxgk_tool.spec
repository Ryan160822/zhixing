# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for _pkg in ("ddddocr", "onnxruntime"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="被执行人查询助手",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="被执行人查询助手",
)
app = BUNDLE(
    coll,
    name="被执行人查询助手.app",
    icon=None,
    bundle_identifier="com.zxgk.tool",
)
