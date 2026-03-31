from pydantic_settings import BaseSettings

class CoreSettings(BaseSettings):
    """Base infrastructure settings for Polymarket bots."""
    polymarket_base_url: str = "https://clob.polymarket.com"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_data_url: str = "https://data-api.polymarket.com"
    polymarket_timeout_seconds: int = 10

    database_url: str = "sqlite:///./polymarket.db"
    database_pool_size: int = 10

    log_level: str = "INFO"
    log_file: str | None = None

    app_mode: str = "PAPER"
    
    binance_ws_url: str = "wss://stream.binance.com:9443/stream"
    binance_rest_url: str = "https://api.binance.com/api/v3"

    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""
    polymarket_funder_address: str = ""
    polymarket_signature_type: int = 2
    wallet_private_key: str = ""

    polygon_rpc_url: str = "https://polygon.drpc.org"
    ctf_contract_address: str = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    usdc_token_address: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    stop_loss_enabled: bool = False
    stop_loss_pct: float = 0.05
    stop_loss_confirmation_count: int = 3
    max_position_size_usdc: float = 1.0
    compounding_enabled: bool = False
    compounding_percentage: float = 0.90

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

settings = CoreSettings()
