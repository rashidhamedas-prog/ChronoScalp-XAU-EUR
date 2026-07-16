#!/usr/bin/env bash
# One-time setup on Netherlands / Linux VPS (Ubuntu 22.04+)
# Usage: bash scripts/vps-setup.sh

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/ChronoScalp-XAU-EUR}"

echo "=== ChronoScalp VPS setup ==="

sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3.11 python3.11-venv python3-pip docker.io docker-compose-plugin ufw

if [ ! -d "$INSTALL_DIR" ]; then
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo ">>> Edit .env now: OANDA_API_TOKEN, OANDA_ACCOUNT_ID"
  echo ">>> Then set config/settings.yaml: broker=oanda, data_source=oanda"
fi

mkdir -p data/state data/spread_history data/reports logs

echo ""
echo "=== Setup complete ==="
echo "Next steps (see docs/RAHNAMA_FA.md):"
echo "  1. nano .env"
echo "  2. nano config/settings.yaml"
echo "  3. cd docker && docker compose up chronoscalp-paper-oanda -d"
echo "  4. docker compose logs -f chronoscalp-paper-oanda"
