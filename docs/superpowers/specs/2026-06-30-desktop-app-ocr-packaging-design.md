# 桌面 APP 化 + 验证码自动识别 设计文档

日期：2026-06-30
状态：待评审

## 1. 背景与现状

`zxgk_tool` 已经是一个基于 tkinter 的 macOS 桌面 GUI（`zxgk_tool/app.py` 的 `ZxgkApp`）。
当前流程：粘贴名单 → 自动识别个人/企业 → 抓验证码 → **人工输入验证码** → 自动查询 →
把结果渲染成 PNG **自动写入 `results/` 目录**。

启动方式目前依赖项目自带的 `.venv`（Python 3.14）+ `run_app.py`，或双击
`启动被执行人查询助手.command`。普通用户需要有 Python 环境才能跑。

关键现状（影响设计）：最近的提交「Reuse captcha across batch queries」让
**一整批名单只需要通过一次验证码**——第一条查询成功后，同一个已验证的验证码会
复用到本批后续所有条目（见 `app.py` 的 `_handle_search_done`）。
因此自动识别**只需攻破每批的第一张验证码**。

## 2. 目标

1. 把程序打包成 **macOS `.app`**，双击即用，使用者无需安装 Python。
2. 验证码**本地自动识别**（ddddocr），识别错误自动重试，连续失败才回退人工输入。
3. 结果不再自动落盘到 `results/`，改为**用户主动点「保存结果」自行选位置保存**。

## 3. 非目标（Out of scope）

- Windows / Linux 打包（本次只做 macOS）。
- 付费打码平台接入。
- 代码签名 + 公证（仅在文档中说明手动绕过 Gatekeeper 的方法）。
- 手机网页版（`mobile.py`）、Docker 部署不在本次改动范围。

## 4. 已确认的决策

| 决策项 | 取值 |
| --- | --- |
| 打包目标平台 | 仅 macOS（arm64） |
| 验证码方案 | 本地 ddddocr + 人工兜底 |
| 结果输出 | 不自动落盘；点「保存结果」弹原生保存框，用户自选位置 |
| OCR 重试上限 | 5 次（连续 5 次失败回退人工） |
| 「自动识别验证码」开关 | 默认开 |
| 打包构建环境 | 独立 Python 3.12 venv（绕开 3.14 装不上 onnxruntime 的问题） |

## 5. Part A：验证码自动识别

### 5.1 新模块 `zxgk_tool/ocr.py`

- `class CaptchaSolver`：懒加载 `ddddocr.DdddOcr(show_ad=False)`（首次调用才加载模型，约 0.5s）。
- `predict(image_path: Path) -> str`：调用 ddddocr，对原始结果做清洗（去掉非字母数字字符、统一大小写）。zxgk 验证码为 4 位字母/数字。
- 模型加载/识别全部在调用方的后台线程里发生，不阻塞 UI。

### 5.2 流程改动（`app.py`）

复用现有的 `events` 队列 + worker 线程机制，最小改动：

1. `_fetch_captcha_worker` 抓到验证码图后，**顺带跑一次 OCR**，把预测值随
   `captcha_ready` 事件一起传回（payload 增加 `predicted` 字段）。
2. `_handle_captcha_ready`：
   - 若「自动识别」开关开 且 有预测值 → 自动把预测值填入输入框并**自动提交**，
     同时 `auto_attempts += 1`。
   - 否则 → 维持现状，显示图片等人工输入。
3. `_handle_search_done` 收到「验证码错误」时：
   - 若自动模式 且 `auto_attempts < 5` → 自动换一张验证码重试（`refresh` + 重新 OCR + 自动提交）。
   - 若 `auto_attempts >= 5` → **回退人工**：停止自动、显示验证码图片、聚焦输入框、提示用户手动输入。
4. 第一条查询成功后，验证码已验证，沿用现有复用逻辑跑完整批，`auto_attempts` 归零。

### 5.3 UI 改动

- 在「验证码」面板加一个复选框「自动识别验证码」（`tk.BooleanVar`，默认 `True`）。
- 关掉开关 = 回到当前纯人工流程。

### 5.4 判定逻辑可测性

把「下一步该自动重试 / 回退人工 / 成功」的决策抽成一个**纯函数**
（输入：是否自动模式、attempts、上一次结果是否验证码错误；输出：动作枚举），
便于单测，不依赖 tkinter 和线程。

## 6. Part B：打包成 macOS `.app`

### 6.1 构建工具与环境

- 用 **PyInstaller**（`--windowed`），产出 `被执行人查询助手.app`。
- **用独立的 Python 3.12 venv（`.venv-build`）构建**。打包出的 `.app` 自带一份 Python，
  与开发机上的 3.14 完全独立，互不影响。
- 仓库提交：
  - `build_app.sh`：创建/复用 `.venv-build`、装依赖、调用 PyInstaller。
  - `zxgk_tool.spec`：PyInstaller 规格文件（含 ddddocr 数据/二进制收集）。
- ddddocr 的 `.onnx` 模型需打进包内：`--collect-all ddddocr`（必要时为 onnxruntime
  补 `--collect-binaries onnxruntime` / hiddenimports）。

### 6.2 可写路径处理（`zxgk_tool/paths.py`）

因为「结果改为用户主动保存」，**结果目录问题直接消失**，只剩验证码临时图需要可写目录：

- 新增 `paths.py`，提供 `captcha_dir()`：
  - 打包态（`getattr(sys, "frozen", False)` 为真）→ 返回系统临时目录下的子目录
    （`tempfile.gettempdir()/zxgk_captchas`）。
  - 开发态 → 维持现状 `PROJECT_ROOT/.runtime/captchas`。
- `app.py` 改用 `paths.captcha_dir()` 取代写死的 `CAPTCHA_DIR`。

### 6.3 Gatekeeper 说明（写进 README）

未签名 `.app` 首次打开会被拦截。自用方法：右键 →「打开」，或
`xattr -dr com.apple.quarantine 被执行人查询助手.app`。仅在需要分发给多人时才考虑
Apple Developer ID 签名 + 公证（99 美元/年），本次不做。

## 7. Part C：结果保存改为手动下载

### 7.1 行为变化

- 查询完成后**不再自动写 `results/`**。
- 渲染出的 PNG 先写到**临时目录**（复用现有 `render_result_png` /
  `render_batch_result_png`，把 `output_dir` 指向 tempdir），路径记在内存里。
- 「查询队列」面板下方加「保存结果」按钮：队列完成后可用，点击弹
  `tkinter.filedialog.asksaveasfilename`（默认文件名沿用现有命名），把临时 PNG
  复制到用户选定位置。
- 单条查询保存单图；批量（>2 条）保存汇总图，与现有渲染规则一致。

### 7.2 影响

- renderer 模块**无需改动**（只改 `output_dir` 指向 + 新增保存按钮逻辑）。
- 现有 `results/` 目录不再被程序写入（保留也无妨）。

## 8. 测试

- **`ocr.py`**：用样本验证码图测试 `predict` 返回 4 位字符；用 mock predictor 测清洗逻辑。
- **重试/兜底判定纯函数**：单测覆盖「自动成功 / 自动重试 / 达到 5 次回退人工 / 开关关闭走人工」。
- **保存流程**：单测「临时 PNG → 复制到目标路径」的拷贝函数（filedialog 部分手动验证）。
- **打包冒烟测试（手动）**：`build_app.sh` 出包 → 双击启动 → 查 1 条 → 点保存 →
  确认 PNG 落到选定位置。

## 9. 风险与对策

| 风险 | 对策 |
| --- | --- |
| Python 3.14 装不上 onnxruntime/ddddocr | 用独立 3.12 venv 构建；`.app` 自包含，不影响开发机 |
| ddddocr 对 zxgk 验证码识别率不够 | 每批只需破第一张 + 5 次重试，命中率足够；连续失败回退人工 |
| PyInstaller 漏收 onnxruntime 二进制/模型 | `.spec` 显式 `collect-all ddddocr` + 冒烟测试验证 |
| 未签名 .app 被 Gatekeeper 拦 | README 写明右键打开 / xattr 去隔离 |

## 10. 交付物清单

- `zxgk_tool/ocr.py`（新）
- `zxgk_tool/paths.py`（新）
- `zxgk_tool/app.py`（改：自动识别流程、开关、保存按钮、临时目录）
- `build_app.sh`、`zxgk_tool.spec`（新）
- `requirements.txt` / 构建依赖（加 ddddocr；构建依赖含 pyinstaller）
- `README.md`（更新：打包步骤、Gatekeeper 说明、结果改为手动保存）
- 对应单元测试
