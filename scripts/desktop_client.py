#!/usr/bin/env python3
"""ChronoScalp Windows desktop monitor — thin client over Control API.

Uses only the Python standard library (urllib + tkinter).
Proxy: set HTTP_PROXY / HTTPS_PROXY, or fill the Proxy field in the UI.

Run:
  python scripts/desktop_client.py
"""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib import error, request

DEFAULT_BASE = "http://45.90.98.99:8510"
DEFAULT_TOKEN = "Hamed95240"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".chronoscalp_desktop.json")


def load_cfg() -> dict:
    cfg = {
        "base_url": DEFAULT_BASE,
        "token": DEFAULT_TOKEN,
        "proxy": os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "",
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                cfg.update({k: v for k, v in loaded.items() if v is not None})
        except (OSError, json.JSONDecodeError):
            pass
    # Empty saved token → fall back to known server token
    if not str(cfg.get("token") or "").strip():
        cfg["token"] = DEFAULT_TOKEN
    return cfg


def save_cfg(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


class ApiClient:
    def __init__(self, base_url: str, token: str, proxy: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.proxy = proxy.strip()

    def _opener(self):
        if self.proxy:
            handler = request.ProxyHandler({"http": self.proxy, "https": self.proxy})
            return request.build_opener(handler)
        return request.build_opener()

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.token:
            raise RuntimeError("Token is empty — paste API token and click Save")
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with self._opener().open(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ChronoScalp Desktop")
        self.geometry("720x520")
        self.cfg = load_cfg()
        self._last_error = ""

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(frm, text="API URL").grid(row=row, column=0, sticky="w")
        self.url_var = tk.StringVar(value=self.cfg.get("base_url", DEFAULT_BASE))
        ttk.Entry(frm, textvariable=self.url_var, width=60).grid(row=row, column=1, sticky="ew")
        row += 1
        ttk.Label(frm, text="Token").grid(row=row, column=0, sticky="w")
        self.token_var = tk.StringVar(value=self.cfg.get("token", DEFAULT_TOKEN))
        ttk.Entry(frm, textvariable=self.token_var, width=60, show="*").grid(
            row=row, column=1, sticky="ew"
        )
        row += 1
        ttk.Label(frm, text="Proxy (optional)").grid(row=row, column=0, sticky="w")
        self.proxy_var = tk.StringVar(value=self.cfg.get("proxy", ""))
        ttk.Entry(frm, textvariable=self.proxy_var, width=60).grid(row=row, column=1, sticky="ew")
        row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(btns, text="Save", command=self.save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Refresh", command=lambda: self.refresh(quiet=False)).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Start Paper", command=lambda: self.start("paper")).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Start Live", command=lambda: self.start("live")).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Stop", command=self.stop).pack(side=tk.LEFT, padx=4)
        row += 1

        self.status_var = tk.StringVar(value="Connecting…")
        ttk.Label(frm, textvariable=self.status_var, font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        self.log = tk.Text(frm, height=22, wrap=tk.WORD)
        self.log.grid(row=row, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(row, weight=1)
        frm.columnconfigure(1, weight=1)

        # Persist defaults so next launch already has token
        save_cfg(
            {
                "base_url": self.url_var.get().strip(),
                "token": self.token_var.get().strip() or DEFAULT_TOKEN,
                "proxy": self.proxy_var.get().strip(),
            }
        )

        self.after(400, lambda: self.refresh(quiet=True))
        self.after(5000, self._auto_refresh)

    def client(self) -> ApiClient:
        return ApiClient(self.url_var.get(), self.token_var.get(), self.proxy_var.get())

    def save(self) -> None:
        token = self.token_var.get().strip() or DEFAULT_TOKEN
        self.token_var.set(token)
        self.cfg = {
            "base_url": self.url_var.get().strip(),
            "token": token,
            "proxy": self.proxy_var.get().strip(),
        }
        save_cfg(self.cfg)
        messagebox.showinfo("Saved", f"Settings stored in {CONFIG_PATH}")
        self.refresh(quiet=False)

    def _auto_refresh(self) -> None:
        self.refresh(quiet=True)
        self.after(5000, self._auto_refresh)

    def _run(self, fn, *, quiet: bool) -> None:
        def worker() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self._last_error = err

                def show() -> None:
                    self.status_var.set(f"Error: {err[:120]}")
                    if not quiet:
                        messagebox.showerror("Error", err)

                self.after(0, show)

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self, quiet: bool = False) -> None:
        def work() -> None:
            data = self.client().call("GET", "/status")
            running = data.get("running")
            mode = data.get("mode")
            syms = ",".join(data.get("symbols") or [])
            line = (
                f"{'RUNNING' if running else 'STOPPED'} | mode={mode} | "
                f"broker={data.get('broker')} | symbols={syms} | "
                f"live_confirm={data.get('live_confirmed')}"
            )
            tail = "\n".join(data.get("log_tail") or [])
            self.after(0, lambda: self._apply(line, tail))

        self._run(work, quiet=quiet)

    def _apply(self, status: str, tail: str) -> None:
        self.status_var.set(status)
        self.log.delete("1.0", tk.END)
        self.log.insert(tk.END, tail)

    def start(self, mode: str) -> None:
        def work() -> None:
            data = self.client().call("POST", "/bot/start", {"mode": mode})
            self.after(0, lambda: messagebox.showinfo("Start", data.get("message", "ok")))
            self.refresh(quiet=True)

        self._run(work, quiet=False)

    def stop(self) -> None:
        def work() -> None:
            data = self.client().call("POST", "/bot/stop")
            self.after(0, lambda: messagebox.showinfo("Stop", data.get("message", "ok")))
            self.refresh(quiet=True)

        self._run(work, quiet=False)


if __name__ == "__main__":
    App().mainloop()
