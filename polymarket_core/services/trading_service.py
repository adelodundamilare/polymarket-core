import asyncio
import math
import time
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from math import gcd
from polymarket_core.config import settings
from polymarket_core.core.models import Order, OrderSide, OrderStatus, OrderType, Trade, TradeStatus
from polymarket_core.db.repositories.order_repo import OrderRepository
from polymarket_core.db.repositories.trade_repo import TradeRepository
from polymarket_core.external.polymarket.client import PolymarketClient
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

class TradingService:
    def __init__(self, client: PolymarketClient, order_repo: OrderRepository, trade_repo: TradeRepository) -> None:
        self._client = client
        self._order_repo = order_repo
        self._trade_repo = trade_repo
        self._sl_confirmation_map: dict[str, int] = {}

    async def execute_entry(self, trade: Trade, order: Order, price: float, shares: float, order_type: str = "FAK") -> bool:
        if settings.app_mode == "PAPER":
            logger.info(f"TradingService | SIMULATING ENTRY | {trade.id} | {shares} @ {price} | Type: {order_type}")
            order.id = f"FAKE_{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
            order.status = OrderStatus.FILLED
            order.filled_price = price
            order.shares = shares
            order.filled_at = datetime.now(timezone.utc).replace(tzinfo=None)

            trade.shares = shares
            trade.entry_price = price
            trade.entry_cost_usdc = shares * price
            trade.status = TradeStatus.ACTIVE
            return True

        try:
            clean_price = float(Decimal(str(price)).quantize(Decimal("0.01")))
            clean_shares = float(Decimal(str(shares)).quantize(Decimal("0.01")))

            logger.info(f"TradingService | Placing {order_type} Order | {trade.id} | Price: {clean_price} | Shares: {clean_shares}")

            res = await self._client.place_limit_order(trade.token_id, trade.outcome.value, clean_price, clean_shares, "BUY", order_type)
            order_id = res.get('orderID')
            if not order_id:
                logger.error(f"TradingService | Order submission failed: {res}")
                trade.status = TradeStatus.CANCELLED
                order.status = OrderStatus.CANCELLED
                return False

            order.id = order_id

            wait_time = 1.0 if order_type == "FAK" else settings.execution_timeout_sec
            await asyncio.sleep(wait_time)

            last_status = ""
            filled_shares = 0.0

            try:
                status_res = await self._client.get_order_status(order_id)
                last_status = status_res.get("status", "").upper()
                filled_shares = float(status_res.get("size_matched", status_res.get("sizeMatched", 0)))

                if last_status == "FILLED":
                    logger.info(f"TradingService | {order_type} Order FILLED | {trade.id} | Shares: {filled_shares}")
                elif last_status == "PARTIALLY_FILLED":
                    logger.info(f"TradingService | {order_type} Order PARTIALLY_FILLED | {trade.id} | Shares: {filled_shares}")
                elif last_status in ["CANCELED", "CANCELLED", "EXPIRED"]:
                    logger.warning(f"TradingService | {order_type} Order {last_status} | {trade.id} | Filled: {filled_shares}")
            except Exception as e:
                logger.warning(f"TradingService | Status check failed for {order_id}: {e}")

            if last_status == "FILLED" and filled_shares == 0:
                filled_shares = shares

            if filled_shares > 0:
                is_full_fill = abs(filled_shares - shares) < 1e-6
                order.status = OrderStatus.FILLED if is_full_fill else OrderStatus.PARTIALLY_FILLED
                order.filled_price = clean_price
                order.shares = filled_shares
                order.filled_at = datetime.now(timezone.utc).replace(tzinfo=None)

                trade.shares = filled_shares
                trade.entry_price = clean_price
                trade.entry_cost_usdc = filled_shares * clean_price
                trade.status = TradeStatus.ACTIVE
                logger.info(f"TradingService | Execution Complete | {trade.id} | Status: {order.status} | Final Shares: {filled_shares}")
                return True
            else:
                logger.warning(f"TradingService | Order failed to fill | {trade.id} | Last Status: {last_status}")
                trade.status = TradeStatus.CANCELLED
                order.status = OrderStatus.CANCELLED
                return False
        except Exception as e:
            logger.error(f"TradingService | Entry failed for {trade.id}: {e}")
            trade.status = TradeStatus.CANCELLED
            order.status = OrderStatus.CANCELLED
            return False

    async def execute_safe_entry(self, trade: Trade, order: Order, target_usdc: float, signal_price: float, order_type: str = "FAK") -> bool:
        try:
            slippage = settings.execution_slippage_pct
            aggressive_price = round(signal_price * (1 + slippage), 2)
            aggressive_price = min(0.99, max(0.01, aggressive_price))

            maker_amount, shares, final_price = self.get_valid_order_size(target_usdc, aggressive_price)

            if shares is None or shares <= 0:
                logger.error(f"TradingService | SAFE_ENTRY | Could not balance size for {target_usdc} USDC at {aggressive_price}")
                return False

            return await self.execute_entry(trade, order, final_price, shares, order_type=order_type)
        except Exception as e:
            logger.error(f"TradingService | SAFE_ENTRY | Error: {e}")
            return False

    async def execute_exit(self, trade: Trade, exit_price: float, reason: str = "STOP_LOSS") -> bool:
        logger.info(f"TradingService | EXIT INITIATED | {trade.id} | Reason: {reason} | Price: {exit_price}")

        shares = trade.shares
        if shares <= 0:
            return False

        exit_order = Order(
            id=f"{trade.id}_exit_{int(time.time())}",
            trade_id=trade.id,
            order_type=OrderType.EXIT,
            side=OrderSide.SELL,
            shares=shares,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            token_id=trade.token_id
        )

        if settings.app_mode == "PAPER":
            exit_order.status = OrderStatus.FILLED
            exit_order.filled_price = exit_price
            exit_order.filled_at = datetime.now(timezone.utc).replace(tzinfo=None)

            entry_price = float(trade.entry_price) if trade.entry_price is not None else exit_price
            pnl = (exit_price - entry_price) * shares

            trade.exit_price = exit_price
            trade.total_pnl_usdc = pnl
            if pnl > 0.001:
                trade.status = TradeStatus.RESOLVED_WIN
            else:
                trade.status = TradeStatus.RESOLVED_LOSS
            trade.exit_reason = reason

            self._order_repo.save(exit_order)
            self._trade_repo.save(trade)
            return True

        try:
            raw_usdc = round(shares * exit_price, 2)
            maker_amount, clean_shares, clean_price = self.get_valid_order_size(raw_usdc, exit_price)

            if clean_shares is None:
                logger.error(f"TradingService | Could not balance exit size for {trade.id}")
                return False

            res = await self._client.place_limit_order(trade.token_id, trade.outcome.value, clean_price, clean_shares, "SELL", "FAK")
            order_id = res.get('orderID')
            exit_order.id = order_id

            await asyncio.sleep(2)

            status_res = await self._client.get_order_status(order_id)
            status = status_res.get("status", "").upper()

            if status in ["FILLED", "PARTIALLY_FILLED", "LIVE"]:
                exit_order.status = OrderStatus.FILLED
                exit_order.filled_price = clean_price
                exit_order.filled_at = datetime.now(timezone.utc).replace(tzinfo=None)

                entry_price = float(trade.entry_price) if trade.entry_price is not None else clean_price
                pnl = (clean_price - entry_price) * clean_shares
                trade.exit_price = clean_price
                trade.total_pnl_usdc = pnl

                if pnl > 0.001:
                    trade.status = TradeStatus.RESOLVED_WIN
                else:
                    trade.status = TradeStatus.RESOLVED_LOSS

                trade.exit_reason = reason

                self._order_repo.save(exit_order)
                self._trade_repo.save(trade)
                return True

            return False
        except Exception as e:
            logger.error(f"TradingService | Exit failed for {trade.id}: {e}")
            return False

    def get_valid_order_size(self, usdc: float, price: float):
        try:
            price_dec = Decimal(str(round(price, 2)))
            price_int = int(price_dec * 100)

            target_usdc_int = int(Decimal(str(round(usdc, 2))) * 10000)

            g = gcd(price_int, 100)
            step = 100 // g

            max_shares_int = target_usdc_int // price_int
            valid_shares_int = (max_shares_int // step) * step

            if valid_shares_int <= 0:
                logger.warning(f"TradingService | get_valid_order_size | No valid share size for usdc={usdc} price={price}")
                return None, None, None

            shares = Decimal(valid_shares_int) / Decimal(100)
            actual_usdc = shares * price_dec

            logger.debug(f"TradingService | get_valid_order_size | shares={shares} price={price_dec} usdc={actual_usdc}")
            return float(actual_usdc), float(shares), float(price_dec)
        except Exception as e:
            logger.error(f"TradingService | get_valid_order_size error: {e}")
            return None, None, None

    async def calculate_position_size(self) -> float:
        try:
            balance_data = await self._client.get_balance()
            available = max(0, float(balance_data.get("balance", 0)) - self._trade_repo.get_total_active_cost())
            if settings.compounding_enabled and available > 0:
                return math.floor((available * settings.compounding_percentage - 0.01) * 100) / 100
            return settings.max_position_size_usdc
        except Exception:
            return settings.max_position_size_usdc