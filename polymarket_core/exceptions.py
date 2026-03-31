class PolymarketScannerError(Exception):
    pass

class ConfigurationError(PolymarketScannerError):
    pass

class ExternalServiceError(PolymarketScannerError):
    pass

class PolymarketAPIError(ExternalServiceError):
    pass

class MarketNotFoundError(PolymarketAPIError):
    pass

class AnalysisError(PolymarketScannerError):
    pass
