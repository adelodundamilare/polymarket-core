import time
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_checksum_address

from polymarket_core.config import settings
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

class OrderSigner:
    DOMAIN = {
        "name": "Polymarket CTF Exchange",
        "version": "1",
        "chainId": 137,
        "verifyingContract": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    }

    ORDER_TYPES = {
        "Order": [
            {"name": "salt", "type": "uint256"},
            {"name": "maker", "type": "address"},
            {"name": "signer", "type": "address"},
            {"name": "taker", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
            {"name": "makerAmount", "type": "uint256"},
            {"name": "takerAmount", "type": "uint256"},
            {"name": "expiration", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
            {"name": "feeRateBps", "type": "uint256"},
            {"name": "side", "type": "uint8"},
            {"name": "signatureType", "type": "uint8"},
        ]
    }

    def __init__(self, private_key: str) -> None:
        if private_key.startswith("0x"):
            private_key = private_key[2:]

        try:
            self.wallet = Account.from_key(f"0x{private_key}")
            self.address = self.wallet.address
        except Exception as e:
            raise ValueError(f"Invalid private key: {e}")

    def sign_order(
        self,
        token_id: str,
        price: float,
        size: float | int,
        side: str,
        nonce: int | None = None,
    ) -> dict[str, Any]:
        salt = int(time.time() * 1000)
        side_value = 0 if side.upper() == "BUY" else 1

        if side_value == 0:
            maker_amount = int(size * price * 10**6)
            taker_amount = int(size * 10**6)
        else:
            maker_amount = int(size * 10**6)
            taker_amount = int(size * price * 10**6)

        if nonce is None:
            nonce = 0

        funder = settings.polymarket_funder_address or self.address
        sig_type = settings.polymarket_signature_type

        order_message = {
            "salt": salt,
            "maker": to_checksum_address(funder),
            "signer": self.address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id),
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": 0,
            "nonce": nonce,
            "feeRateBps": 0,
            "side": side_value,
            "signatureType": sig_type,
        }

        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"}
                ],
                "Order": self.ORDER_TYPES["Order"]
            },
            "primaryType": "Order",
            "domain": self.DOMAIN,
            "message": order_message
        }

        signable = encode_typed_data(full_message=typed_data)
        signed = self.wallet.sign_message(signable)
        signature = "0x" + signed.signature.hex()

        return {
            "payload": {
                "order": {
                    "salt": salt,
                    "maker": funder,
                    "signer": self.address,
                    "taker": "0x0000000000000000000000000000000000000000",
                    "tokenId": token_id,
                    "makerAmount": str(maker_amount),
                    "takerAmount": str(taker_amount),
                    "expiration": "0",
                    "nonce": str(nonce),
                    "feeRateBps": "0",
                    "side": side_value,
                    "signatureType": sig_type,
                },
                "signature": signature,
                "owner": funder,
            }
        }
