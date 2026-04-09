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
            # We trust the price and shares passed in, as they should be pre-balanced
            # using get_valid_order_size to satisfy precision requirements.
            aggressive_price = round(price, 4)
            
            logger.info(f"TradingService | Placing {order_type} Order | {trade.id} | Price: {aggressive_price} | Shares: {shares}")
            
            res = await self._client.place_limit_order(trade.token_id, trade.outcome.value, aggressive_price, shares, "BUY", order_type)
            order_id = res.get('orderID')
            if not order_id:
                logger.error(f"TradingService | Order submission failed: {res}")
                trade.status = TradeStatus.CANCELLED
                order.status = OrderStatus.CANCELLED
                return False
                
            order.id = order_id
            
            # Brief wait for resolution
            wait_time = 1.0 if order_type == "FAK" else settings.execution_timeout_sec
            await asyncio.sleep(wait_time)
            
            try:
                status_res = await self._client.get_order_status(order_id)
                last_status = status_res.get("status", "").upper()
                filled_shares = float(status_res.get("size_matched", status_res.get("sizeMatched", 0)))
                
                if last_status == "FILLED":
                    logger.info(f"TradingService | {order_type} Order FILLED | {trade.id} | Shares: {filled_shares}")
                elif last_status in ["CANCELED", "CANCELLED", "EXPIRED"]:
                    logger.warning(f"TradingService | {order_type} Order {last_status} | {trade.id} | Filled: {filled_shares}")
            except Exception as e:
                logger.warning(f"TradingService | Status check failed for {order_id}: {e}")

            if last_status == "FILLED" and filled_shares == 0:
                filled_shares = shares

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

    async def execute_safe_entry(self, trade: Trade, order: Order, target_usdc: float, signal_price: float, order_type: str = "FAK") -> bool:
        """
        Consolidated, precision-safe entry.
        Applies slippage, balances the size/price product to avoid 400 errors, and executes.
        """
        try:
            # 1. Apply slippage
            slippage = settings.execution_slippage_pct
            aggressive_price = round(signal_price * (1 + slippage), 4)
            aggressive_price = min(0.99, max(0.01, aggressive_price))
            
            # 2. Balance for precision
            maker_amount, shares, final_price = self.get_valid_order_size(target_usdc, aggressive_price)
            
            if shares is None or shares <= 0:
                logger.error(f"TradingService | SAFE_ENTRY | Could not balance size for {target_usdc} USDC at {aggressive_price}")
                return False
                
            # 3. Execute
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


    def get_valid_order_size(self, usdc: float, price: float):
        """
        Robust search for a (Shares, Price) pair that satisfies Polymarket's 2-decimal USDC rule.
        Prioritizes the highest valid amount LESS THAN OR EQUAL TO the target usdc.
        """
        target_k = int(round(usdc * 100))
        base_p = round(price, 4)
        
        # Try finding a solution for a range of "cents" starting from target downwards (max 10% lower)
        # We search downwards because the user prefers lower amounts over exceeding target
        cents_range = range(target_k, max(0, int(target_k * 0.9)) - 1, -1)
        
        for k in cents_range:
            maker_target = k / 100.0
            
            # Initial estimate for shares
            shares_est = round(maker_target / base_p, 4)
            
            # Try a range of shares around the estimate
            # We check both directions because a small price nudge in either direction might balance it
            for s_offset_ticks in range(500):
                for sign in [1, -1]:
                    if s_offset_ticks == 0 and sign == -1: continue
                    
                    s = round(shares_est + (sign * s_offset_ticks * 0.0001), 4)
                    if s <= 0: continue
                    
                    # Resulting price P = Maker / S
                    p = round(maker_target / s, 4)
                    if p <= 0 or p > 0.99: continue
                    
                    # Verify this price and share combo produces EXACTLY the target 2-decimal maker amount
                    # Floating point precision safety: use round and epsilon
                    calc_maker = round(s * p, 2)
                    if abs((s * p) - calc_maker) < 1e-9:
                        # Success! Now check if the price nudge is within acceptable slippage (1%)
                        if abs(p - base_p) / base_p <= 0.01:
                            return calc_maker, s, p
                            
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

