import asyncio
import math
import time
from datetime import datetime, timezone
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

    async def execute_entry(self, trade: Trade, order: Order, price: float, shares: float) -> bool:
        if settings.app_mode == "PAPER":
            logger.info(f"TradingService | SIMULATING ENTRY | {trade.id} | {shares} @ {price}")
            order.id = f"FAKE_{int(datetime.now(timezone.utc).timestamp())}"
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
            # Calculate aggressive price using percentage-based slippage
            slippage = settings.execution_slippage_pct
            aggressive_price = round(price * (1 + slippage), 4)
            aggressive_price = min(0.99, max(0.01, aggressive_price))
            
            logger.info(f"TradingService | Placing GTC Order | {trade.id} | Base: {price} | Aggressive: {aggressive_price} | Slippage: {slippage:.1%}")
            
            res = await self._client.place_limit_order(trade.token_id, trade.outcome.value, aggressive_price, shares, "BUY", "GTC")
            order_id = res.get('orderID')
            if not order_id:
                logger.error(f"TradingService | Order submission failed: {res}")
                trade.status = TradeStatus.CANCELLED
                order.status = OrderStatus.CANCELLED
                return False
                
            order.id = order_id
            
            # Wait-for-Fill Loop
            timeout = settings.execution_timeout_sec
            start_time = time.time()
            filled_shares = 0.0
            last_status = "PENDING"
            
            while time.time() - start_time < timeout:
                try:
                    status_res = await self._client.get_order_status(order_id)
                    last_status = status_res.get("status", "").upper()
                    filled_shares = float(status_res.get("size_matched", 0))
                    
                    if last_status == "FILLED":
                        logger.info(f"TradingService | Order FILLED | {trade.id} | Shares: {filled_shares}")
                        break
                    
                    if last_status in ["CANCELED", "CANCELLED", "EXPIRED"]:
                        logger.warning(f"TradingService | Order {last_status} externally | {trade.id}")
                        break
                        
                    await asyncio.sleep(1.0)
                except Exception as e:
                    logger.warning(f"TradingService | Status check failed for {order_id}: {e}")
                    await asyncio.sleep(1.0)

            # If still open after timeout, cancel remaining
            if last_status not in ["FILLED", "CANCELED", "CANCELLED", "EXPIRED"]:
                logger.info(f"TradingService | Timeout reached. Cancelling remaining for {trade.id} (Filled: {filled_shares})")
                await self._client.cancel_order(order_id)
                # Final check after cancellation
                try:
                    status_res = await self._client.get_order_status(order_id)
                    filled_shares = float(status_res.get("size_matched", filled_shares))
                except: pass

            if filled_shares > 0:
                is_full_fill = abs(filled_shares - shares) < 1e-6
                order.status = OrderStatus.FILLED if is_full_fill else OrderStatus.PARTIALLY_FILLED
                order.filled_price = aggressive_price
                order.shares = filled_shares
                order.filled_at = datetime.now(timezone.utc).replace(tzinfo=None)
                
                trade.shares = filled_shares
                trade.entry_price = aggressive_price
                trade.entry_cost_usdc = filled_shares * aggressive_price
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
            trade.status = TradeStatus.CLOSED if reason != "STOP_LOSS" else TradeStatus.STOPPED_OUT
            trade.exit_reason = reason
            
            self._order_repo.save(exit_order)
            self._trade_repo.save(trade)
            return True

        try:
            res = await self._client.place_limit_order(trade.token_id, trade.outcome.value, exit_price, shares, "SELL", "FAK")
            order_id = res.get('orderID')
            exit_order.id = order_id
            
            await asyncio.sleep(2)
            
            status_res = await self._client.get_order_status(order_id)
            status = status_res.get("status", "").upper()
            
            if status in ["FILLED", "PARTIALLY_FILLED", "LIVE"]:
                exit_order.status = OrderStatus.FILLED
                exit_order.filled_price = exit_price
                exit_order.filled_at = datetime.now(timezone.utc).replace(tzinfo=None)
                
                entry_price = float(trade.entry_price) if trade.entry_price is not None else exit_price
                pnl = (exit_price - entry_price) * shares
                trade.exit_price = exit_price
                trade.total_pnl_usdc = pnl
                trade.status = TradeStatus.CLOSED if reason != "STOP_LOSS" else TradeStatus.STOPPED_OUT
                trade.exit_reason = reason
                
                self._order_repo.save(exit_order)
                self._trade_repo.save(trade)
                return True
            
            return False
        except Exception as e:
            logger.error(f"TradingService | Exit failed for {trade.id}: {e}")
            return False

    async def evaluate_stop_loss(self, trade: Trade, mid_price: float, bid_price: float | None = None) -> bool:
        if not settings.stop_loss_enabled or not trade.entry_price or trade.shares <= 0:
            return False

        sl_price = trade.entry_price * (1 - settings.stop_loss_pct)
        trigger_p = bid_price if bid_price is not None else mid_price

        if trigger_p <= sl_price:
            count = self._sl_confirmation_map.get(trade.id, 0) + 1
            self._sl_confirmation_map[trade.id] = count
            
            if count >= settings.stop_loss_confirmation_count:
                logger.warning(
                    f"STOP LOSS TRIGGERED (Confirmed {count}/{settings.stop_loss_confirmation_count}) | "
                    f"{trade.id} | Entry: {trade.entry_price:.3f} | Current: {trigger_p:.3f} | Target SL: {sl_price:.3f}"
                )
                exit_p = max(0.01, round(bid_price - 0.005, 4)) if bid_price else round(mid_price - 0.01, 4)
                success = await self.execute_exit(trade, exit_p, reason="STOP_LOSS")
                if success:
                    self._sl_confirmation_map.pop(trade.id, None)
                return success
            else:
                logger.info(
                    f"STOP LOSS PENDING ({count}/{settings.stop_loss_confirmation_count}) | "
                    f"{trade.id} | Current: {trigger_p:.3f} | Target SL: {sl_price:.3f}"
                )
        else:
            if trade.id in self._sl_confirmation_map:
                self._sl_confirmation_map[trade.id] = 0
            
        return False

    def get_valid_order_size(self, usdc: float, price: float):
        usdc_val = round(float(usdc), 2)
        base_price = round(float(price), 4)

        for p_adj in [0, 0.0001, -0.0001, 0.0002, -0.0002]:
            adj_price = round(base_price + p_adj, 4)
            if adj_price <= 0: continue
            
            shares = round(usdc_val / adj_price, 4)
            for i in range(100):
                test_shares = round(shares - (i * 0.0001), 4)
                if test_shares <= 0: break
                
                maker = float(test_shares * adj_price)
                if abs(maker - round(maker, 2)) < 1e-9:
                    return round(maker, 2), test_shares, adj_price
        
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

