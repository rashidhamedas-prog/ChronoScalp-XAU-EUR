"""MetaTrader5 broker implementation. Windows-only — see
docs/ARCHITECTURE.md and chronoscalp.data.mt5_connector for details.
"""

from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.data.mt5_connector import MT5Connector, _require_windows
from chronoscalp.execution.mt5_utils import (
    CHRONOSCALP_MAGIC,
    StaleStopsError,
    fetch_closed_position_pnl,
    find_managed_position_ticket,
    order_comment_for_signal,
    resolve_order_filling_mode,
    sanitize_mt5_comment,
    scale_volume_to_free_margin,
    spread_points_to_pips,
    validate_fill_vs_signal_entry,
    validate_min_stop_distance,
    validate_stops_vs_fill_price,
)
from chronoscalp.logging_setup import logger
from chronoscalp.utils.strategy_tags import resolve_strategy_tag, strategy_from_comment
from chronoscalp.utils.types import (
    PendingOrder,
    PendingOrderSide,
    Position,
    Quote,
    Signal,
    SignalType,
    TradeResult,
)


class MT5Broker:
    """Implements the `Broker` protocol (execution/broker.py) against a real
    or demo MT5 account. Requires a Windows host with the MT5 terminal
    installed and logged in (see .env.example: MT5_LOGIN/MT5_PASSWORD/MT5_SERVER)."""

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        terminal_path: str = "",
        connector: MT5Connector | None = None,
        symbols_cfg: dict | None = None,
        magic: int = CHRONOSCALP_MAGIC,
    ) -> None:
        self._connector = connector or MT5Connector(login, password, server, terminal_path)
        self._owns_connector = connector is None
        self._symbols_cfg = symbols_cfg or {}
        self._magic = magic

    def connect(self) -> bool:
        if self._connector.is_connected:
            return True
        if self._owns_connector:
            return self._connector.connect()
        return self._connector.is_connected

    def get_balance(self) -> float:
        _require_windows()
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        return float(info.equity)

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        return self.get_managed_positions(symbol=symbol)

    def get_account_positions(self, symbol: str | None = None) -> list[Position]:
        """All open account positions (no magic filter) — for operator display."""
        return self._positions_from_mt5(symbol=symbol, magic=None)

    def get_managed_positions(self, symbol: str | None = None) -> list[Position]:
        """Open positions placed by this bot (filtered by magic number)."""
        return self._positions_from_mt5(symbol=symbol, magic=self._magic)

    def _positions_from_mt5(
        self, *, symbol: str | None = None, magic: int | None
    ) -> list[Position]:
        _require_windows()
        import MetaTrader5 as mt5

        raw_positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if raw_positions is None:
            return []

        positions: list[Position] = []
        for p in raw_positions:
            if magic is not None and int(getattr(p, "magic", 0) or 0) != magic:
                continue
            positions.append(
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    direction=(
                        SignalType.BUY if p.type == mt5.POSITION_TYPE_BUY else SignalType.SELL
                    ),
                    volume=p.volume,
                    entry_price=p.price_open,
                    stop_loss=p.sl,
                    take_profit=p.tp,
                    open_time=datetime.fromtimestamp(p.time, tz=UTC),
                    strategy=strategy_from_comment(str(getattr(p, "comment", "") or "")),
                )
            )
        return positions

    def snapshot_account_summary(self) -> dict:
        """Account login/equity/margin for operator display (Telegram empty-state)."""
        _require_windows()
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is None:
            return {}
        return {
            "login": int(info.login),
            "server": str(getattr(info, "server", "") or ""),
            "balance": float(info.balance),
            "equity": float(info.equity),
            "margin": float(info.margin),
            "profit": float(getattr(info, "profit", 0.0) or 0.0),
        }

    def snapshot_account_positions(self, symbol: str | None = None) -> list[dict]:
        """Rich open-position rows for Telegram/dashboard (includes profit/magic)."""
        _require_windows()
        import MetaTrader5 as mt5

        raw_positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if raw_positions is None:
            return []

        rows: list[dict] = []
        for p in raw_positions:
            direction = "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell"
            rows.append(
                {
                    "ticket": int(p.ticket),
                    "symbol": str(p.symbol),
                    "direction": direction,
                    "volume": float(p.volume),
                    "entry_price": float(p.price_open),
                    "stop_loss": float(p.sl or 0.0),
                    "take_profit": float(p.tp or 0.0),
                    "profit": float(getattr(p, "profit", 0.0) or 0.0),
                    "magic": int(getattr(p, "magic", 0) or 0),
                    "comment": str(getattr(p, "comment", "") or ""),
                    "strategy": strategy_from_comment(str(getattr(p, "comment", "") or "")),
                    "open_time": datetime.fromtimestamp(p.time, tz=UTC).isoformat(),
                }
            )
        return rows

    def get_current_spread_pips(self, symbol: str) -> float:
        spread_points = self._connector.current_spread_points(symbol)
        if spread_points is None:
            return float("inf")

        spec = self._symbols_cfg.get(symbol, {})
        pip_size = float(spec.get("pip_size", 0.0))
        if pip_size <= 0:
            logger.warning(
                "No pip_size for {} in symbols.yaml — returning raw spread points", symbol
            )
            return float(spread_points)

        point = self._connector.symbol_point(symbol)
        if point is None or point <= 0:
            logger.warning("Could not read MT5 point for {} — returning raw spread points", symbol)
            return float(spread_points)

        return spread_points_to_pips(float(spread_points), point, pip_size)

    def get_quote(self, symbol: str) -> Quote | None:
        _require_windows()
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return Quote(
            symbol=symbol,
            bid=float(tick.bid),
            ask=float(tick.ask),
            time=(
                datetime.fromtimestamp(float(getattr(tick, "time", 0) or 0), tz=UTC)
                if getattr(tick, "time", 0)
                else datetime.now(tz=UTC)
            ),
        )

    def place_pending_stop(
        self,
        *,
        symbol: str,
        side: PendingOrderSide,
        volume: float,
        price: float,
        stop_loss: float,
        take_profit: float,
        expiration: datetime | None = None,
        comment: str = "",
    ) -> PendingOrder:
        _require_windows()
        import MetaTrader5 as mt5

        order_type = (
            mt5.ORDER_TYPE_BUY_STOP
            if side == PendingOrderSide.BUY_STOP
            else mt5.ORDER_TYPE_SELL_STOP
        )
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol_info failed for {symbol}: {mt5.last_error()}")

        request: dict = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "sl": float(stop_loss),
            "tp": float(take_profit),
            "magic": self._magic,
            "comment": sanitize_mt5_comment(comment or "CS_News"),
            "type_filling": resolve_order_filling_mode(symbol),
        }
        if expiration is not None:
            request["type_time"] = mt5.ORDER_TIME_SPECIFIED
            request["expiration"] = int(expiration.timestamp())
        else:
            request["type_time"] = mt5.ORDER_TIME_GTC

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(
                f"MT5 pending order_send failed: result={result} last_error={mt5.last_error()} "
                f"symbol={symbol} side={side.value} price={price}"
            )
        ticket = int(result.order)
        logger.info(
            "Pending placed: {} {} vol={} @ {} ticket={}",
            symbol,
            side.value,
            volume,
            price,
            ticket,
        )
        return PendingOrder(
            ticket=ticket,
            symbol=symbol,
            side=side,
            volume=float(volume),
            price=float(price),
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            comment=sanitize_mt5_comment(comment or "CS_News"),
            expiration=expiration,
        )

    def cancel_pending_order(self, ticket: int) -> bool:
        _require_windows()
        import MetaTrader5 as mt5

        request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        if not ok:
            logger.warning("cancel_pending_order failed ticket={}: {}", ticket, result)
        return ok

    def get_pending_orders(
        self, symbol: str | None = None, comment_prefix: str | None = None
    ) -> list[PendingOrder]:
        _require_windows()
        import MetaTrader5 as mt5

        raw = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
        if raw is None:
            return []
        out: list[PendingOrder] = []
        for order in raw:
            if self._magic and int(getattr(order, "magic", 0) or 0) != self._magic:
                continue
            comment = str(getattr(order, "comment", "") or "")
            if comment_prefix and not comment.startswith(comment_prefix):
                continue
            otype = int(order.type)
            if otype == mt5.ORDER_TYPE_BUY_STOP:
                side = PendingOrderSide.BUY_STOP
            elif otype == mt5.ORDER_TYPE_SELL_STOP:
                side = PendingOrderSide.SELL_STOP
            else:
                continue
            exp_raw = int(getattr(order, "time_expiration", 0) or 0)
            expiration = datetime.fromtimestamp(exp_raw, tz=UTC) if exp_raw > 0 else None
            out.append(
                PendingOrder(
                    ticket=int(order.ticket),
                    symbol=str(order.symbol),
                    side=side,
                    volume=float(order.volume_current),
                    price=float(order.price_open),
                    stop_loss=float(order.sl),
                    take_profit=float(order.tp),
                    comment=comment,
                    expiration=expiration,
                )
            )
        return out

    def place_order(self, signal: Signal, volume: float) -> Position:
        _require_windows()
        import MetaTrader5 as mt5

        order_type = (
            mt5.ORDER_TYPE_BUY if signal.signal_type == SignalType.BUY else mt5.ORDER_TYPE_SELL
        )
        tick = mt5.symbol_info_tick(signal.symbol)
        if tick is None:
            raise RuntimeError(f"No tick data for {signal.symbol}: {mt5.last_error()}")
        price = tick.ask if signal.signal_type == SignalType.BUY else tick.bid
        validate_fill_vs_signal_entry(
            fill_price=float(price),
            signal_entry=float(signal.entry_price),
            stop_loss=float(signal.stop_loss),
        )
        validate_stops_vs_fill_price(
            is_buy=signal.signal_type == SignalType.BUY,
            fill_price=float(price),
            stop_loss=float(signal.stop_loss),
            take_profit=float(signal.take_profit),
        )
        info = mt5.symbol_info(signal.symbol)
        if info is not None:
            stops_points = float(getattr(info, "trade_stops_level", 0) or 0)
            point = float(getattr(info, "point", 0) or 0)
            validate_min_stop_distance(
                fill_price=float(price),
                stop_loss=float(signal.stop_loss),
                take_profit=float(signal.take_profit),
                min_distance=stops_points * point,
            )

        # Fit volume inside free margin instead of letting MT5 bounce "No money".
        account = mt5.account_info()
        required = None
        try:
            required = mt5.order_calc_margin(order_type, signal.symbol, float(volume), float(price))
        except Exception:  # noqa: BLE001 - older builds may lack order_calc_margin
            required = None
        if account is not None and required is not None and required > 0:
            adjusted = scale_volume_to_free_margin(
                volume=float(volume),
                required_margin=float(required),
                free_margin=float(getattr(account, "margin_free", 0.0) or 0.0),
                volume_step=float(getattr(info, "volume_step", 0.01) or 0.01) if info else 0.01,
                volume_min=float(getattr(info, "volume_min", 0.01) or 0.01) if info else 0.01,
            )
            if adjusted <= 0:
                raise StaleStopsError(
                    f"{signal.symbol}: even minimum volume does not fit free margin "
                    f"(required={required:.2f} free={getattr(account, 'margin_free', 0.0):.2f})"
                )
            if adjusted < float(volume):
                logger.warning(
                    "Volume reduced to fit margin: {} {:.2f} -> {:.2f} lots",
                    signal.symbol,
                    float(volume),
                    adjusted,
                )
                volume = adjusted

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": signal.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "deviation": 10,
            "magic": self._magic,
            "comment": order_comment_for_signal(signal),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": resolve_order_filling_mode(signal.symbol),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            last_err = mt5.last_error()
            raise RuntimeError(
                f"MT5 order_send failed: result={result} last_error={last_err} "
                f"symbol={signal.symbol} volume={volume} type_filling={request.get('type_filling')}"
            )

        ticket = find_managed_position_ticket(signal.symbol, magic=self._magic)
        if ticket is None:
            raise RuntimeError(
                f"Order reported done but no managed position found for {signal.symbol} "
                f"(magic={self._magic})"
            )

        logger.info(
            "Order placed: {} {} vol={} @ {} ticket={}",
            signal.symbol,
            signal.signal_type.value,
            volume,
            price,
            ticket,
        )
        return Position(
            ticket=ticket,
            symbol=signal.symbol,
            direction=signal.signal_type,
            volume=volume,
            entry_price=price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            open_time=datetime.now(tz=UTC),
            initial_volume=volume,
            initial_stop_loss=signal.stop_loss,
            strategy=resolve_strategy_tag(
                explicit=signal.strategy, reason=signal.reason
            ),
        )

    def modify_sl_tp(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        _require_windows()
        import MetaTrader5 as mt5

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning("modify_sl_tp: no open position for ticket {}", ticket)
            return False
        position = positions[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": stop_loss,
            "tp": take_profit,
        }
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        if not ok:
            logger.warning("modify_sl_tp failed for ticket {}: {}", ticket, result)
        return ok

    def close_position(self, ticket: int) -> TradeResult:
        _require_windows()
        import MetaTrader5 as mt5

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise RuntimeError(f"No open position for ticket {ticket}")
        position = positions[0]

        tick = mt5.symbol_info_tick(position.symbol)
        close_price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask
        order_type = (
            mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "position": ticket,
            "price": close_price,
            "deviation": 10,
            "magic": self._magic,
            "comment": sanitize_mt5_comment("CS_close"),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": resolve_order_filling_mode(position.symbol),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 close order_send failed: {result}")

        direction = SignalType.BUY if position.type == mt5.POSITION_TYPE_BUY else SignalType.SELL
        pnl = float(position.profit)
        return TradeResult(
            symbol=position.symbol,
            direction=direction,
            entry_price=position.price_open,
            exit_price=close_price,
            volume=position.volume,
            open_time=datetime.fromtimestamp(position.time, tz=UTC),
            close_time=datetime.now(tz=UTC),
            pnl=pnl,
        )

    def close_partial(self, ticket: int, volume: float) -> TradeResult:
        _require_windows()
        import MetaTrader5 as mt5

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise RuntimeError(f"No open position for ticket {ticket}")
        position = positions[0]
        close_vol = min(float(volume), float(position.volume))
        if close_vol <= 0:
            raise ValueError("partial volume must be positive")

        tick = mt5.symbol_info_tick(position.symbol)
        close_price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask
        order_type = (
            mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        )
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": close_vol,
            "type": order_type,
            "position": ticket,
            "price": close_price,
            "deviation": 10,
            "magic": self._magic,
            "comment": sanitize_mt5_comment("CS_partial"),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": resolve_order_filling_mode(position.symbol),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 partial close failed: {result}")

        direction = SignalType.BUY if position.type == mt5.POSITION_TYPE_BUY else SignalType.SELL
        return TradeResult(
            symbol=position.symbol,
            direction=direction,
            entry_price=position.price_open,
            exit_price=close_price,
            volume=close_vol,
            open_time=datetime.fromtimestamp(position.time, tz=UTC),
            close_time=datetime.now(tz=UTC),
            pnl=float(getattr(result, "profit", 0.0) or 0.0),
            exit_reason="partial_tp",
        )

    def fetch_closed_pnl(self, ticket: int) -> float | None:
        """Realized P&L after the position was closed externally (SL/TP on broker)."""
        return fetch_closed_position_pnl(ticket)
