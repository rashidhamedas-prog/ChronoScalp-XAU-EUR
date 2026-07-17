# Runs scripts/run_backtest.py or a Linux-native broker (e.g. a future OANDA
# REST implementation) inside Docker. Does NOT run scripts/run_live.py against
# MT5 — the MetaTrader5 package requires a Windows host with the MT5 terminal
# installed, which cannot run inside this Linux container. See
# docs/ARCHITECTURE.md "Broker abstraction" for the deployment options.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app/src
ENV LOG_LEVEL=INFO

# Default: run a backtest. Override CMD for other entry points, e.g.
#   docker run chronoscalp python scripts/run_backtest.py --symbol XAUUSD
CMD ["python", "scripts/run_backtest.py", "--symbol", "XAUUSD"]
