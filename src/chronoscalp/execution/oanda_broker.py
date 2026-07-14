"""OANDA v20 REST broker — Linux-native live execution.

Implements the ``Broker`` protocol via HTTPS only (no MetaTrader5). Suitable
for deployment on a Netherlands / Amsterdam Linux VPS — see docs/DEPLOY_NL_VPS.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

import requests

from chronoscalp.execution.oanda_utils import (
    api_base_url,
    signed_units,
    spread_pips_from_prices,
    to_chronoscalp_symbol,
    to_instrument,
)
from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position, Signal, SignalType, TradeResult


class OANDABroker:
    """OANDA v20 REST implementation of ``execution/broker.py``."""

    def __init__(
        self,
        api_token: str,
        account_id: str,
        environment: str = "practice",
        symbols_cfg: dict | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._token = api_token.strip()
        self._account_id = account_id.strip()
        self._base_url = api_base_url(environment)
        self._symbols_cfg = symbols_cfg or {}
        self._timeout = timeout_seconds
        self._connected = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def connect(self) -> bool:
        if not self._token or not self._account_id:
            logger.error("OANDA broker connect failed: token and account id required")
            return False
        url = f"{self._base_url}/v3/accounts/{self._account_id}/summary"
        try:
            response = requests.get(url, headers=self._headers(), timeout=self._timeout)
        except requests.RequestException as exc:
            logger.error("OANDA broker connect failed: {}", exc)
            return False
        if response.status_code >= 400:
            logger.error(
                "OANDA broker connect HTTP {}: {}", response.status_code, response.text[:200]
            )
            return False
        self._connected = True
        logger.info("OANDABroker connected (account={})", self._account_id)
        return True

    def get_balance(self) -> float:
        url = f"{self._base_url}/v3/accounts/{self._account_id}/summary"
        response = requests.get(url, headers=self._headers(), timeout=self._timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"OANDA get_balance failed: HTTP {response.status_code}")
        data = response.json().get("account") or {}
        return float(data.get("NAV") or data.get("balance") or 0.0)

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        return self.get_managed_positions(symbol=symbol)

    def get_managed_positions(self, symbol: str | None = None) -> list[Position]:
        """All open trades on the account (single-bot deployment assumed)."""
        url = f"{self._base_url}/v3/accounts/{self._account_id}/openTrades"
        response = requests.get(url, headers=self._headers(), timeout=self._timeout)
        if response.status_code >= 400:
            logger.warning("OANDA openTrades failed: HTTP {}", response.status_code)
            return []

        trades = response.json().get("trades") or []
        positions: list[Position] = []
        for trade in trades:
            instrument = trade.get("instrument", "")
            sym = to_chronoscalp_symbol(instrument)
            if symbol is not None and sym != symbol:
                continue
            units = float(trade.get("currentUnits", 0))
            direction = SignalType.BUY if units > 0 else SignalType.SELL
            sl = trade.get("stopLossOrder") or {}
            tp = trade.get("takeProfitOrder") or {}
            open_time_raw = trade.get("openTime", "")
            try:
                open_time = datetime.fromisoformat(open_time_raw.replace("Z", "+00:00"))
            except ValueError:
                open_time = datetime.now(tz=UTC)

            positions.append(
                Position(
                    ticket=int(trade["id"]),
                    symbol=sym,
                    direction=direction,
                    volume=abs(units)
                    / float(self._symbols_cfg.get(sym, {}).get("contract_size", 1)),
                    entry_price=float(trade.get("price", 0)),
                    stop_loss=float(sl.get("price", 0)) if sl else 0.0,
                    take_profit=float(tp.get("price", 0)) if tp else 0.0,
                    open_time=open_time,
                )
            )
        return positions

    def get_current_spread_pips(self, symbol: str) -> float:
        instrument = to_instrument(symbol)
        url = f"{self._base_url}/v3/accounts/{self._account_id}/pricing"
        params = {"instruments": instrument}
        response = requests.get(url, headers=self._headers(), params=params, timeout=self._timeout)
        if response.status_code >= 400:
            logger.warning("OANDA pricing failed for {}: HTTP {}", symbol, response.status_code)
            return float("inf")

        prices = (response.json().get("prices") or [{}])[0]
        bids = prices.get("bids") or [{}]
        asks = prices.get("asks") or [{}]
        bid = float(bids[0].get("price", 0))
        ask = float(asks[0].get("price", 0))
        pip_size = float(self._symbols_cfg.get(symbol, {}).get("pip_size", 0.0001))
        return spread_pips_from_prices(bid, ask, pip_size)

    def place_order(self, signal: Signal, volume: float) -> Position:
        instrument = to_instrument(signal.symbol)
        units = signed_units(signal.symbol, volume, signal.signal_type, self._symbols_cfg)
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "stopLossOnFill": {"price": f"{signal.stop_loss:.5f}"},
                "takeProfitOnFill": {"price": f"{signal.take_profit:.5f}"},
            }
        }
        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders"
        response = requests.post(url, headers=self._headers(), json=payload, timeout=self._timeout)
        if response.status_code >= 400:
            raise RuntimeError(
                f"OANDA place_order failed: HTTP {response.status_code} {response.text[:300]}"
            )

        body = response.json()
        fill = body.get("orderFillTransaction") or body.get("orderCreateTransaction") or {}
        trade_opened = fill.get("tradeOpened") or {}
        ticket = int(trade_opened.get("tradeID") or fill.get("id") or 0)
        if ticket <= 0:
            raise RuntimeError(f"OANDA order filled but no trade ID in response: {body}")

        entry_price = float(fill.get("price", signal.entry_price))
        logger.info(
            "OANDA order placed: {} {} units={} @ {} ticket={}",
            signal.symbol,
            signal.signal_type.value,
            units,
            entry_price,
            ticket,
        )
        return Position(
            ticket=ticket,
            symbol=signal.symbol,
            direction=signal.signal_type,
            volume=volume,
            entry_price=entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            open_time=signal.timestamp if signal.timestamp else datetime.now(tz=UTC),
        )

    def modify_sl_tp(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        url = f"{self._base_url}/v3/accounts/{self._account_id}/trades/{ticket}/orders"
        payload = {
            "stopLoss": {"price": f"{stop_loss:.5f}", "timeInForce": "GTC"},
            "takeProfit": {"price": f"{take_profit:.5f}", "timeInForce": "GTC"},
        }
        response = requests.put(url, headers=self._headers(), json=payload, timeout=self._timeout)
        ok = response.status_code < 400
        if not ok:
            logger.warning(
                "OANDA modify_sl_tp failed for ticket {}: {}", ticket, response.text[:200]
            )
        return ok

    def close_position(self, ticket: int) -> TradeResult:
        trade_url = f"{self._base_url}/v3/accounts/{self._account_id}/trades/{ticket}"
        trade_resp = requests.get(trade_url, headers=self._headers(), timeout=self._timeout)
        if trade_resp.status_code >= 400:
            raise RuntimeError(f"OANDA trade {ticket} not found: HTTP {trade_resp.status_code}")
        trade = trade_resp.json().get("trade") or {}
        instrument = trade.get("instrument", "")
        sym = to_chronoscalp_symbol(instrument)
        units = float(trade.get("currentUnits", 0))
        direction = SignalType.BUY if units > 0 else SignalType.SELL
        entry_price = float(trade.get("price", 0))
        open_time_raw = trade.get("openTime", "")
        try:
            open_time = datetime.fromisoformat(open_time_raw.replace("Z", "+00:00"))
        except ValueError:
            open_time = datetime.now(tz=UTC)
        volume = abs(units) / float(self._symbols_cfg.get(sym, {}).get("contract_size", 1))

        url = f"{self._base_url}/v3/accounts/{self._account_id}/trades/{ticket}/close"
        response = requests.put(url, headers=self._headers(), json={}, timeout=self._timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"OANDA close_position failed: HTTP {response.status_code}")

        body = response.json()
        order_fill = body.get("orderFillTransaction") or {}
        trades_closed = order_fill.get("tradesClosed") or [{}]
        pnl = float(trades_closed[0].get("realizedPL", 0)) if trades_closed else 0.0
        exit_price = float(order_fill.get("price", 0))

        return TradeResult(
            symbol=sym,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            volume=volume,
            open_time=open_time,
            close_time=datetime.now(tz=UTC),
            pnl=pnl,
            exit_reason="manual",
        )

    def fetch_closed_pnl(self, ticket: int) -> float | None:
        """Best-effort realized P&L for a recently closed trade."""
        url = f"{self._base_url}/v3/accounts/{self._account_id}/trades/{ticket}"
        response = requests.get(url, headers=self._headers(), timeout=self._timeout)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            return None
        trade = response.json().get("trade") or {}
        return float(trade.get("realizedPL", 0))
