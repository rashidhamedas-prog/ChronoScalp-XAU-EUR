#!/usr/bin/env python3
"""One-shot remote VPS bootstrap for ChronoScalp (run from your PC).

Usage (PowerShell):
  $env:VPS_HOST='89.23.103.82'
  $env:VPS_USER='root'
  $env:VPS_PASSWORD='...'
  $env:SSH_PUBKEY_PATH="$env:USERPROFILE\\.ssh\\chronoscalp_vps.pub"
  python scripts/remote_bootstrap.py

Does NOT print or commit the password. Prefer deleting VPS_PASSWORD from
shell history after success and rotating the root password.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("VPS_HOST", "").strip()
USER = os.environ.get("VPS_USER", "root").strip()
PASSWORD = os.environ.get("VPS_PASSWORD", "")
PUBKEY_PATH = Path(
    os.environ.get("SSH_PUBKEY_PATH", str(Path.home() / ".ssh" / "chronoscalp_vps.pub"))
)
DEPLOY_USER = os.environ.get("DEPLOY_USER", "chronoscalp").strip()
REPO_URL = os.environ.get(
    "REPO_URL", "https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git"
)
INSTALL_DIR = f"/home/{DEPLOY_USER}/ChronoScalp-XAU-EUR"


def _connect(password: str | None = None, key_path: Path | None = None) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict = {
        "hostname": HOST,
        "username": USER,
        "timeout": 60,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if key_path and key_path.exists():
        kwargs["key_filename"] = str(key_path)
    elif password:
        kwargs["password"] = password
    else:
        raise RuntimeError("Need password or key")
    client.connect(**kwargs)
    return client


def run(client: paramiko.SSHClient, cmd: str, *, check: bool = True, timeout: int = 600) -> str:
    print(f"$ {cmd[:120]}{'...' if len(cmd) > 120 else ''}")
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out[-4000:])
    if err.strip() and code != 0:
        print(err[-2000:], file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"Remote command failed ({code}): {cmd}")
    return out


def main() -> None:
    if not HOST or not PASSWORD:
        raise SystemExit("Set VPS_HOST and VPS_PASSWORD env vars")
    if not PUBKEY_PATH.exists():
        raise SystemExit(f"Public key not found: {PUBKEY_PATH}")

    pubkey = PUBKEY_PATH.read_text(encoding="utf-8").strip()
    print(f"Connecting to {USER}@{HOST} ...")
    client = _connect(password=PASSWORD)

    # --- packages + harden ---
    run(client, "export DEBIAN_FRONTEND=noninteractive; apt-get update -y")
    run(
        client,
        "export DEBIAN_FRONTEND=noninteractive; apt-get upgrade -y",
        timeout=1200,
    )
    run(
        client,
        "export DEBIAN_FRONTEND=noninteractive; apt-get install -y "
        "git curl ufw fail2ban unattended-upgrades ca-certificates "
        "python3 python3-venv python3-pip docker.io docker-compose-plugin "
        "openssh-server",
        timeout=1200,
    )

    # deploy user
    run(
        client,
        f"id {DEPLOY_USER} >/dev/null 2>&1 || "
        f"adduser --disabled-password --gecos '' {DEPLOY_USER}",
        check=False,
    )
    run(client, f"usermod -aG sudo,docker {DEPLOY_USER}", check=False)
    run(
        client,
        f"echo '{DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{DEPLOY_USER} && "
        f"chmod 440 /etc/sudoers.d/{DEPLOY_USER}",
    )

    # install SSH keys for root + deploy user
    for home, uname in (("/root", "root"), (f"/home/{DEPLOY_USER}", DEPLOY_USER)):
        run(client, f"mkdir -p {home}/.ssh && chmod 700 {home}/.ssh")
        # append if missing
        run(
            client,
            "python3 - <<'PY'\n"
            f"from pathlib import Path\n"
            f"p = Path('{home}/.ssh/authorized_keys')\n"
            f"key = '''{pubkey}'''\n"
            "existing = p.read_text() if p.exists() else ''\n"
            "if key not in existing:\n"
            "    p.write_text(existing + ('' if not existing or existing.endswith('\\n') else '\\n') + key + '\\n')\n"
            "p.chmod(0o600)\n"
            f"import os; os.chown(p, os.stat('{home}').st_uid, os.stat('{home}').st_gid)\n"
            "print('authorized_keys ok', p)\n"
            "PY",
        )
        run(client, f"chown -R {uname}:{uname} {home}/.ssh")

    # sshd harden
    run(
        client,
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "p = Path('/etc/ssh/sshd_config')\n"
        "text = p.read_text()\n"
        "lines = []\n"
        "seen = set()\n"
        "wanted = {\n"
        "  'PasswordAuthentication': 'no',\n"
        "  'PermitRootLogin': 'prohibit-password',\n"
        "  'PubkeyAuthentication': 'yes',\n"
        "  'KbdInteractiveAuthentication': 'no',\n"
        "  'ChallengeResponseAuthentication': 'no',\n"
        "  'X11Forwarding': 'no',\n"
        "  'MaxAuthTries': '3',\n"
        "}\n"
        "for line in text.splitlines():\n"
        "    raw = line.strip()\n"
        "    if not raw or raw.startswith('#'):\n"
        "        lines.append(line); continue\n"
        "    key = raw.split()[0]\n"
        "    if key in wanted:\n"
        "        lines.append(f'{key} {wanted[key]}')\n"
        "        seen.add(key)\n"
        "    else:\n"
        "        lines.append(line)\n"
        "for k,v in wanted.items():\n"
        "    if k not in seen:\n"
        "        lines.append(f'{k} {v}')\n"
        "p.write_text('\\n'.join(lines) + '\\n')\n"
        "print('sshd_config updated')\n"
        "PY",
    )
    run(client, "systemctl restart ssh || systemctl restart sshd")

    # firewall
    run(client, "ufw default deny incoming")
    run(client, "ufw default allow outgoing")
    run(client, "ufw allow OpenSSH")
    run(client, "ufw allow 8501/tcp comment 'ChronoScalp dashboard optional'")
    run(client, "ufw --force enable")
    run(client, "systemctl enable --now fail2ban")
    run(client, "systemctl enable --now docker")
    run(client, "systemctl enable unattended-upgrades", check=False)

    # clone + configure project as deploy user
    run(
        client,
        f"sudo -u {DEPLOY_USER} bash -lc '"
        f"set -e; "
        f"if [ ! -d {INSTALL_DIR}/.git ]; then git clone {REPO_URL} {INSTALL_DIR}; "
        f"else cd {INSTALL_DIR} && git fetch origin && git reset --hard origin/main; fi; "
        f"cd {INSTALL_DIR}; "
        f"mkdir -p data/state data/spread_history data/reports logs; "
        f"if [ ! -f .env ]; then cp .env.example .env; fi"
        f"'",
    )

    # paper + oanda data source overrides (no secrets)
    run(
        client,
        f"sudo -u {DEPLOY_USER} bash -lc '"
        f"cat > {INSTALL_DIR}/config/runtime_overrides.yaml <<EOF\n"
        f"execution:\n"
        f"  broker: paper\n"
        f"  data_source: oanda\n"
        f"oanda:\n"
        f"  environment: practice\n"
        f"alerting:\n"
        f"  enabled: true\n"
        f"  telegram_enabled: true\n"
        f"licensing:\n"
        f"  require_license: false\n"
        f"EOF\n"
        f"'",
    )

    # ensure settings can merge overrides — check if project supports runtime_overrides
    run(
        client,
        f"grep -n runtime_overrides {INSTALL_DIR}/src/chronoscalp/config.py || true",
        check=False,
    )

    run(client, "docker --version && docker compose version", check=False)
    print("\n=== Bootstrap finished ===")
    print(f"SSH key auth installed. Prefer: ssh -i ~/.ssh/chronoscalp_vps {DEPLOY_USER}@{HOST}")
    print("Password authentication disabled. Root password login should no longer work.")
    print("Next: put OANDA_* and TELEGRAM_* into .env on the server, then start docker.")
    client.close()


if __name__ == "__main__":
    main()
