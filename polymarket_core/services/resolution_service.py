from datetime import datetime, timezone
import json
from polymarket_core.core.models import MarketOutcome, Trade, TradeStatus
from polymarket_core.db.repositories.trade_repo import TradeRepository
from polymarket_core.external.polymarket.client import PolymarketClient
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

from polymarket_core.config import settings
from polymarket_core.core.constants import WINNING_YES_VALUES, WINNING_NO_VALUES

class ResolutionService:
    def __init__(self, client: PolymarketClient, trade_repo: TradeRepository) -> None:
        self._client = client
        self._trade_repo = trade_repo

    async def resolve_trade(self, trade: Trade, winning_outcome: MarketOutcome, market: dict) -> None:
        is_win = (trade.outcome == winning_outcome)
        payout_price = 1.0 if is_win else 0.0
        pnl = (trade.shares * payout_price) - trade.entry_cost_usdc
        status = TradeStatus.RESOLVED_WIN if is_win else TradeStatus.RESOLVED_LOSS

        self._trade_repo.update_resolved(trade.id, status, pnl, exit_price=payout_price)
        
        # Sanity Check: If win but PnL is negative, it indicates a data corruption in shares/cost
        if is_win and pnl < -0.01:
            logger.critical(f"DATA_ERROR | Trade {trade.id} RESOLVED_WIN with NEGATIVE PnL ({pnl:.2f}) | Shares: {trade.shares} | Cost: {trade.entry_cost_usdc}")
        else:
            logger.info(f"Trade {trade.id} RESOLVED | {status.value} | PnL: {pnl:.2f}")
        
        # NOTE: Auto-redemption is globally disabled to save gas. 
        # Bulk redemption is handled by the Centralized RedemptionWorker.
        # if is_win:
        #     cid = market.get("conditionId") or market.get("condition_id")
        #     if cid:
        #         await self.redeem_tokens(cid, is_paper=trade.is_paper)

    def determine_winning_outcome(self, market: dict) -> MarketOutcome | None:
        try:
            prices_str = market.get("outcomePrices")
            uma_status = market.get("umaResolutionStatus")
            if prices_str and uma_status == "resolved":
                outcomes = json.loads(market.get("outcomes", "[]"))
                prices = json.loads(prices_str)
                if "1" in prices:
                    winner_index = prices.index("1")
                    return self._parse_outcome_text(outcomes[winner_index])
        except: pass

        resolved_answer = market.get("resolved_answer") or market.get("resolvedAnswer")
        if resolved_answer:
            return self._parse_outcome_text(str(resolved_answer))

        winning_outcome = market.get("winningOutcome") or market.get("winning_outcome")
        if winning_outcome:
            return self._parse_outcome_text(winning_outcome)

        status_outcome = market.get("outcome") if market.get("status") == "RESOLVED" else None
        if status_outcome:
            return self._parse_outcome_text(status_outcome)

    async def get_redeemable_condition_ids(self) -> list[str]:
        try:
            positions = await self._client.get_user_positions(self._client._address)
            return [p["conditionId"] for p in positions if float(p.get("size", 0)) > 0 and p.get("redeemable")]
        except Exception as e:
            logger.error(f"ResolutionService | Failed to fetch redeemable positions: {e}")
            return []

    async def redeem_tokens(self, condition_id: str, is_paper: bool = False) -> bool:
        if is_paper or settings.app_mode == "PAPER":
            logger.info(f"ResolutionService | Simulated redemption for paper trade {condition_id} (APP_MODE=PAPER)")
            return True
        try:
            res = await self._client.redeem_positions(condition_id)
            logger.info(f"ResolutionService | Redemption result for {condition_id}: {res}")
            return True
        except Exception as e:
            logger.error(f"ResolutionService | Redemption failed for {condition_id}: {e}")
            return False

    def _parse_outcome_text(self, text: str) -> MarketOutcome | None:
        t = text.lower()
        if t in WINNING_YES_VALUES: return MarketOutcome.YES
        if t in WINNING_NO_VALUES: return MarketOutcome.NO
        return None
