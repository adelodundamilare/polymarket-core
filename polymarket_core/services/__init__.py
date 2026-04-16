from .trading_service import TradingService
from .market_data_service import MarketDataService
from .resolution_service import ResolutionService
from .indicator_service import IndicatorService

_services = {
    "trading": None,
    "market_data": None,
    "resolution": None
}

def initialize_library(client, trade_repo, order_repo, binance_client=None):
    """
    Initializes the global services singleton for the library.
    """
    global _services
    _services["trading"] = TradingService(client, order_repo, trade_repo)
    _services["market_data"] = MarketDataService(binance_client)
    _services["resolution"] = ResolutionService(client, trade_repo)

def _get_service(name: str):
    service = _services.get(name)
    if not service:
        raise RuntimeError(f"Core Library: {name} service not initialized. Call initialize_library() first.")
    return service

def get_trading_service() -> TradingService:
    return _get_service("trading")

def get_market_data_service() -> MarketDataService:
    return _get_service("market_data")

def get_resolution_service() -> ResolutionService:
    return _get_service("resolution")

# --- Trading Service Facade ---
async def execute_entry(trade, order, price, shares, order_type="FAK"):
    return await _get_service("trading").execute_entry(trade, order, price, shares, order_type=order_type)

async def execute_safe_entry(trade, order, target_usdc, signal_price, order_type="FAK"):
    return await _get_service("trading").execute_safe_entry(trade, order, target_usdc, signal_price, order_type=order_type)

def get_valid_order_size(usdc: float, price: float):
    return _get_service("trading").get_valid_order_size(usdc, price)

async def calculate_position_size():
    return await _get_service("trading").calculate_position_size()

# --- Market Data Service Facade ---
def get_token_id(market: dict, direction: str):
    return _get_service("market_data").get_token_id(market, direction)

def get_strike_price(market: dict):
    return _get_service("market_data").get_strike_price(market)

async def get_strike_price_async(market: dict):
    return await _get_service("market_data").get_strike_price_async(market)

def calculate_time_remaining(market: dict):
    return _get_service("market_data").calculate_time_remaining(market)

def calculate_market_age(market: dict):
    return _get_service("market_data").calculate_market_age(market)

async def get_active_market(coin: str):
    return await _get_service("market_data").get_active_market(coin)

async def get_token_price(client, token_id: str):
    return await _get_service("market_data").get_token_price(client, token_id)

async def get_price_and_volume(client, token_id: str):
    return await _get_service("market_data").get_price_and_volume(client, token_id)

async def get_market_data_bundle(client, market: dict, coin: str, yes_token: str):
    return await _get_service("market_data").get_market_data_bundle(client, market, coin, yes_token)

async def get_prices_for_markets(client, markets: dict[str, dict]):
    return await _get_service("market_data").get_prices_for_markets(client, markets)

def calculate_macro_trend(normalized_results: list[str], dominance_pct: float) -> str:
    return MarketDataService.calculate_macro_trend(normalized_results, dominance_pct)

def calculate_obi(alt_data: dict):
    return MarketDataService.calculate_obi(alt_data)

def calculate_obi_velocity(coin: str, current_obi: float):
    return _get_service("market_data").calculate_obi_velocity(coin, current_obi)

def calculate_fair_probability(spot: float, strike: float, time_rem_sec: float):
    return MarketDataService.calculate_fair_probability(spot, strike, time_rem_sec)

def check_liquidity(alt_data: dict, is_long: bool):
    return MarketDataService.check_liquidity(alt_data, is_long)

# --- Resolution Service Facade ---
def determine_winning_outcome(market: dict):
    return _get_service("resolution").determine_winning_outcome(market)

async def get_redeemable_condition_ids():
    return await _get_service("resolution").get_redeemable_condition_ids()

async def redeem_tokens(condition_id, is_paper=False):
    return await _get_service("resolution").redeem_tokens(condition_id, is_paper)

async def resolve_trade(trade, winning_outcome, market):
    return await _get_service("resolution").resolve_trade(trade, winning_outcome, market)

async def get_market_metrics(coin: str):
    return await IndicatorService.get_market_metrics(coin)
