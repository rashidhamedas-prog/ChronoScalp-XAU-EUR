#!/usr/bin/env python3
"""ChronoScalp Desktop Manager — full ops panel over SSH Control API.

Talks to the VPS Control API through SSH (no open WAN ports). Provides
Telegram-parity control plus live positions, journal, and strategy P&L reports.

Run:
  python scripts/desktop_client.py
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

DEFAULT_SSH_HOST = os.environ.get("CHRONOSCALP_SSH_HOST", "45.90.98.99")
DEFAULT_SSH_USER = os.environ.get("CHRONOSCALP_SSH_USER", "Administrator")
DEFAULT_SSH_KEY = os.environ.get(
    "CHRONOSCALP_SSH_KEY",
    os.path.join(os.path.expanduser("~"), ".ssh", "chronoscalp_vps"),
)
DEFAULT_TOKEN = os.environ.get("CHRONOSCALP_API_TOKEN", "")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".chronoscalp_desktop.json")

STRATEGY_LABELS = {
    "ultra_scalp": "Ultra Scalp",
    "institutional": "Institutional",
    "news_straddle": "News Straddle",
    "smc_confluence": "SMC",
    "liquidity_volume": "Liquidity",
    "unknown": "Unknown / legacy",
}


def load_cfg() -> dict:
    cfg = {
        "ssh_host": DEFAULT_SSH_HOST,
        "ssh_user": DEFAULT_SSH_USER,
        "ssh_key": DEFAULT_SSH_KEY,
        "token": DEFAULT_TOKEN,
        "proxy": "",
        "base_url": "ssh://vps",
        "auto_refresh_sec": 8,
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

        ps_body = ""
        if body is not None:
            raw = json.dumps(body).replace("'", "''")
            ps_body = f"$body = '{raw}'; " "$bytes = [Text.Encoding]::UTF8.GetBytes($body); "
        ps = (
            "$ErrorActionPreference='Stop'; "
            f"$h=@{{ Authorization='Bearer {self.token}'"
            + ("; 'Content-Type'='application/json'" if body is not None else "")
            + " }; "
            + ps_body
            + f"$uri='http://127.0.0.1:8510{path}'; "
            + (
                f"$r=Invoke-WebRequest -Uri $uri -Method {method} -Headers $h "
                f"-Body $bytes -UseBasicParsing -TimeoutSec 60; "
                if body is not None
                else f"$r=Invoke-WebRequest -Uri $uri -Method {method} -Headers $h "
                f"-UseBasicParsing -TimeoutSec 60; "
            )
            + "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
            "Write-Output $r.Content"
        )
        return self._ssh_json(ps, timeout_sec=120)

    def snapshot(self) -> dict:
        """Fetch the full desktop payload in a single SSH + HTTP round-trip."""
        return self.call("GET", "/desktop/snapshot?closed_limit=150&log_lines=120")

    def _ssh_json(self, ps: str, *, timeout_sec: int = 120) -> dict:
        cmd = [
            "ssh",
            "-i",
            self.key,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=25",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=3",
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
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"SSH timed out after {timeout_sec}s — check VPS/OpenSSH/VPN, then Retry"
            ) from exc
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


def _fmt_money(value: Any) -> str:
    try:
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return "—"


def _clear_tree(tree: ttk.Treeview) -> None:
    for item in tree.get_children():
        tree.delete(item)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ChronoScalp Desktop Manager")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.cfg = load_cfg()
        self._last_error = ""
        self._status_cache: dict[str, Any] = {}
        self._refreshing = False

        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)

        self._build_connection_bar(root)
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        self.tab_overview = ttk.Frame(self.notebook, padding=8)
        self.tab_positions = ttk.Frame(self.notebook, padding=8)
        self.tab_journal = ttk.Frame(self.notebook, padding=8)
        self.tab_strategy = ttk.Frame(self.notebook, padding=8)
        self.tab_settings = ttk.Frame(self.notebook, padding=8)
        self.tab_logs = ttk.Frame(self.notebook, padding=8)

        self.notebook.add(self.tab_overview, text="Overview")
        self.notebook.add(self.tab_positions, text="Live Positions")
        self.notebook.add(self.tab_journal, text="Trades")
        self.notebook.add(self.tab_strategy, text="Strategy P&L")
        self.notebook.add(self.tab_settings, text="Settings")
        self.notebook.add(self.tab_logs, text="Logs")

        self._build_overview()
        self._build_positions()
        self._build_journal()
        self._build_strategy()
        self._build_settings()
        self._build_logs()

        save_cfg(self._current_cfg())
        self.after(400, lambda: self.refresh_all(quiet=True))
        self.after(15000, self._auto_refresh)

    def _build_connection_bar(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="Connection (SSH → VPS API :8510)", padding=8)
        frm.grid(row=0, column=0, sticky="ew")
        for col in range(6):
            frm.columnconfigure(col, weight=1 if col % 2 == 1 else 0)

        ttk.Label(frm, text="Host").grid(row=0, column=0, sticky="w")
        self.host_var = tk.StringVar(value=self.cfg.get("ssh_host", DEFAULT_SSH_HOST))
        ttk.Entry(frm, textvariable=self.host_var, width=22).grid(row=0, column=1, sticky="ew", padx=4)

        ttk.Label(frm, text="User").grid(row=0, column=2, sticky="w")
        self.user_var = tk.StringVar(value=self.cfg.get("ssh_user", DEFAULT_SSH_USER))
        ttk.Entry(frm, textvariable=self.user_var, width=16).grid(row=0, column=3, sticky="ew", padx=4)

        ttk.Label(frm, text="Key").grid(row=0, column=4, sticky="w")
        self.key_var = tk.StringVar(value=self.cfg.get("ssh_key", DEFAULT_SSH_KEY))
        ttk.Entry(frm, textvariable=self.key_var, width=36).grid(row=0, column=5, sticky="ew", padx=4)

        ttk.Label(frm, text="Token").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.token_var = tk.StringVar(value=self.cfg.get("token", DEFAULT_TOKEN))
        ttk.Entry(frm, textvariable=self.token_var, width=40, show="*").grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=(6, 0)
        )

        btns = ttk.Frame(frm)
        btns.grid(row=1, column=4, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(btns, text="Save", command=self.save).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Refresh All", command=lambda: self.refresh_all(quiet=False)).pack(
            side=tk.LEFT, padx=3
        )

    def _build_overview(self) -> None:
        frm = self.tab_overview
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(2, weight=1)

        self.status_var = tk.StringVar(value="Connecting via SSH…")
        ttk.Label(frm, textvariable=self.status_var, font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        self.kpi_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.kpi_var, font=("Consolas", 10)).grid(
            row=1, column=0, sticky="w", pady=(4, 8)
        )

        ctrl = ttk.LabelFrame(frm, text="Bot control", padding=8)
        ctrl.grid(row=2, column=0, sticky="new")
        for text, cmd in (
            ("Start Paper", lambda: self.start("paper")),
            ("Start Live", lambda: self.start("live")),
            ("Stop", self.stop),
            ("Kill ON", lambda: self.set_kill(True)),
            ("Kill OFF", lambda: self.set_kill(False)),
            ("Unlock Daily DD", self.unlock_daily),
        ):
            ttk.Button(ctrl, text=text, command=cmd).pack(side=tk.LEFT, padx=4, pady=2)

        self.account_var = tk.StringVar(value="Account: —")
        ttk.Label(frm, textvariable=self.account_var, font=("Consolas", 10)).grid(
            row=3, column=0, sticky="w", pady=(12, 0)
        )

    def _build_positions(self) -> None:
        frm = self.tab_positions
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        ttk.Button(frm, text="Refresh positions", command=self.refresh_positions).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        cols = (
            "ticket",
            "symbol",
            "direction",
            "volume",
            "entry",
            "sl",
            "tp",
            "profit",
            "strategy",
            "open_time",
        )
        self.pos_tree = ttk.Treeview(frm, columns=cols, show="headings", height=18)
        widths = {
            "ticket": 90,
            "symbol": 90,
            "direction": 70,
            "volume": 70,
            "entry": 100,
            "sl": 100,
            "tp": 100,
            "profit": 90,
            "strategy": 120,
            "open_time": 160,
        }
        for col in cols:
            self.pos_tree.heading(col, text=col)
            self.pos_tree.column(col, width=widths.get(col, 90), anchor="center")
        self.pos_tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frm, orient="vertical", command=self.pos_tree.yview)
        self.pos_tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")

    def _build_journal(self) -> None:
        frm = self.tab_journal
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        ttk.Button(frm, text="Refresh trades", command=self.refresh_journal).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        cols = (
            "ticket",
            "symbol",
            "direction",
            "volume",
            "entry",
            "exit",
            "pnl",
            "r",
            "strategy",
            "exit_reason",
            "close_time",
        )
        self.trade_tree = ttk.Treeview(frm, columns=cols, show="headings", height=18)
        for col in cols:
            self.trade_tree.heading(col, text=col)
            self.trade_tree.column(col, width=90 if col != "close_time" else 150, anchor="center")
        self.trade_tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frm, orient="vertical", command=self.trade_tree.yview)
        self.trade_tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")

    def _build_strategy(self) -> None:
        frm = self.tab_strategy
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        self.strategy_summary = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.strategy_summary, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        cols = (
            "strategy",
            "trades",
            "wins",
            "losses",
            "win_rate",
            "net_pnl",
            "gross_profit",
            "gross_loss",
            "profit_share",
            "loss_share",
            "pnl_pct",
            "open",
        )
        self.strat_tree = ttk.Treeview(frm, columns=cols, show="headings", height=14)
        for col in cols:
            self.strat_tree.heading(col, text=col)
            self.strat_tree.column(col, width=85, anchor="center")
        self.strat_tree.column("strategy", width=130)
        self.strat_tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frm, orient="vertical", command=self.strat_tree.yview)
        self.strat_tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")
        ttk.Label(
            frm,
            text="profit_share / loss_share = % of total winning / losing P&L attributed to that strategy",
            font=("Segoe UI", 8),
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))

    def _build_settings(self) -> None:
        frm = self.tab_settings
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Symbols (comma-separated)").grid(row=0, column=0, sticky="w")
        self.symbols_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.symbols_var, width=70).grid(
            row=0, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Button(frm, text="Apply symbols", command=self.apply_symbols).grid(row=0, column=2)

        ttk.Label(frm, text="Strategies").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        strat_box = ttk.Frame(frm)
        strat_box.grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.strategy_vars: dict[str, tk.BooleanVar] = {}
        for name in (
            "smc_confluence",
            "liquidity_volume",
            "ultra_scalp",
            "news_straddle",
        ):
            var = tk.BooleanVar(value=False)
            self.strategy_vars[name] = var
            ttk.Checkbutton(strat_box, text=name, variable=var).pack(anchor="w")
        ttk.Button(frm, text="Apply strategies", command=self.apply_strategies).grid(
            row=1, column=2, sticky="n", pady=(8, 0)
        )

        ttk.Label(frm, text="Trading hours").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.hours_var = tk.StringVar(value="london_ny")
        hours = ttk.Combobox(
            frm,
            textvariable=self.hours_var,
            values=["london_ny", "always_on_24h"],
            state="readonly",
            width=24,
        )
        hours.grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Button(frm, text="Apply hours", command=self.apply_hours).grid(
            row=2, column=2, pady=(8, 0)
        )

        ttk.Label(frm, text="Risk preset %").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.risk_var = tk.StringVar(value="1.0")
        risk = ttk.Combobox(
            frm, textvariable=self.risk_var, values=["0.5", "1.0", "1.5"], state="readonly", width=10
        )
        risk.grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Button(frm, text="Apply risk", command=self.apply_risk).grid(
            row=3, column=2, pady=(8, 0)
        )

        self.daily_loss_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm, text="Daily loss limit enabled", variable=self.daily_loss_var
        ).grid(row=4, column=1, sticky="w", pady=(8, 0))
        ttk.Button(frm, text="Apply daily-loss", command=self.apply_daily_loss).grid(
            row=4, column=2, pady=(8, 0)
        )

        note = (
            "Settings write runtime_overrides on the VPS. Restart the bot (Stop → Start) "
            "for most changes to take effect. Live confirm stays gated by .env."
        )
        ttk.Label(frm, text=note, wraplength=780).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(16, 0)
        )

    def _build_logs(self) -> None:
        frm = self.tab_logs
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)
        ttk.Button(frm, text="Refresh logs", command=self.refresh_logs).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.log = tk.Text(frm, wrap=tk.WORD, font=("Consolas", 9))
        self.log.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frm, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")

    def _current_cfg(self) -> dict:
        return {
            "ssh_host": self.host_var.get().strip(),
            "ssh_user": self.user_var.get().strip(),
            "ssh_key": self.key_var.get().strip(),
            "token": self.token_var.get().strip() or DEFAULT_TOKEN,
            "base_url": "ssh://vps",
            "proxy": "",
            "auto_refresh_sec": 8,
        }

    def client(self) -> SshApiClient:
        c = self._current_cfg()
        return SshApiClient(c["ssh_host"], c["ssh_user"], c["ssh_key"], c["token"])

    def save(self) -> None:
        self.token_var.set(self.token_var.get().strip() or DEFAULT_TOKEN)
        self.cfg = self._current_cfg()
        save_cfg(self.cfg)
        messagebox.showinfo("Saved", f"Settings stored in {CONFIG_PATH}")
        self.refresh_all(quiet=False)

    def _auto_refresh(self) -> None:
        self.refresh_all(quiet=True)
        self.after(15000, self._auto_refresh)

    def _run(self, fn: Callable[[], None], *, quiet: bool) -> None:
        def worker() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                self._last_error = err

                def show() -> None:
                    self.status_var.set(f"Error: {err[:160]}")
                    if not quiet:
                        messagebox.showerror("Error", err)

                self.after(0, show)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_all(self, quiet: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True

        def work() -> None:
            try:
                bundle = self.client().snapshot()
                status = bundle.get("status") or {}
                positions = bundle.get("positions") or {}
                journal = bundle.get("journal") or {}
                strategy = bundle.get("strategy") or {}
                logs = bundle.get("logs") or {}
                self.after(
                    0,
                    lambda: self._apply_all(status, positions, journal, strategy, logs),
                )
            finally:
                self._refreshing = False

        self._run(work, quiet=quiet)

    def refresh_positions(self) -> None:
        def work() -> None:
            data = self.client().call("GET", "/positions")
            self.after(0, lambda: self._fill_positions(data))

        self._run(work, quiet=False)

    def refresh_journal(self) -> None:
        def work() -> None:
            data = self.client().call("GET", "/journal?closed_limit=200")
            self.after(0, lambda: self._fill_journal(data))

        self._run(work, quiet=False)

    def refresh_logs(self) -> None:
        def work() -> None:
            data = self.client().call("GET", "/logs?lines=200")
            self.after(0, lambda: self._fill_logs(data.get("lines") or []))

        self._run(work, quiet=False)

    def _apply_all(
        self,
        status: dict,
        positions: dict,
        journal: dict,
        strategy: dict,
        logs: dict,
    ) -> None:
        self._status_cache = status
        running = status.get("running")
        mode = status.get("mode")
        syms = ",".join(status.get("symbols") or [])
        kill = "ON" if status.get("kill_switch") else "off"
        line = (
            f"{'RUNNING' if running else 'STOPPED'} | mode={mode} | "
            f"broker={status.get('broker')} | symbols={syms} | "
            f"kill={kill} | live_confirm={status.get('live_confirmed')}"
        )
        self.status_var.set(line)

        stats = status.get("stats") or {}
        self.kpi_var.set(
            f"net={_fmt_money(stats.get('net_pnl'))}  today={_fmt_money(stats.get('today_pnl'))}  "
            f"open={stats.get('open_trades', 0)}  closed={stats.get('closed_trades', 0)}  "
            f"WR={stats.get('win_rate_pct', 0)}%  PF={stats.get('profit_factor')}  "
            f"daily_loss={'ON' if status.get('daily_loss_limit_enabled') else 'OFF'}"
        )
        acct = status.get("account") or positions.get("account") or {}
        self.account_var.set(
            f"Account login={acct.get('login', '—')} server={acct.get('server', '—')}  "
            f"balance={acct.get('balance', '—')} equity={acct.get('equity', '—')}  "
            f"margin={acct.get('margin', '—')} floating={acct.get('profit', '—')}"
        )

        self.symbols_var.set(",".join(status.get("symbols") or []))
        enabled = set(status.get("strategies") or [])
        for name, var in self.strategy_vars.items():
            var.set(name in enabled)
        hours = status.get("trading_hours_mode") or "london_ny"
        self.hours_var.set(hours)
        self.daily_loss_var.set(bool(status.get("daily_loss_limit_enabled", True)))
        risk = status.get("risk_per_trade_pct")
        if risk is not None:
            self.risk_var.set(str(risk))

        self._fill_positions(positions)
        self._fill_journal(journal)
        self._fill_strategy(strategy)
        self._fill_logs(logs.get("lines") or [])

    def _fill_positions(self, data: dict) -> None:
        _clear_tree(self.pos_tree)
        for row in data.get("positions") or []:
            self.pos_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("ticket"),
                    row.get("symbol"),
                    row.get("direction"),
                    row.get("volume"),
                    row.get("entry_price"),
                    row.get("stop_loss"),
                    row.get("take_profit"),
                    _fmt_money(row.get("profit")),
                    row.get("strategy") or row.get("journal_strategy") or "—",
                    str(row.get("open_time") or "")[:19],
                ),
            )

    def _fill_journal(self, data: dict) -> None:
        _clear_tree(self.trade_tree)
        for row in data.get("closed_trades") or []:
            self.trade_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("ticket"),
                    row.get("symbol"),
                    row.get("direction"),
                    row.get("volume"),
                    row.get("entry_price"),
                    row.get("exit_price"),
                    _fmt_money(row.get("pnl")),
                    row.get("r_multiple"),
                    row.get("strategy") or "unknown",
                    row.get("exit_reason"),
                    str(row.get("close_time") or "")[:19],
                ),
            )

    def _fill_strategy(self, data: dict) -> None:
        _clear_tree(self.strat_tree)
        stats = data.get("stats") or {}
        self.strategy_summary.set(
            f"Overall net={_fmt_money(stats.get('net_pnl'))} | "
            f"wins={stats.get('wins', 0)} losses={stats.get('losses', 0)} | "
            f"today={_fmt_money(stats.get('today_pnl'))}"
        )
        rows = data.get("by_strategy") or data.get("strategy_stats") or []
        for row in rows:
            tag = row.get("strategy") or "unknown"
            label = STRATEGY_LABELS.get(tag, tag)
            self.strat_tree.insert(
                "",
                tk.END,
                values=(
                    label,
                    row.get("trades"),
                    row.get("wins"),
                    row.get("losses"),
                    f"{row.get('win_rate_pct', 0)}%",
                    _fmt_money(row.get("net_pnl")),
                    _fmt_money(row.get("gross_profit")),
                    _fmt_money(row.get("gross_loss")),
                    f"{row.get('profit_share_pct', 0)}%",
                    f"{row.get('loss_share_pct', 0)}%",
                    f"{row.get('pnl_pct_of_equity', 0)}%",
                    row.get("open_trades"),
                ),
            )

    def _fill_logs(self, lines: list[str]) -> None:
        self.log.delete("1.0", tk.END)
        self.log.insert(tk.END, "\n".join(lines))
        self.log.see(tk.END)

    def start(self, mode: str) -> None:
        if mode == "live" and not messagebox.askyesno(
            "Start LIVE",
            "Start LIVE trading on the VPS?\nRequires CHRONOSCALP_CONFIRM_LIVE=yes.",
        ):
            return

        def work() -> None:
            data = self.client().call("POST", "/bot/start", {"mode": mode})
            self.after(0, lambda: messagebox.showinfo("Start", data.get("message", "ok")))
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def stop(self) -> None:
        def work() -> None:
            data = self.client().call("POST", "/bot/stop")
            self.after(0, lambda: messagebox.showinfo("Stop", data.get("message", "ok")))
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def set_kill(self, active: bool) -> None:
        def work() -> None:
            data = self.client().call("POST", "/kill", {"active": active, "reason": "desktop"})
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Kill switch",
                    f"active={data.get('active')} reason={data.get('reason')}",
                ),
            )
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def unlock_daily(self) -> None:
        if not messagebox.askyesno(
            "Unlock daily DD",
            "Reset today's daily-loss tracker and restart the bot?",
        ):
            return

        def work() -> None:
            data = self.client().call(
                "POST", "/daily-loss/unlock", {"restart": True}
            )
            self.after(0, lambda: messagebox.showinfo("Unlock", data.get("message", "ok")))
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def apply_symbols(self) -> None:
        symbols = [s.strip() for s in self.symbols_var.get().split(",") if s.strip()]

        def work() -> None:
            data = self.client().call("POST", "/settings/symbols", {"symbols": symbols})
            self.after(0, lambda: messagebox.showinfo("Symbols", str(data.get("symbols"))))
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def apply_strategies(self) -> None:
        selected = [name for name, var in self.strategy_vars.items() if var.get()]

        def work() -> None:
            data = self.client().call(
                "POST", "/settings/strategies", {"strategies": selected}
            )
            self.after(0, lambda: messagebox.showinfo("Strategies", str(data.get("strategies"))))
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def apply_hours(self) -> None:
        def work() -> None:
            data = self.client().call(
                "POST", "/settings/hours", {"mode": self.hours_var.get()}
            )
            self.after(0, lambda: messagebox.showinfo("Hours", str(data.get("mode"))))
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def apply_risk(self) -> None:
        def work() -> None:
            data = self.client().call(
                "POST",
                "/settings/risk-preset",
                {"preset": float(self.risk_var.get())},
            )
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Risk", f"effective={data.get('risk_per_trade_pct')}%"
                ),
            )
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)

    def apply_daily_loss(self) -> None:
        def work() -> None:
            data = self.client().call(
                "POST",
                "/settings/daily-loss",
                {"enabled": bool(self.daily_loss_var.get())},
            )
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Daily loss",
                    f"enabled={data.get('daily_loss_limit_enabled')}",
                ),
            )
            self.refresh_all(quiet=True)

        self._run(work, quiet=False)


if __name__ == "__main__":
    App().mainloop()
