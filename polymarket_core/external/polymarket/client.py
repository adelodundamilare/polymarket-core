import asyncio
import httpx
import hmac
import hashlib
import time
import json
import base64
from typing import Optional
from polymarket_core.config import settings
from polymarket_core.exceptions import MarketNotFoundError, PolymarketAPIError
from polymarket_core.logger import get_logger
from polymarket_core.external.polymarket.signing import OrderSigner
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, BalanceAllowanceParams, AssetType


logger = get_logger(__name__)
class PolymarketClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None, api_passphrase: str | None = None) -> None:
        self._api_key = (api_key or settings.polymarket_api_key or "").strip().strip('"').strip("'")
        self._api_secret = (api_secret or settings.polymarket_api_secret or "").strip().strip('"').strip("'")
        self._api_passphrase = (api_passphrase or settings.polymarket_api_passphrase or "").strip().strip('"').strip("'")

        self._address = settings.polymarket_funder_address
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = httpx.Timeout(10.0)

        self._signer: Optional[OrderSigner] = None
        if settings.wallet_private_key:
            try:
                self._signer = OrderSigner(settings.wallet_private_key)
                if not self._address:
                    self._address = self._signer.address
            except Exception as e:
                pass

        if not all([self._api_key, self._api_secret, self._api_passphrase]):
            self._credentials_derived = False
        else:
            self._credentials_derived = True

    async def open(self) -> None:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "PolymarketClient":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        closed: bool = False,
    ) -> dict:
        if not self._client:
            raise PolymarketAPIError("Client not initialized (use async with)")

        url = f"{settings.polymarket_gamma_url}/events"
        params = {
            "limit": limit,
            "offset": offset,
            "closed": closed,
            "order": "id",
            "ascending": False,
        }

        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise PolymarketAPIError(f"Failed to fetch markets: {e}") from e
        except httpx.RequestError as e:
            raise PolymarketAPIError(f"Request failed: {e}") from e

    async def get_market(self, market_id: str) -> dict:
        if not self._client:
            raise PolymarketAPIError("Client not initialized (use async with)")

        if not market_id or not isinstance(market_id, str):
            raise ValueError(f"Invalid market_id: {market_id}")

        url = f"{settings.polymarket_base_url}/markets/{market_id}"

        try:
            response = await self._client.get(url)

            if response.status_code == 404:
                raise MarketNotFoundError(f"Market {market_id} not found")

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise PolymarketAPIError(
                f"Failed to fetch market {market_id}: {e}"
            ) from e
        except httpx.RequestError as e:
            raise PolymarketAPIError(f"Request failed: {e}") from e

    async def get_orderbook(self, token_id: str) -> dict:
        if not self._client:
            raise PolymarketAPIError("Client not initialized (use async with)")

        url = f"{settings.polymarket_base_url}/book"
        params = {"token_id": token_id, "_t": int(time.time() * 1000)}

        try:

            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise PolymarketAPIError(
                f"Failed to fetch orderbook for {token_id}: {e}"
            ) from e
        except httpx.RequestError as e:
            raise PolymarketAPIError(f"Request failed: {e}") from e

    async def get_midpoint(self, token_id: str) -> float | None:
        try:
            ob = await self.get_orderbook(token_id)
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            bid = float(bids[0]["price"]) if bids else None
            ask = float(asks[0]["price"]) if asks else None
            if bid is not None and ask is not None:
                return (bid + ask) / 2
            return bid or ask
        except:
            return None

    async def place_limit_order(
        self,
        market_id: str,
        outcome: str,
        price: float,
        size: float,
        side: str = "BUY",
        order_type: str = "FAK",
    ) -> dict:
        await self.ensure_credentials()

        creds = ApiCreds(
            api_key=self._api_key,
            api_secret=self._api_secret,
            api_passphrase=self._api_passphrase
        )

        sdk_client = ClobClient(
            host=settings.polymarket_base_url,
            key=settings.wallet_private_key,
            chain_id=137,
            creds=creds,
            signature_type=2,
            funder=self._address
        )

        try:
            logger.info(f"SDK Submission | Token: {market_id} | Price: {price} | Size: {size} | Side: {side} | Type: {order_type}")
            order_args = OrderArgs(
                price=price,
                size=size,
                side=side.upper(),
                token_id=market_id,
            )

            signed_order = await asyncio.to_thread(sdk_client.create_order, order_args)
            response = await asyncio.to_thread(
                sdk_client.post_order, 
                signed_order, 
                orderType=order_type.upper() if order_type else "FAK"
            )

            return response
        except Exception as e:
            raise PolymarketAPIError(f"Failed to place order: {e}")

    async def get_market_price(self, token_id: str, side: str = "BUY") -> dict:
        if not self._client:
            raise PolymarketAPIError("Client not initialized (use async with)")

        url = f"{settings.polymarket_base_url}/price"
        params = {"token_id": token_id, "side": side}
        headers = self._get_auth_headers("GET", f"/price?token_id={token_id}&side={side}")

        try:
            response = await self._client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise PolymarketAPIError(f"Failed to fetch price: {e}") from e
        except httpx.RequestError as e:
            raise PolymarketAPIError(f"Request failed: {e}") from e

    async def get_order_status(self, order_id: str) -> dict:
        if not self._client:
            raise PolymarketAPIError("Client not initialized (use async with)")

        url = f"{settings.polymarket_base_url}/data/order/{order_id}"
        headers = self._get_auth_headers("GET", f"/data/order/{order_id}")

        try:
            response = await self._client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise PolymarketAPIError(f"Failed to fetch order: {e}") from e
        except httpx.RequestError as e:
            raise PolymarketAPIError(f"Request failed: {e}") from e

    async def ensure_credentials(self) -> None:
        if not self._credentials_derived:
            creds = await self.derive_and_save_credentials()
            self._api_key = creds["apiKey"]
            self._api_secret = creds["secret"]
            self._api_passphrase = creds["passphrase"]
            self._credentials_derived = True

    async def derive_and_save_credentials(self) -> dict:
        if not settings.wallet_private_key:
            raise PolymarketAPIError("WALLET_PRIVATE_KEY missing from settings")


        sdk_client = ClobClient(
            host=settings.polymarket_base_url,
            key=settings.wallet_private_key,
            chain_id=137,
            signature_type=2,
            funder=self._address
        )

        try:
            res = await asyncio.to_thread(sdk_client.create_or_derive_api_creds)

            if hasattr(res, 'api_key'):
                creds_dict = {
                    'apiKey': res.api_key,
                    'secret': res.api_secret,
                    'passphrase': res.api_passphrase
                }
            elif isinstance(res, dict):
                creds_dict = res
            else:
                creds_dict = {'raw': str(res)}

            return creds_dict
        except Exception as e:
            raise PolymarketAPIError(f"SDK Derivation failed: {e}")

    async def test_authentication(self) -> dict:
        await self.ensure_credentials()

        creds = ApiCreds(
            api_key=self._api_key,
            api_secret=self._api_secret,
            api_passphrase=self._api_passphrase
        )

        sdk_client = ClobClient(
            host=settings.polymarket_base_url,
            key=settings.wallet_private_key,
            chain_id=137,
            creds=creds,
            signature_type=2,
            funder=self._address
        )

        try:
            return await asyncio.to_thread(sdk_client.get_orders)
        except Exception as e:
            raise PolymarketAPIError(f"SDK Auth verification failed: {e}")

    async def cancel_order(self, order_id: str) -> bool:
        await self.ensure_credentials()

        creds = ApiCreds(
            api_key=self._api_key,
            api_secret=self._api_secret,
            api_passphrase=self._api_passphrase
        )

        sdk_client = ClobClient(
            host=settings.polymarket_base_url,
            key=settings.wallet_private_key,
            chain_id=137,
            creds=creds,
            signature_type=2,
            funder=self._address
        )

        try:
            await asyncio.to_thread(sdk_client.cancel, order_id)
            return True
        except Exception as e:
            if "404" in str(e):
                return True
            raise PolymarketAPIError(f"Failed to cancel order: {e}")

    async def update_allowance(self, asset_type: AssetType = AssetType.COLLATERAL) -> dict:
        await self.ensure_credentials()

        creds = ApiCreds(
            api_key=self._api_key,
            api_secret=self._api_secret,
            api_passphrase=self._api_passphrase
        )

        sdk_client = ClobClient(
            host=settings.polymarket_base_url,
            key=settings.wallet_private_key,
            chain_id=137,
            creds=creds,
            signature_type=2,
            funder=self._address
        )

        try:
            params = BalanceAllowanceParams(asset_type=asset_type)
            res = await asyncio.to_thread(sdk_client.update_balance_allowance, params=params)
            await asyncio.sleep(3)
            return res
        except Exception as e:
            raise PolymarketAPIError(f"Failed to update allowance for {asset_type}: {e}")

    async def get_balance(self) -> dict:
        await self.ensure_credentials()

        creds = ApiCreds(
            api_key=self._api_key,
            api_secret=self._api_secret,
            api_passphrase=self._api_passphrase
        )

        sdk_client = ClobClient(
            host=settings.polymarket_base_url,
            key=settings.wallet_private_key,
            chain_id=137,
            creds=creds,
            signature_type=2,
            funder=self._address
        )

        try:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            res = await asyncio.to_thread(sdk_client.get_balance_allowance, params=params)
            
            if isinstance(res, dict):
                bal = float(res.get("balance", 0)) / 1_000_000
                
                raw_allowances = res.get("allowances", {})
                if isinstance(raw_allowances, dict) and raw_allowances:
                    allowance_val = max([float(v) for v in raw_allowances.values()] + [0])
                else:
                    allowance_val = float(res.get("allowance", 0))
                
                res["balance"] = bal
                res["allowance"] = allowance_val / 1_000_000
            
            return res
        except Exception as e:
            raise PolymarketAPIError(f"Failed to fetch balance: {e}")

    async def get_user_positions(self, user_address: str) -> list[dict]:
        if not self._client:
            raise PolymarketAPIError("Client not initialized")
        
        url = f"{settings.polymarket_data_url}/positions"
        params = {"user": user_address.lower(), "limit": 100}
        
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch user positions: {e}")
            return []

    async def redeem_positions(self, condition_id: str, outcome_index: int | None = None, nonce: int | None = None) -> dict:
        from web3 import Web3

        POLYGON_RPC = "https://polygon-bor-rpc.publicnode.com"
        CTF_ADDRESS = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
        USDC_ADDRESS = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

        CTF_ABI = [
            {
                "name": "redeemPositions",
                "type": "function",
                "inputs": [
                    {"name": "collateralToken", "type": "address"},
                    {"name": "parentCollectionId", "type": "bytes32"},
                    {"name": "conditionId", "type": "bytes32"},
                    {"name": "indexSets", "type": "uint256[]"}
                ],
                "outputs": []
            }
        ]
        
        SAFE_ABI = [
            {
                "name": "execTransaction",
                "type": "function",
                "inputs": [
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "data", "type": "bytes"},
                    {"name": "operation", "type": "uint8"},
                    {"name": "safeTxGas", "type": "uint256"},
                    {"name": "baseGas", "type": "uint256"},
                    {"name": "gasPrice", "type": "uint256"},
                    {"name": "gasToken", "type": "address"},
                    {"name": "refundReceiver", "type": "address"},
                    {"name": "signatures", "type": "bytes"}
                ],
                "outputs": [{"name": "success", "type": "bool"}]
            }
        ]

        try:
            w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
            account = w3.eth.account.from_key(settings.wallet_private_key)
            sender = Web3.to_checksum_address(account.address)

            index_sets = [1, 2] if outcome_index is None else [1 << outcome_index]
            condition_bytes = bytes.fromhex(condition_id[2:]) if condition_id.startswith("0x") else bytes.fromhex(condition_id)

            ctf = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
            inner_tx = ctf.functions.redeemPositions(
                USDC_ADDRESS,
                bytes(32),
                condition_bytes,
                index_sets
            ).build_transaction({"gas": 0, "gasPrice": 0, "nonce": 0})
            inner_data = bytes.fromhex(inner_tx["data"][2:])

            proxy_addr = settings.polymarket_funder_address
            
            if proxy_addr and len(w3.eth.get_code(Web3.to_checksum_address(proxy_addr))) > 0:
                proxy = Web3.to_checksum_address(proxy_addr)
                safe = w3.eth.contract(address=proxy, abi=SAFE_ABI)
                
                r = account.address[2:].zfill(64)
                s = "00" * 32
                v = "01"
                signatures = bytes.fromhex(r + s + v)
                
                logger.info(f"Routing redemption through proxy {proxy} for condition {condition_id}")
                tx = safe.functions.execTransaction(
                    CTF_ADDRESS, 0, inner_data, 0, 0, 0, 0,
                    "0x0000000000000000000000000000000000000000",
                    "0x0000000000000000000000000000000000000000",
                    signatures
                ).build_transaction({
                    "from": sender,
                    "nonce": nonce if nonce is not None else w3.eth.get_transaction_count(sender),
                    "gas": 500000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": 137,
                })
            else:
                logger.info(f"Executing direct EOA redemption for condition {condition_id}")
                tx = ctf.functions.redeemPositions(
                    USDC_ADDRESS,
                    bytes(32),
                    condition_bytes,
                    index_sets
                ).build_transaction({
                    "from": sender,
                    "nonce": nonce if nonce is not None else w3.eth.get_transaction_count(sender),
                    "gas": 300000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": 137,
                })

            signed = await asyncio.to_thread(w3.eth.account.sign_transaction, tx, settings.wallet_private_key)
            tx_hash = await asyncio.to_thread(w3.eth.send_raw_transaction, signed.raw_transaction)
            receipt = await asyncio.to_thread(w3.eth.wait_for_transaction_receipt, tx_hash, timeout=120)
            
            logger.info(f"Redemption TX: {tx_hash.hex()} | Status: {receipt['status']}")
            return {"tx_hash": tx_hash.hex(), "status": "success" if receipt["status"] == 1 else "failed"}
        except Exception as e:
            raise PolymarketAPIError(f"On-chain redemption failed: {e}")
    async def redeem_positions_batch(self, items: list[dict]) -> list[dict]:
        """Redeem multiple positions in parallel by managing nonces."""
        if not items:
            return []
            
        from web3 import Web3
        POLYGON_RPC = "https://polygon-bor-rpc.publicnode.com"
        w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
        
        account = w3.eth.account.from_key(settings.wallet_private_key)
        sender = Web3.to_checksum_address(account.address)
        
        start_nonce = await asyncio.to_thread(w3.eth.get_transaction_count, sender)
        
        logger.info(f"Initiating bulk redemption for {len(items)} positions starting at nonce {start_nonce}")
        
        tasks = []
        for i, item in enumerate(items):
            tasks.append(self.redeem_positions(
                item["condition_id"], 
                outcome_index=item.get("outcome_index"),
                nonce=start_nonce + i
            ))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [res for res in results if not isinstance(res, Exception)]

    def _get_auth_headers(self, method: str, path: str, body: dict | None = None) -> dict:
        timestamp = str(int(time.time()))
        clean_path = path.split('?')[0]
        message = timestamp + method.upper() + clean_path

        if body:
            message += json.dumps(body, separators=(',', ':'))

        try:
            rem = len(self._api_secret) % 4
            padding = '=' * (4 - rem) if rem else ''
            key = base64.b64decode(self._api_secret + padding)

            signature = hmac.new(
                key,
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()

            base64_sig = base64.b64encode(signature).decode('utf-8')
            funder = settings.polymarket_funder_address or self._address or ""
            lowercase_address = funder.lower() if funder else ""

            return {
                "POLY_API_KEY": self._api_key,
                "POLY_SIGNATURE": base64_sig,
                "POLY_TIMESTAMP": timestamp,
                "POLY_PASSPHRASE": self._api_passphrase,
                "POLY_ADDRESS": lowercase_address,
                "Content-Type": "application/json",
            }
        except Exception as e:
            raise PolymarketAPIError(f"Signature generation failed: {e}")
