from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from .client import CaptchaChallenge, CourtClient
from .models import (
    QueryItem,
    STATUS_CAPTCHA_ERROR,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_INPUT_ERROR,
    STATUS_PENDING,
    STATUS_QUERYING,
    STATUS_WAITING_CAPTCHA,
)
from .parser import parse_batch_lines
from .renderer import render_result_png


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"
CAPTCHA_DIR = PROJECT_ROOT / ".runtime" / "mobile-captchas"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass
class MobileJob:
    id: str
    client: CourtClient
    items: list[QueryItem]
    current_item: QueryItem | None = None
    current_captcha: CaptchaChallenge | None = None
    message: str = "准备就绪"


class MobileQueryService:
    def __init__(
        self,
        client_factory: Callable[[], CourtClient] = CourtClient,
        output_dir: Path = RESULTS_DIR,
        captcha_dir: Path = CAPTCHA_DIR,
        render_result: Callable[[QueryItem, list[dict], Path, str], Path] = render_result_png,
        today: Callable[[], str] = lambda: date.today().isoformat(),
    ) -> None:
        self.client_factory = client_factory
        self.output_dir = output_dir
        self.captcha_dir = captcha_dir
        self.render_result = render_result
        self.today = today
        self.jobs: dict[str, MobileJob] = {}
        self.lock = threading.Lock()

    def start_job(self, text: str) -> dict:
        items = parse_batch_lines(text)
        job = MobileJob(str(uuid.uuid4()), self.client_factory(), items)
        with self.lock:
            self.jobs[job.id] = job
        if not items:
            job.message = "没有可查询的内容"
            return self._job_to_dict(job)
        self._fetch_next_captcha(job)
        return self._job_to_dict(job)

    def get_job(self, job_id: str) -> dict:
        return self._job_to_dict(self._get_job(job_id))

    def submit_captcha(self, job_id: str, code: str) -> dict:
        job = self._get_job(job_id)
        code = code.strip()
        if not code:
            job.message = "请输入验证码"
            return self._job_to_dict(job)
        if not job.current_item or not job.current_captcha:
            job.message = "当前没有等待验证码的查询"
            return self._job_to_dict(job)

        item = job.current_item
        captcha = job.current_captcha
        item.status = STATUS_QUERYING
        job.message = f"正在查询：{item.name}"
        try:
            result = job.client.search(item, captcha, code)
        except Exception as exc:
            item.status = STATUS_FAILED
            item.error = str(exc)
            job.message = str(exc)
            return self._job_to_dict(job)

        if result.error:
            item.status = STATUS_CAPTCHA_ERROR
            item.error = result.error
            job.message = result.error
            return self._job_to_dict(job)

        output_path = self.render_result(item, result.rows, self.output_dir, self.today())
        item.status = STATUS_DONE
        item.output_path = output_path
        item.error = None
        self._delete_captcha(captcha)
        job.current_item = None
        job.current_captcha = None
        job.message = f"已完成：{item.name}"
        self._fetch_next_captcha(job)
        return self._job_to_dict(job)

    def refresh_captcha(self, job_id: str) -> dict:
        job = self._get_job(job_id)
        if not job.current_item:
            job.message = "当前没有需要刷新验证码的查询"
            return self._job_to_dict(job)
        if job.current_captcha:
            self._delete_captcha(job.current_captcha)
        self._fetch_captcha_for(job, job.current_item)
        return self._job_to_dict(job)

    def captcha_path_for(self, filename: str) -> Path:
        return self._safe_child(self.captcha_dir, filename)

    def result_path_for(self, filename: str) -> Path:
        return self._safe_child(self.output_dir, filename)

    def _get_job(self, job_id: str) -> MobileJob:
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise KeyError("没有找到这次查询，请重新开始") from exc

    def _fetch_next_captcha(self, job: MobileJob) -> None:
        for item in job.items:
            if item.status == STATUS_PENDING:
                self._fetch_captcha_for(job, item)
                return
        job.current_item = None
        job.current_captcha = None
        if any(item.status == STATUS_DONE for item in job.items):
            job.message = "队列已完成"

    def _fetch_captcha_for(self, job: MobileJob, item: QueryItem) -> None:
        item.status = STATUS_QUERYING
        job.current_item = item
        job.message = f"正在获取验证码：{item.name}"
        try:
            captcha = job.client.fetch_captcha(self.captcha_dir, item.name)
        except Exception as exc:
            item.status = STATUS_FAILED
            item.error = str(exc)
            job.current_captcha = None
            job.message = str(exc)
            return
        item.status = STATUS_WAITING_CAPTCHA
        item.error = None
        job.current_captcha = captcha
        job.message = "请输入验证码"

    def _job_to_dict(self, job: MobileJob) -> dict:
        current_captcha = None
        if job.current_item and job.current_captcha:
            current_captcha = {
                "itemIndex": job.current_item.index,
                "name": job.current_item.name,
                "imageUrl": f"/captcha/{job.id}/{job.current_captcha.image_path.name}",
            }
        return {
            "id": job.id,
            "message": job.message,
            "items": [self._item_to_dict(item) for item in job.items],
            "currentCaptcha": current_captcha,
            "done": sum(1 for item in job.items if item.status == STATUS_DONE),
            "total": len(job.items),
        }

    def _item_to_dict(self, item: QueryItem) -> dict:
        output_url = f"/results/{item.output_path.name}" if item.output_path else None
        return {
            "index": item.index,
            "kind": "个人" if item.kind == "person" else "企业",
            "name": item.name,
            "cardNum": item.card_num,
            "status": item.status,
            "error": item.error,
            "outputUrl": output_url,
        }

    def _delete_captcha(self, captcha: CaptchaChallenge) -> None:
        try:
            captcha.image_path.unlink()
        except FileNotFoundError:
            pass

    def _safe_child(self, directory: Path, filename: str) -> Path:
        target = (directory / Path(filename).name).resolve()
        base = directory.resolve()
        if target.parent != base:
            raise ValueError("文件路径无效")
        return target


MOBILE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#1d5d8f">
  <link rel="manifest" href="/manifest.json">
  <title>被执行人查询助手</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #eaf1f7;
      --panel: #ffffff;
      --ink: #16324a;
      --muted: #637487;
      --line: #cfdbe7;
      --primary: #1d5d8f;
      --primary-dark: #164a73;
      --ok: #2f8f72;
      --warn: #a35b00;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", Arial, sans-serif;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      padding: calc(14px + env(safe-area-inset-top)) 16px 12px;
      background: rgba(234, 241, 247, .96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(14px);
    }
    h1 {
      margin: 0 0 10px;
      font-size: 23px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .notice {
      background: var(--primary);
      color: #fff;
      padding: 10px 12px;
      border-radius: 7px;
      font-weight: 700;
      font-size: 14px;
      line-height: 1.45;
    }
    main {
      max-width: 760px;
      margin: 0 auto;
      padding: 14px 12px 90px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 12px;
      box-shadow: 0 8px 20px rgba(20, 35, 60, .06);
    }
    h2 {
      margin: 0 0 10px;
      font-size: 17px;
      letter-spacing: 0;
    }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 11px;
      font: 16px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--ink);
      background: #f7fafc;
      outline: none;
    }
    textarea {
      min-height: 180px;
      resize: vertical;
      line-height: 1.5;
    }
    textarea:focus, input:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(29, 93, 143, .16);
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 12px;
    }
    button, .result-link {
      min-height: 44px;
      border: 0;
      border-radius: 7px;
      background: var(--primary);
      color: #fff;
      font-size: 16px;
      font-weight: 700;
      text-align: center;
      text-decoration: none;
      display: inline-grid;
      place-items: center;
      padding: 0 12px;
    }
    button.secondary {
      background: #607d8f;
    }
    button:disabled {
      opacity: .55;
    }
    .captcha-card {
      display: none;
    }
    .captcha-card.active {
      display: block;
    }
    .captcha-image {
      min-height: 92px;
      border: 1px dashed var(--line);
      border-radius: 7px;
      display: grid;
      place-items: center;
      margin: 10px 0;
      background: #f7fafc;
      overflow: hidden;
    }
    .captcha-image img {
      max-width: 100%;
      image-rendering: auto;
    }
    .meta {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 8px;
    }
    .status-bar {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
      background: rgba(255, 255, 255, .96);
      border-top: 1px solid var(--line);
      backdrop-filter: blur(14px);
    }
    .status-inner {
      max-width: 760px;
      margin: 0 auto;
      color: var(--muted);
      font-size: 14px;
    }
    .queue {
      display: grid;
      gap: 8px;
    }
    .row {
      border: 1px solid #e1e8ef;
      border-radius: 7px;
      padding: 10px;
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 10px;
      align-items: center;
      background: #fff;
    }
    .index {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: #e9f2f8;
      color: var(--primary-dark);
      font-weight: 800;
      font-size: 13px;
    }
    .name {
      font-weight: 800;
      margin-bottom: 3px;
      overflow-wrap: anywhere;
    }
    .sub {
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    .badge {
      min-width: 74px;
      text-align: center;
      border-radius: 999px;
      padding: 5px 8px;
      font-size: 12px;
      font-weight: 800;
      color: #fff;
      background: #607d8f;
    }
    .badge.done { background: var(--ok); }
    .badge.wait { background: var(--warn); }
    .badge.fail { background: var(--danger); }
    .result-link {
      margin-top: 8px;
      min-height: 36px;
      font-size: 14px;
    }
    @media (min-width: 700px) {
      main { padding-top: 18px; }
      .two-col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }
      .two-col section { margin-bottom: 0; }
    }
  </style>
</head>
<body>
  <header>
    <h1>被执行人查询助手</h1>
    <div class="notice">粘贴名单后自动识别个人/企业；验证码人工输入，其余自动完成。</div>
  </header>
  <main>
    <section>
      <h2>批量输入</h2>
      <p class="meta">一行一个对象。个人请包含姓名和 18 位身份证号；没有身份证号时按企业查询。</p>
      <textarea id="batchText" placeholder="在这里粘贴名单，一行一个"></textarea>
      <div class="actions">
        <button id="startBtn">开始查询</button>
        <button class="secondary" id="clearBtn">清空</button>
      </div>
    </section>
    <div class="two-col">
      <section class="captcha-card" id="captchaCard">
        <h2>验证码</h2>
        <p class="meta" id="captchaTitle">等待验证码</p>
        <div class="captcha-image" id="captchaImageBox"></div>
        <input id="captchaCode" autocomplete="off" autocapitalize="characters" placeholder="输入验证码">
        <div class="actions">
          <button id="submitBtn">提交本条</button>
          <button class="secondary" id="refreshBtn">换验证码</button>
        </div>
      </section>
      <section>
        <h2>查询队列</h2>
        <div class="queue" id="queue"></div>
      </section>
    </div>
  </main>
  <div class="status-bar"><div class="status-inner" id="statusText">准备就绪</div></div>
  <script>
    let jobId = null;
    const $ = (id) => document.getElementById(id);
    const statusText = $("statusText");
    const startBtn = $("startBtn");
    const submitBtn = $("submitBtn");
    const refreshBtn = $("refreshBtn");

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    }

    function setBusy(isBusy) {
      startBtn.disabled = isBusy;
      submitBtn.disabled = isBusy;
      refreshBtn.disabled = isBusy;
    }

    async function postJson(url, data) {
      setBusy(true);
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data || {})
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "请求失败");
        renderJob(payload);
      } catch (error) {
        statusText.textContent = error.message;
      } finally {
        setBusy(false);
      }
    }

    function badgeClass(status) {
      if (status === "已完成") return "done";
      if (status === "等待验证码" || status === "验证码错误") return "wait";
      if (status === "查询失败" || status === "输入错误") return "fail";
      return "";
    }

    function renderJob(job) {
      jobId = job.id;
      statusText.textContent = job.message + (job.total ? `（${job.done}/${job.total}）` : "");
      const queue = $("queue");
      queue.innerHTML = "";
      job.items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "row";
        const output = item.outputUrl ? `<a class="result-link" href="${item.outputUrl}" target="_blank">打开 PNG</a>` : "";
        row.innerHTML = `
          <div class="index">${item.index}</div>
          <div>
            <div class="name">${escapeHtml(item.name || "未命名")}</div>
            <div class="sub">${item.kind}${item.cardNum ? " · " + escapeHtml(item.cardNum) : ""}</div>
            ${item.error ? `<div class="sub">${escapeHtml(item.error)}</div>` : ""}
            ${output}
          </div>
          <div class="badge ${badgeClass(item.status)}">${item.status}</div>
        `;
        queue.appendChild(row);
      });
      const card = $("captchaCard");
      if (job.currentCaptcha) {
        card.classList.add("active");
        $("captchaTitle").textContent = `当前：${job.currentCaptcha.name}`;
        $("captchaImageBox").innerHTML = `<img src="${job.currentCaptcha.imageUrl}?t=${Date.now()}" alt="验证码">`;
        $("captchaCode").value = "";
        $("captchaCode").focus();
      } else {
        card.classList.remove("active");
        $("captchaImageBox").innerHTML = "";
      }
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    startBtn.addEventListener("click", () => {
      postJson("/api/jobs", { text: $("batchText").value });
    });
    $("clearBtn").addEventListener("click", () => {
      $("batchText").value = "";
      $("batchText").focus();
    });
    submitBtn.addEventListener("click", () => {
      if (!jobId) return;
      postJson(`/api/jobs/${jobId}/submit`, { code: $("captchaCode").value });
    });
    refreshBtn.addEventListener("click", () => {
      if (!jobId) return;
      postJson(`/api/jobs/${jobId}/refresh`, {});
    });
    $("captchaCode").addEventListener("keydown", (event) => {
      if (event.key === "Enter") submitBtn.click();
    });
  </script>
</body>
</html>
"""


MANIFEST_JSON = {
    "name": "被执行人查询助手",
    "short_name": "被执行查询",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#eaf1f7",
    "theme_color": "#1d5d8f",
}


SERVICE_WORKER_JS = """
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open("zxgk-mobile-v1").then((cache) => cache.addAll(["/"])));
});
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
"""


class MobileRequestHandler(BaseHTTPRequestHandler):
    server: "MobileHTTPServer"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self._send_text(MOBILE_HTML, "text/html; charset=utf-8")
            elif path == "/manifest.json":
                self._send_json(MANIFEST_JSON)
            elif path == "/service-worker.js":
                self._send_text(SERVICE_WORKER_JS, "application/javascript; charset=utf-8")
            elif path.startswith("/captcha/"):
                self._send_file(self.server.service.captcha_path_for(unquote(path.split("/")[-1])), "image/png")
            elif path.startswith("/results/"):
                self._send_file(self.server.service.result_path_for(unquote(path.split("/")[-1])), "image/png")
            elif path.startswith("/api/jobs/"):
                job_id = path.rstrip("/").split("/")[-1]
                self._send_json(self.server.service.get_job(job_id))
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "页面不存在")
        except Exception as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            data = self._read_json()
            if path == "/api/jobs":
                self._send_json(self.server.service.start_job(str(data.get("text", ""))))
            elif path.endswith("/submit") and path.startswith("/api/jobs/"):
                job_id = path.split("/")[-2]
                self._send_json(self.server.service.submit_captcha(job_id, str(data.get("code", ""))))
            elif path.endswith("/refresh") and path.startswith("/api/jobs/"):
                job_id = path.split("/")[-2]
                self._send_json(self.server.service.refresh_captcha(job_id))
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "接口不存在")
        except KeyError as exc:
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body or "{}")

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_error(HTTPStatus.NOT_FOUND, "文件不存在")
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)


class MobileHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], service: MobileQueryService) -> None:
        super().__init__(server_address, MobileRequestHandler)
        self.service = service


def server_config_from_env() -> tuple[str, int]:
    host = os.environ.get("ZXGK_HOST", DEFAULT_HOST)
    port_text = os.environ.get("ZXGK_PORT", str(DEFAULT_PORT))
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("ZXGK_PORT 必须是数字") from exc
    if port < 1 or port > 65535:
        raise ValueError("ZXGK_PORT 必须在 1 到 65535 之间")
    return host, port


def create_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> MobileHTTPServer:
    return MobileHTTPServer((host, port), MobileQueryService())


def local_network_url(port: int) -> str:
    ip = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
    except Exception:
        pass
    return f"http://{ip}:{port}"


def main() -> None:
    host, port = server_config_from_env()
    server = create_server(host, port)
    bound_host, bound_port = server.server_address
    print("手机网页服务已启动", flush=True)
    print(f"监听地址：{bound_host}:{bound_port}", flush=True)
    print(f"本机打开：http://127.0.0.1:{bound_port}", flush=True)
    print(f"iPhone 同 Wi-Fi 打开：{local_network_url(bound_port)}", flush=True)
    print("按 Ctrl+C 停止服务", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
