"""Real dkimpy/RSA verification, with ephemeral keys and local DNS answers only.

This suite does not prove Gmail API behavior or real-world DNS interoperability.
The only dkimpy patch replaces verify()'s default DNS callback; signature
parsing, body hashing, RSA verification, and signed_headers are the real code.
"""

import base64
import socket
from typing import NamedTuple

import dkim
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gmail_unsubscriber.gmail import _verified_raw


COMPLETE = (b"from", b"list-unsubscribe", b"list-unsubscribe-post")
BASE = (
    b"From: Fixture News <news@example.test>\r\n"
    b"To: Synthetic Reader <reader@example.invalid>\r\n"
    b"Subject: Offline cryptography fixture\r\n"
    b"Date: Fri, 18 Sep 2026 00:00:00 +0000\r\n"
    b"List-ID: Fixture <news.example.test>\r\n"
    b"List-Unsubscribe: <https://example.test/leave?list=original>\r\n"
    b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
    b"Authentication-Results: mx.google.com; dkim=pass\r\n"
    b"\r\n"
    b"Hello synthetic body.\r\n"
)


class EphemeralKey(NamedTuple):
    private_pem: bytes
    dns_record: bytes

    def __repr__(self):
        return "<ephemeral RSA-2048 test key: contents redacted>"


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Fail even if adapter's fail-closed catch would hide a network attempt."""
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("network attempted")
        raise AssertionError("Offline cryptography tests forbid network access")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    for method in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"):
        if hasattr(socket.socket, method):
            monkeypatch.setattr(socket.socket, method, blocked)
    yield
    assert attempts == [], "A DNS/HTTP network operation was attempted"


@pytest.fixture(scope="module")
def ephemeral_key():
    """Generated in memory for this test run; never written to disk or logged."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    public_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return EphemeralKey(private_pem, b"v=DKIM1; k=rsa; p=" + base64.b64encode(public_der))


@pytest.fixture
def local_dns(monkeypatch, ephemeral_key):
    queries = []
    records = {b"fixture._domainkey.example.test": ephemeral_key[1]}

    def resolve(name, timeout=5):
        queries.append((name, timeout))
        return records.get(name.lower().rstrip(b"."))

    # Do not replace DKIM.verify or the cryptography implementation. Setting its
    # default parameter exercises the production call verifier.verify(idx=...).
    assert dkim.DKIM.verify.__defaults__[0] == 0
    monkeypatch.setattr(dkim.DKIM.verify, "__defaults__", (0, resolve))
    return records, queries


def sign(message, private_pem, headers=COMPLETE, canonicalize=(b"relaxed", b"simple")):
    return dkim.sign(
        message, selector=b"fixture", domain=b"example.test", privkey=private_pem,
        include_headers=headers, canonicalize=canonicalize, signature_algorithm=b"rsa-sha256",
    ) + message


def library_verifies(raw, index=0):
    return dkim.DKIM(raw).verify(idx=index)


def adapter_verifies(raw):
    return _verified_raw(raw, {"id": "a1", "internalDate": "1700000000000"}, dkim)


@pytest.mark.parametrize("canonicalize", [(b"relaxed", b"simple"), (b"simple", b"simple")])
def test_real_signature_valid_and_actual_signed_headers_supported(ephemeral_key, local_dns, canonicalize):
    raw = sign(BASE, ephemeral_key[0], canonicalize=canonicalize)
    verifier = dkim.DKIM(raw)
    assert verifier.verify() is True
    actual = {name.lower(): value for name, value in verifier.signed_headers}
    assert set(COMPLETE).issubset(actual)
    assert actual[b"list-unsubscribe"].endswith(b"\r\n")
    assert b"https://example.test/leave?list=original" in actual[b"list-unsubscribe"]
    result = adapter_verifies(raw)
    assert result["authenticated"] is True
    assert result["verification_reason"] == "dkim_verified"
    assert result["sender_email"] == "news@example.test"
    assert result["list_unsubscribe"] == "<https://example.test/leave?list=original>"
    assert local_dns[1]
    assert local_dns[1][-1][1] == 3  # Adapter's finite DNS timeout is forwarded.


def test_real_body_tampering_is_rejected(ephemeral_key, local_dns):
    raw = sign(BASE, ephemeral_key[0]).replace(b"Hello synthetic body.", b"Changed synthetic body.")
    # dkimpy's class API raises this exception; only its top-level helper turns
    # all validation failures into False. The production adapter handles either.
    with pytest.raises(dkim.ValidationError, match="body hash mismatch"):
        library_verifies(raw)
    assert adapter_verifies(raw)["authenticated"] is False


@pytest.mark.parametrize("original,replacement", [
    (b"news@example.test", b"attacker@example.test"),
    (b"leave?list=original", b"leave?list=changed"),
    (b"List-Unsubscribe=One-Click", b"List-Unsubscribe=Not-One-Click"),
])
def test_real_signed_header_tampering_is_rejected(ephemeral_key, local_dns, original, replacement):
    raw = sign(BASE, ephemeral_key[0]).replace(original, replacement)
    assert library_verifies(raw) is False
    assert adapter_verifies(raw)["authenticated"] is False


@pytest.mark.parametrize("headers", [
    (b"from",),
    (b"from", b"list-unsubscribe"),
    (b"from", b"list-unsubscribe-post"),
])
def test_actual_valid_signature_with_incomplete_coverage_remains_manual(ephemeral_key, local_dns, headers):
    raw = sign(BASE, ephemeral_key[0], headers=headers)
    assert library_verifies(raw) is True
    local_dns[1].clear()
    assert adapter_verifies(raw)["authenticated"] is False
    assert local_dns[1] == []  # No needless DNS for insufficient h= coverage.


def test_two_actual_valid_signatures_cannot_combine_their_header_coverage(ephemeral_key, local_dns):
    first = sign(BASE, ephemeral_key[0], headers=(b"from", b"list-unsubscribe"))
    raw = sign(first, ephemeral_key[0], headers=(b"from", b"list-unsubscribe-post"))
    assert library_verifies(raw, 0) is True
    assert library_verifies(raw, 1) is True
    assert adapter_verifies(raw)["authenticated"] is False


def test_valid_weak_signature_cannot_lend_success_to_invalid_complete_signature(ephemeral_key, local_dns):
    complete_then_tampered = sign(BASE, ephemeral_key[0]).replace(b"leave?list=original", b"leave?list=changed")
    raw = sign(complete_then_tampered, ephemeral_key[0], headers=(b"from",))
    # The forged Authentication-Results in BASE also claims pass, but is ignored.
    assert library_verifies(raw, 0) is True
    assert library_verifies(raw, 1) is False
    local_dns[1].clear()
    assert adapter_verifies(raw)["authenticated"] is False
    assert len(local_dns[1]) == 1  # Only the complete, invalid signature is tested.


def test_second_complete_valid_signature_is_accepted_at_actual_index(ephemeral_key, local_dns):
    valid = sign(BASE, ephemeral_key[0])
    different_body = BASE.replace(b"Hello synthetic body.", b"Different signed body.")
    invalid_header = sign(different_body, ephemeral_key[0])[:-len(different_body)]
    raw = invalid_header + valid
    with pytest.raises(dkim.ValidationError, match="body hash mismatch"):
        library_verifies(raw, 0)
    assert library_verifies(raw, 1) is True
    local_dns[1].clear()
    assert adapter_verifies(raw)["authenticated"] is True
    assert len(local_dns[1]) == 2


def test_duplicate_unsigned_target_is_rejected_even_when_crypto_still_passes(ephemeral_key, local_dns):
    # DKIM h= selects the bottommost original List-Unsubscribe. The newly added
    # duplicate is not authenticated, so the adapter must reject the ambiguity.
    raw = b"List-Unsubscribe: <https://attacker.invalid/leave>\r\n" + sign(BASE, ephemeral_key[0])
    assert library_verifies(raw) is True
    local_dns[1].clear()
    result = adapter_verifies(raw)
    assert result["authenticated"] is False
    assert result["verification_reason"] == "ambiguous_headers"
    assert local_dns[1] == []


def test_missing_local_dns_key_fails_closed(ephemeral_key, local_dns):
    raw = sign(BASE, ephemeral_key[0])
    local_dns[0].clear()
    assert library_verifies(raw) is False
    assert adapter_verifies(raw)["authenticated"] is False


def test_folded_headers_verify_with_actual_canonicalized_values(ephemeral_key, local_dns):
    folded = BASE.replace(
        b"List-Unsubscribe: <https://example.test/leave?list=original>",
        b"List-Unsubscribe:\r\n\t<https://example.test/leave?list=original>",
    )
    raw = sign(folded, ephemeral_key[0])
    assert library_verifies(raw) is True
    assert adapter_verifies(raw)["authenticated"] is True
