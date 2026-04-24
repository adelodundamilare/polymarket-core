import json
import os
from pathlib import Path
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

from polymarket_core.db.repositories.trade_repo import TradeRepository

class PaperWalletService:
    @staticmethod
    def calculate_balance(initial_equity: float, trade_repo: TradeRepository) -> float:
        """
        Calculates current paper balance based on:
        initial_equity + total_pnl (from resolved trades) - entry_cost (of active trades)
        """
        # total_pnl_usdc should already account for the "resolved" result.
        # However, for ACTIVE trades, the cost is already spent from the wallet.
        pnl = trade_repo.get_paper_pnl()
        active_cost = trade_repo.get_paper_active_cost()
        
        return initial_equity + pnl - active_cost
