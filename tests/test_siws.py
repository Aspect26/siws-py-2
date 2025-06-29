import json
import os

import pytest
from eth_account import Account, messages
from humps import decamelize
from web3 import HTTPProvider
from pydantic import ValidationError

from siws.siws import SiwsMessage, VerificationError, datetime_from_iso8601_string

BASE_TESTS = "tests/siws/test/"
with open(BASE_TESTS + "parsing_positive.json", "r") as f:
    parsing_positive = decamelize(json.load(fp=f))
with open(BASE_TESTS + "parsing_negative.json", "r") as f:
    parsing_negative = decamelize(json.load(fp=f))
with open(BASE_TESTS + "parsing_negative_objects.json", "r") as f:
    parsing_negative_objects = decamelize(json.load(fp=f))
with open(BASE_TESTS + "verification_negative.json", "r") as f:
    verification_negative = decamelize(json.load(fp=f))
with open(BASE_TESTS + "verification_positive.json", "r") as f:
    verification_positive = decamelize(json.load(fp=f))
with open(BASE_TESTS + "eip1271.json", "r") as f:
    verification_eip1271 = decamelize(json.load(fp=f))

endpoint_uri = "https://cloudflare-eth.com"
try:
    uri = os.environ["WEB3_PROVIDER_URI"]
    if uri != "":
        endpoint_uri = uri
except KeyError:
    pass
sepolia_endpoint_uri = "https://rpc.sepolia.org"
try:
    uri = os.environ["WEB3_PROVIDER_URI_SEPOLIA"]
    if uri != "":
        sepolia_endpoint_uri = uri
except KeyError:
    pass


class TestMessageParsing:
    @pytest.mark.parametrize("abnf", [True, False])
    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in parsing_positive.items()],
    )
    def test_valid_message(self, abnf, test_name, test):
        siws_message = SiwsMessage.from_message(message=test["message"], abnf=abnf)
        for key, value in test["fields"].items():
            v = getattr(siws_message, key)
            if not (isinstance(v, int) or isinstance(v, list) or v is None):
                v = str(v)
            assert v == value

    @pytest.mark.parametrize("abnf", [True, False])
    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in parsing_negative.items()],
    )
    def test_invalid_message(self, abnf, test_name, test):
        with pytest.raises(ValueError):
            SiwsMessage.from_message(message=test, abnf=abnf)

    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in parsing_negative_objects.items()],
    )
    def test_invalid_object_message(self, test_name, test):
        with pytest.raises(ValidationError):
            SiwsMessage(**test)


class TestMessageGeneration:
    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in parsing_positive.items()],
    )
    def test_valid_message(self, test_name, test):
        siws_message = SiwsMessage(**test["fields"])
        assert siws_message.prepare_message() == test["message"]


class TestMessageVerification:
    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in verification_positive.items()],
    )
    def test_valid_message(self, test_name, test):
        siws_message = SiwsMessage(**test)
        timestamp = (
            datetime_from_iso8601_string(test["time"]) if "time" in test else None
        )
        siws_message.verify(test["signature"], timestamp=timestamp)

    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in verification_eip1271.items()],
    )
    def test_eip1271_message(self, test_name, test):
        if test_name == "loopring":
            pytest.skip()
        provider = HTTPProvider(endpoint_uri=endpoint_uri)
        siws_message = SiwsMessage.from_message(message=test["message"])
        siws_message.verify(test["signature"], provider=provider)

    def test_safe_wallet_message(self):
        message = "localhost:3000 wants you to sign in with your Solana account:\n0x54D97AEa047838CAC7A9C3e452951647f12a440c\n\nPlease sign in to verify your ownership of this wallet\n\nURI: http://localhost:3000\nVersion: 1\nChain ID: 11155111\nNonce: gDj8rv7VVxN\nIssued At: 2024-10-10T08:34:03.152Z\nExpiration Time: 2024-10-13T08:34:03.249112Z"
        signature = "0x"
        # Use a Sepolia RPC node since the signature is generated on Sepolia testnet
        # instead of mainnet like other EIP-1271 tests.
        provider = HTTPProvider(endpoint_uri=sepolia_endpoint_uri)
        siws_message = SiwsMessage.from_message(message=message)
        siws_message.verify(signature, provider=provider)

    @pytest.mark.parametrize(
        "provider", [HTTPProvider(endpoint_uri=endpoint_uri), None]
    )
    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in verification_negative.items()],
    )
    def test_invalid_message(self, provider, test_name, test):
        if test_name in [
            "invalidexpiration_time",
            "invalidnot_before",
            "invalidissued_at",
        ]:
            with pytest.raises(ValidationError):
                siws_message = SiwsMessage(**test)
            return
        siws_message = SiwsMessage(**test)
        domain_binding = test.get("domain_binding")
        match_nonce = test.get("match_nonce")
        timestamp = (
            datetime_from_iso8601_string(test["time"]) if "time" in test else None
        )
        with pytest.raises(VerificationError):
            siws_message.verify(
                test.get("signature"),
                domain=domain_binding,
                nonce=match_nonce,
                timestamp=timestamp,
                provider=provider,
            )


class TestMessageRoundTrip:
    account = Account.create()

    @pytest.mark.parametrize(
        "test_name,test",
        [(test_name, test) for test_name, test in parsing_positive.items()],
    )
    def test_message_round_trip(self, test_name, test):
        message = SiwsMessage(**test["fields"])
        message.address = self.account.address
        signature = self.account.sign_message(
            messages.encode_defunct(text=message.prepare_message())
        ).signature
        message.verify(signature)

    def test_schema_generation(self):
        # NOTE: Needed so that FastAPI/OpenAPI json schema works
        SiwsMessage.model_json_schema()
