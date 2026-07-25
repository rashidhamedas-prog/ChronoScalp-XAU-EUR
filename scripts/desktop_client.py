#!/usr/bin/env python3
"""ChronoScalp Desktop — talks to VPS Control API through SSH (no open WAN ports).

Default: SSH to the VPS and call http://127.0.0.1:8510 on the server itself.
This avoids Iran ISP blocks on 8510 and broken Windows SSH -L forwarding.

Run:
  python scripts/desktop_client.py
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

DEFAULT_SSH_HOST = "45.90.98.99"
DEFAULT_SSH_USER = "Administrator"
DEFAULT_SSH_KEY = os.path.join(os.path.expanduser("~"), ".ssh", "chronoscalp_vps")
DEFAULT_TOKEN = "Hamed95240"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".chronoscalp_desktop.json")


def load_cfg() -> dict:
    cfg = {
        "ssh_host": DEFAULT_SSH_HOST,
        "ssh_user": DEFAULT_SSH_USER,
        "ssh_key": DEFAULT_SSH_KEY,
        "token": DEFAULT_TOKEN,
        "proxy": "",  # unused in SSH mode; kept for compatibility
        "base_url": "ssh://vps",  # display only
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                cfg.update({k: v for k, v in loaded.items() if v is not None})
        except (OSError, json.JSONDecodeError):
            pass
    if not str(cfg.get("token") or "").strip():
        cfg["token"] = DEFAULT_TOKEN
    if not str(cfg.get("ssh_key") or "").strip():
        cfg["ssh_key"] = DEFAULT_SSH_KEY
    return cfg


def save_cfg(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


class SshApiClient:
    """Invoke Control API endpoints on the VPS over an SSH remote command."""

    def __init__(self, host: str, user: str, key: str, token: str) -> None:
        self.host = host.strip()
        self.user = user.strip()
        self.key = key.strip()
        self.token = token.strip()

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.token:
            raise RuntimeError("Token is empty — paste token and click Save")
        if not os.path.exists(self.key):
            raise RuntimeError(f"SSH key not found: {self.key}")

        # PowerShell on VPS talks to local API (always reachable on the server).
        ps_body = ""
        if body is not None:
            raw = json.dumps(body).replace("'", "''")
            ps_body = (
                f"$body = '{raw}'; "
                "$bytes = [Text.Encoding]::UTF8.GetBytes($body); "
            )
        ps = (
            "$ErrorActionPreference='Stop'; "
            f"$h=@{{ Authorization='Bearer {self.token}'"
            + ("; 'Content-Type'='application/json'" if body is not None else "")
            + " }; "
            + ps_body
            + f"$uri='http://127.0.0.1:8510{path}'; "
            + (
                f"$r=Invoke-WebRequest -Uri $uri -Method {method} -Headers $h "
                f"-Body $bytes -UseBasicParsing -TimeoutSec 45; "
                if body is not None
                else f"$r=Invoke-WebRequest -Uri $uri -Method {method} -Headers $h "
                f"-UseBasicParsing -TimeoutSec 45; "
            )
            + "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
            "Write-Output $r.Content"
        )

        cmd = [
            "ssh",
            "-i",
            self.key,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            f"{self.user}@{self.host}",
            "powershell",
            "-NoProfile",
            "-Command",
            ps,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("SSH timed out — check VPS/OpenSSH") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("ssh.exe not found — install OpenSSH Client") from exc

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"SSH/API error: {err[:400] or f'exit {proc.returncode}'}")

        raw = (proc.stdout or "").strip()
        if not raw:
            raise RuntimeError("Empty response from VPS API")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Bad JSON from VPS: {raw[:200]}") from exc


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ChronoScalp Desktop (SSH)")
        self.geometry("760x540")
        self.cfg = load_cfg()
        self._last_error = ""

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(frm, text="SSH Host").grid(row=row, column=0, sticky="w")
        self.host_var = tk.StringVar(value=self.cfg.get("ssh_host", DEFAULT_SSH_HOST))
        ttk.Entry(frm, textvariable=self.host_var, width=62).grid(row=row, column=1, sticky="ew")
        row += 1

        ttk.Label(frm, text="SSH User").grid(row=row, column=0, sticky="w")
        self.user_var = tk.StringVar(value=self.cfg.get("ssh_user", DEFAULT_SSH_USER))
        ttk.Entry(frm, textvariable=self.user_var, width=62).grid(row=row, column=1, sticky="ew")
        row += 1

        ttk.Label(frm, text="SSH Key").grid(row=row, column=0, sticky="w")
        self.key_var = tk.StringVar(value=self.cfg.get("ssh_key", DEFAULT_SSH_KEY))
        ttk.Entry(frm, textvariable=self.key_var, width=62).grid(row=row, column=1, sticky="ew")
        row += 1

        ttk.Label(frm, text="API Token").grid(row=row, column=0, sticky="w")
        self.token_var = tk.StringVar(value=self.cfg.get("token", DEFAULT_TOKEN))
        ttk.Entry(frm, textvariable=self.token_var, width=62, show="*").grid(
            row=row, column=1, sticky="ew"
        )
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

        self.status_var = tk.StringVar(value="Connecting via SSH…")
        ttk.Label(frm, textvariable=self.status_var, font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        self.log = tk.Text(frm, height=20, wrap=tk.WORD)
        self.log.grid(row=row, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(row, weight=1)
        frm.columnconfigure(1, weight=1)

        save_cfg(self._current_cfg())
        self.after(400, lambda: self.refresh(quiet=True))
        self.after(8000, self._auto_refresh)

    def _current_cfg(self) -> dict:
        return {
            "ssh_host": self.host_var.get().strip(),
            "ssh_user": self.user_var.get().strip(),
            "ssh_key": self.key_var.get().strip(),
            "token": self.token_var.get().strip() or DEFAULT_TOKEN,
            "base_url": "ssh://vps",
            "proxy": "",
        }

    def client(self) -> SshApiClient:
        c = self._current_cfg()
        return SshApiClient(c["ssh_host"], c["ssh_user"], c["ssh_key"], c["token"])

    def save(self) -> None:
        self.token_var.set(self.token_var.get().strip() or DEFAULT_TOKEN)
        self.cfg = self._current_cfg()
        save_cfg(self.cfg)
        messagebox.showinfo("Saved", f"Settings stored in {CONFIG_PATH}")
        self.refresh(quiet=False)

    def _auto_refresh(self) -> None:
        self.refresh(quiet=True)
        self.after(8000, self._auto_refresh)

    def _run(self, fn, *, quiet: bool) -> None:
        def worker() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self._last_error = err

                def show() -> None:
                    self.status_var.set(f"Error: {err[:140]}")
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
