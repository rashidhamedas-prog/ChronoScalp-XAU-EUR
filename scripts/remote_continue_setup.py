#!/usr/bin/env python3
"""Continue ChronoScalp VPS setup after partial bootstrap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ["VPS_HOST"]
PASSWORD = os.environ["VPS_PASSWORD"]
PUBKEY = Path(os.environ["SSH_PUBKEY_PATH"]).read_text(encoding="utf-8").strip()
DEPLOY_USER = "chronoscalp"
INSTALL_DIR = f"/home/{DEPLOY_USER}/ChronoScalp-XAU-EUR"
REPO = "https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git"
LOCAL_ROOT = Path(__file__).resolve().parents[1]
KEY_PATH = Path.home() / ".ssh" / "chronoscalp_vps"


def connect(password: str | None = None, key: bool = False) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw: dict = {
        "hostname": HOST,
        "username": "root",
        "timeout": 60,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if key:
        kw["key_filename"] = str(KEY_PATH)
        kw["username"] = DEPLOY_USER
    else:
        kw["password"] = password
    c.connect(**kw)
    return c


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 900, check: bool = True) -> str:
    print("CMD:", cmd[:140])
    _i, out, err = c.exec_command(cmd, timeout=timeout)
    data = out.read().decode("utf-8", "replace")
    edata = err.read().decode("utf-8", "replace")
    code = out.channel.recv_exit_status()
    sys.stdout.buffer.write((data[-6000:] + "\n").encode("utf-8", "replace"))
    if code != 0:
        sys.stdout.buffer.write(("ERR:" + edata[-3000:] + "\n").encode("utf-8", "replace"))
    if check and code != 0:
        raise RuntimeError(f"fail {code}")
    return data


def main() -> None:
    c = connect(password=PASSWORD)

    run(
        c,
        "export DEBIAN_FRONTEND=noninteractive; apt-get install -y "
        "git curl ufw fail2ban unattended-upgrades ca-certificates "
        "python3 python3-venv python3-pip docker.io openssh-server",
        timeout=1200,
    )

    # Docker Compose plugin via GitHub release binary (works without docker.com apt repo)
    run(
        c,
        "set -e; "
        "if ! docker compose version >/dev/null 2>&1; then "
        "  curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 "
        "    -o /usr/local/lib/docker/cli-plugins/docker-compose; "
        "  mkdir -p /usr/local/lib/docker/cli-plugins; "
        "  curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 "
        "    -o /usr/local/lib/docker/cli-plugins/docker-compose; "
        "  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose; "
        "fi; "
        "docker --version; docker compose version",
        check=False,
    )
    # Fix order if mkdir was after first curl fail
    run(
        c,
        "mkdir -p /usr/local/lib/docker/cli-plugins && "
        "curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 "
        "-o /usr/local/lib/docker/cli-plugins/docker-compose && "
        "chmod +x /usr/local/lib/docker/cli-plugins/docker-compose && "
        "docker compose version",
        check=False,
    )

    run(c, f"id {DEPLOY_USER} >/dev/null 2>&1 || adduser --disabled-password --gecos '' {DEPLOY_USER}", check=False)
    run(c, f"usermod -aG sudo,docker {DEPLOY_USER}", check=False)
    run(
        c,
        f"echo '{DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/{DEPLOY_USER} && "
        f"chmod 440 /etc/sudoers.d/{DEPLOY_USER}",
    )

    for home, uname in (("/root", "root"), (f"/home/{DEPLOY_USER}", DEPLOY_USER)):
        run(c, f"mkdir -p {home}/.ssh && chmod 700 {home}/.ssh")
        run(
            c,
            "python3 - <<'PY'\n"
            f"from pathlib import Path\n"
            f"p=Path('{home}/.ssh/authorized_keys')\n"
            f"key={PUBKEY!r}\n"
            "ex=p.read_text() if p.exists() else ''\n"
            "if key not in ex:\n"
            "  p.write_text(ex+('' if not ex or ex.endswith(chr(10)) else chr(10))+key+chr(10))\n"
            "p.chmod(0o600)\n"
            f"import os; st=os.stat('{home}'); os.chown(str(p), st.st_uid, st.st_gid)\n"
            "print('ok', p)\n"
            "PY",
        )
        run(c, f"chown -R {uname}:{uname} {home}/.ssh")

    # sshd harden
    run(
        c,
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "p=Path('/etc/ssh/sshd_config')\n"
        "wanted={'PasswordAuthentication':'no','PermitRootLogin':'prohibit-password',"
        "'PubkeyAuthentication':'yes','KbdInteractiveAuthentication':'no',"
        "'ChallengeResponseAuthentication':'no','X11Forwarding':'no','MaxAuthTries':'3'}\n"
        "lines=[]; seen=set()\n"
        "for line in p.read_text().splitlines():\n"
        "  raw=line.strip()\n"
        "  if not raw or raw.startswith('#'):\n"
        "    lines.append(line); continue\n"
        "  key=raw.split()[0]\n"
        "  if key in wanted:\n"
        "    lines.append(f'{key} {wanted[key]}'); seen.add(key)\n"
        "  else:\n"
        "    lines.append(line)\n"
        "for k,v in wanted.items():\n"
        "  if k not in seen: lines.append(f'{k} {v}')\n"
        "p.write_text(chr(10).join(lines)+chr(10))\n"
        "print('sshd updated')\n"
        "PY",
    )
    run(c, "systemctl restart ssh || systemctl restart sshd")

    run(c, "ufw default deny incoming && ufw default allow outgoing")
    run(c, "ufw allow OpenSSH && ufw allow 8501/tcp && ufw --force enable")
    run(c, "systemctl enable --now fail2ban docker")
    run(c, "systemctl enable unattended-upgrades", check=False)

    run(
        c,
        f"sudo -u {DEPLOY_USER} bash -lc '"
        f"set -e; "
        f"if [ ! -d {INSTALL_DIR}/.git ]; then git clone {REPO} {INSTALL_DIR}; "
        f"else cd {INSTALL_DIR} && git fetch origin && git reset --hard origin/main; fi; "
        f"cd {INSTALL_DIR}; mkdir -p data/state data/spread_history data/reports logs; "
        f"[ -f .env ] || cp .env.example .env"
        f"'",
    )

    # Upload local newer files via SFTP (repo may not have latest push yet)
    transport = c.get_transport()
    assert transport is not None
    sftp = paramiko.SFTPClient.from_transport(transport)
    assert sftp is not None
    uploads = [
        "scripts/telegram_control_bot.py",
        "scripts/remote_bootstrap.py",
        "docker/docker-compose.yml",
        "src/chronoscalp/orchestration/kill_switch.py",
        "docs/SSH_VPS.md",
        "src/chronoscalp/orchestration/trade_journal.py",
        "scripts/dashboard_stats.py",
        "scripts/dashboard.py",
        "scripts/dashboard_i18n.py",
        "scripts/app.py",
    ]
    for rel in uploads:
        local = LOCAL_ROOT / rel
        if not local.exists():
            print("skip missing", rel)
            continue
        remote = f"{INSTALL_DIR}/{rel}"
        # ensure remote dir
        run(c, f"mkdir -p $(dirname {remote}) && chown {DEPLOY_USER}:{DEPLOY_USER} $(dirname {remote})")
        sftp.put(str(local), remote)
        run(c, f"chown {DEPLOY_USER}:{DEPLOY_USER} {remote}")
        print("uploaded", rel)
    sftp.close()

    run(
        c,
        f"sudo -u {DEPLOY_USER} bash -lc \"cat > {INSTALL_DIR}/config/runtime_overrides.yaml <<'EOF'\n"
        "execution:\n"
        "  broker: paper\n"
        "  data_source: oanda\n"
        "oanda:\n"
        "  environment: practice\n"
        "alerting:\n"
        "  enabled: true\n"
        "  telegram_enabled: true\n"
        "licensing:\n"
        "  require_license: false\n"
        "EOF\"",
    )

    print("SETUP_DONE")
    c.close()

    # verify key login
    try:
        c2 = connect(key=True)
        run(c2, "whoami && hostname && docker --version", check=False)
        print("KEY_LOGIN_OK")
        c2.close()
    except Exception as exc:  # noqa: BLE001
        print("KEY_LOGIN_FAIL", type(exc).__name__, str(exc)[:200])


if __name__ == "__main__":
    main()
