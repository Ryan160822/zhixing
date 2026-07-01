from __future__ import annotations

import queue
import shutil
import threading
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

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
from . import paths
from .ocr import (
    AUTO_SUBMIT,
    MAX_AUTO_ATTEMPTS,
    CaptchaSolver,
    decide_captcha_action,
    should_auto_attempt,
)
from .renderer import render_batch_result_png, render_result_png


class ZxgkApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("被执行人批量查询助手")
        self.geometry("1180x760")
        self.minsize(980, 680)
        self.configure(bg="#eaf1f7")

        self.client = CourtClient()
        self.items: list[QueryItem] = []
        self.current_item: QueryItem | None = None
        self.current_captcha: CaptchaChallenge | None = None
        self.batch_output_path: Path | None = None
        self.captcha_photo: ImageTk.PhotoImage | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.solver = CaptchaSolver()
        self.auto_var = tk.BooleanVar(value=True)
        self.auto_attempts = 0
        self.output_paths: list[Path] = []
        self.current_predicted: str | None = None

        self._build_ui()
        self.bind("<Command-r>", lambda _event: self.refresh_captcha())
        self.after(100, self._process_events)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        style = ttk.Style(self)
        style.configure("App.TFrame", background="#eaf1f7")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#eaf1f7", foreground="#16324a")
        style.configure("Section.TLabel", background="#ffffff", foreground="#16324a")
        style.configure("Status.TLabel", background="#ffffff", foreground="#4d6073")

        header = ttk.Frame(self, padding=(18, 16, 18, 12), style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="被执行人批量查询助手",
            font=("PingFang SC", 23, "bold"),
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        notice = tk.Frame(header, bg="#1d5d8f", highlightthickness=0)
        notice.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        notice.columnconfigure(0, weight=1)
        tk.Label(
            notice,
            text="粘贴名单后自动识别个人/企业；验证码人工输入，其余自动完成。",
            bg="#1d5d8f",
            fg="#ffffff",
            font=("PingFang SC", 13, "bold"),
            padx=14,
            pady=9,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        main = tk.Frame(self, bg="#eaf1f7")
        main.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        main.columnconfigure(0, weight=2, minsize=360)
        main.columnconfigure(1, weight=3, minsize=540)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, padding=14, style="Panel.TFrame")
        right = ttk.Frame(main, padding=14, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="批量输入", font=("PingFang SC", 15, "bold"), style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.input_text = tk.Text(
            left,
            height=14,
            wrap="word",
            font=("Menlo", 13),
            bg="#f7fafc",
            fg="#16324a",
            insertbackground="#1d5d8f",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#cfdae6",
            highlightcolor="#1d5d8f",
        )
        self.input_text.grid(row=1, column=0, sticky="nsew", pady=(8, 10))

        buttons = ttk.Frame(left)
        buttons.grid(row=2, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(buttons, text="开始查询", command=self.start_queue)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="清空", command=self.clear_input).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        captcha_box = ttk.LabelFrame(left, text="验证码", padding=10)
        captcha_box.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        captcha_box.columnconfigure(0, weight=1)
        self.current_label_var = tk.StringVar(value="当前没有等待验证码的查询")
        ttk.Label(captcha_box, textvariable=self.current_label_var).grid(row=0, column=0, sticky="w")
        self.captcha_label = ttk.Label(captcha_box, text="验证码会显示在这里", anchor="center")
        self.captcha_label.grid(row=1, column=0, sticky="ew", pady=10)
        self.captcha_entry = ttk.Entry(captcha_box, font=("Menlo", 18))
        self.captcha_entry.grid(row=2, column=0, sticky="ew")
        self.captcha_entry.bind("<Return>", lambda _event: self.submit_captcha())
        captcha_actions = ttk.Frame(captcha_box)
        captcha_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        captcha_actions.columnconfigure(0, weight=1)
        captcha_actions.columnconfigure(1, weight=1)
        ttk.Button(captcha_actions, text="提交本条 (Enter)", command=self.submit_captcha).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(captcha_actions, text="换验证码 (Cmd+R)", command=self.refresh_captcha).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.auto_check = ttk.Checkbutton(captcha_box, text="自动识别验证码", variable=self.auto_var)
        self.auto_check.grid(row=4, column=0, sticky="w", pady=(8, 0))

        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="查询队列", font=("PingFang SC", 15, "bold"), style="Section.TLabel").grid(row=0, column=0, sticky="w")
        columns = ("index", "kind", "name", "card", "status", "output")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", height=18)
        self.tree.heading("index", text="序号")
        self.tree.heading("kind", text="类型")
        self.tree.heading("name", text="名称")
        self.tree.heading("card", text="身份证号/代码")
        self.tree.heading("status", text="状态")
        self.tree.heading("output", text="输出")
        self.tree.column("index", width=55, anchor="center")
        self.tree.column("kind", width=70, anchor="center")
        self.tree.column("name", width=180)
        self.tree.column("card", width=180)
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("output", width=260)
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(8, 10))

        self.status_var = tk.StringVar(value="准备就绪")
        ttk.Label(right, textvariable=self.status_var, style="Status.TLabel").grid(row=2, column=0, sticky="ew")
        self.save_button = ttk.Button(right, text="保存结果", command=self.save_results, state="disabled")
        self.save_button.grid(row=3, column=0, sticky="w", pady=(8, 0))

    def clear_input(self) -> None:
        if self.busy:
            messagebox.showinfo("正在查询", "查询进行中，暂时不能清空。")
            return
        self.input_text.delete("1.0", tk.END)

    def start_queue(self) -> None:
        if self.busy:
            return
        self.items = parse_batch_lines(self.input_text.get("1.0", tk.END))
        self.current_item = None
        self.current_captcha = None
        self.batch_output_path = None
        self.auto_attempts = 0
        self.output_paths = []
        self._update_save_button()
        self._render_queue()
        if not self.items:
            self.status_var.set("没有可查询的内容")
            return
        self.status_var.set(f"已载入 {len(self.items)} 条，开始查询")
        self._advance_queue()

    def _advance_queue(self) -> None:
        if self.busy:
            return
        for item in self.items:
            if item.status == STATUS_PENDING:
                self.current_item = item
                self._fetch_captcha_for(item)
                return
        self._finish_batch_output_if_ready()
        self.current_label_var.set("队列已完成")
        self.captcha_label.configure(image="", text="没有等待验证码的查询")
        if not self.batch_output_path:
            self.status_var.set("队列已完成")

    def _fetch_captcha_for(self, item: QueryItem) -> None:
        self.busy = True
        item.status = STATUS_QUERYING
        self._render_queue()
        self.status_var.set(f"正在获取验证码：{item.name}")
        threading.Thread(target=self._fetch_captcha_worker, args=(item,), daemon=True).start()

    def _fetch_captcha_worker(self, item: QueryItem) -> None:
        try:
            challenge = self.client.fetch_captcha(paths.captcha_dir(), item.name)
            predicted = None
            if self.auto_var.get():
                try:
                    predicted = self.solver.predict(challenge.image_path)
                except Exception:
                    predicted = None
            self.events.put(("captcha_ready", (item, challenge, predicted)))
        except Exception as exc:
            self.events.put(("error", (item, str(exc))))

    def submit_captcha(self) -> None:
        if self.busy:
            return
        if not self.current_item or not self.current_captcha:
            self.status_var.set("当前没有可提交的验证码")
            return
        code = self.captcha_entry.get().strip()
        if not code:
            self.status_var.set("请输入验证码")
            self.captcha_entry.focus_set()
            return
        item = self.current_item
        captcha = self.current_captcha
        self._submit_with_captcha(item, captcha, code)

    def _submit_with_captcha(self, item: QueryItem, captcha: CaptchaChallenge, code: str) -> None:
        self.busy = True
        item.status = STATUS_QUERYING
        self._render_queue()
        self.status_var.set(f"正在查询：{item.name}")
        threading.Thread(target=self._submit_worker, args=(item, captcha, code), daemon=True).start()

    def _submit_worker(self, item: QueryItem, captcha: CaptchaChallenge, code: str) -> None:
        try:
            result = self.client.search(item, captcha, code)
            self.events.put(("search_done", (item, captcha, result, code)))
        except Exception as exc:
            self.events.put(("error", (item, str(exc))))

    def refresh_captcha(self) -> None:
        if self.busy:
            return
        if not self.current_item:
            self.status_var.set("当前没有需要刷新验证码的查询")
            return
        self._delete_current_captcha()
        self._fetch_captcha_for(self.current_item)

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "captcha_ready":
                    item, challenge, predicted = payload
                    self._handle_captcha_ready(item, challenge, predicted)
                elif event == "search_done":
                    item, captcha, result, code = payload
                    self._handle_search_done(item, captcha, result, code)
                elif event == "error":
                    item, message = payload
                    self._handle_error(item, message)
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _handle_captcha_ready(self, item: QueryItem, challenge: CaptchaChallenge, predicted: str | None) -> None:
        self.busy = False
        item.status = STATUS_WAITING_CAPTCHA
        self.current_item = item
        self.current_captcha = challenge
        self.current_predicted = predicted
        self.current_label_var.set(f"当前：{item.name}")
        self._show_captcha(challenge.image_path)
        self.captcha_entry.delete(0, tk.END)
        self._render_queue()

        if decide_captcha_action(self.auto_var.get(), predicted, self.auto_attempts) == AUTO_SUBMIT:
            self.auto_attempts += 1
            self.status_var.set(f"自动识别验证码（第 {self.auto_attempts} 次）：{predicted}")
            self._submit_with_captcha(item, challenge, predicted)
            return

        self.captcha_entry.focus_set()
        self.status_var.set("请输入验证码，按 Enter 提交")

    def _handle_search_done(self, item: QueryItem, captcha: CaptchaChallenge, result, code: str) -> None:
        self.busy = False
        if result.error:
            item.status = STATUS_CAPTCHA_ERROR
            item.error = result.error
            self.current_item = item
            self.current_captcha = captcha
            self._render_queue()
            self.captcha_entry.delete(0, tk.END)
            if should_auto_attempt(self.auto_var.get(), self.auto_attempts):
                self.status_var.set(f"验证码识别错误，自动换一张重试（已 {self.auto_attempts} 次）")
                self._delete_captcha(captcha)
                self.current_captcha = None
                self._fetch_captcha_for(item)
                return
            self.status_var.set(result.error)
            self.captcha_entry.focus_set()
            return

        item.result_rows = result.rows
        out = None
        if not self._uses_batch_output():
            out = render_result_png(item, result.rows, paths.temp_results_dir(), date.today().isoformat())
            self.output_paths.append(out)
            self._update_save_button()
        self.auto_attempts = 0
        item.status = STATUS_DONE
        item.output_path = out
        item.error = None
        self.captcha_entry.delete(0, tk.END)
        self._render_queue()
        self.status_var.set(f"已完成：{item.name}")

        next_item = self._next_pending_item()
        if next_item:
            self.current_item = next_item
            self.current_captcha = captcha
            self.current_label_var.set(f"当前：{next_item.name}")
            self._submit_with_captcha(next_item, captcha, code)
            return

        self._delete_captcha(captcha)
        self.current_item = None
        self.current_captcha = None
        self._advance_queue()

    def _handle_error(self, item: QueryItem, message: str) -> None:
        self.busy = False
        item.status = STATUS_FAILED
        item.error = message
        self.status_var.set(f"{item.name} 查询失败：{message}")
        self._render_queue()
        self._advance_queue()

    def _show_captcha(self, image_path: Path) -> None:
        image = Image.open(image_path)
        image = image.resize((image.width * 2, image.height * 2))
        self.captcha_photo = ImageTk.PhotoImage(image)
        self.captcha_label.configure(image=self.captcha_photo, text="")

    def _delete_current_captcha(self) -> None:
        if self.current_captcha:
            self._delete_captcha(self.current_captcha)
            self.current_captcha = None

    @staticmethod
    def _delete_captcha(captcha: CaptchaChallenge) -> None:
        try:
            captcha.image_path.unlink()
        except FileNotFoundError:
            pass

    def _render_queue(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.items:
            output = str(item.output_path) if item.output_path else (item.error or "")
            kind = "个人" if item.kind == "person" else "企业"
            self.tree.insert(
                "",
                tk.END,
                iid=str(item.index),
                values=(item.index, kind, item.name, item.card_num, item.status, output),
            )

    def _uses_batch_output(self) -> bool:
        return len(self.items) > 2

    def _next_pending_item(self) -> QueryItem | None:
        for item in self.items:
            if item.status == STATUS_PENDING:
                return item
        return None

    def _finish_batch_output_if_ready(self) -> None:
        if not self._uses_batch_output() or self.batch_output_path:
            return
        if not self.items or any(item.status != STATUS_DONE for item in self.items):
            return
        out = render_batch_result_png(self.items, paths.temp_results_dir(), date.today().isoformat())
        self.batch_output_path = out
        self.output_paths = [out]
        self._update_save_button()
        for item in self.items:
            item.output_path = out
        self._render_queue()
        self.status_var.set(f"队列已完成，已生成汇总 PNG：{out}")

    def _update_save_button(self) -> None:
        self.save_button.configure(state="normal" if self.output_paths else "disabled")

    def save_results(self) -> None:
        if not self.output_paths:
            messagebox.showinfo("没有结果", "还没有可保存的结果。")
            return
        if len(self.output_paths) == 1:
            src = self.output_paths[0]
            dest = filedialog.asksaveasfilename(
                title="保存结果",
                defaultextension=".png",
                initialfile=src.name,
                filetypes=[("PNG 图片", "*.png")],
            )
            if not dest:
                return
            shutil.copyfile(src, dest)
            self.status_var.set(f"已保存：{dest}")
            return
        folder = filedialog.askdirectory(title="选择保存文件夹")
        if not folder:
            return
        for src in self.output_paths:
            shutil.copyfile(src, Path(folder) / src.name)
        self.status_var.set(f"已保存 {len(self.output_paths)} 个文件到：{folder}")


def main() -> None:
    app = ZxgkApp()
    app.mainloop()
