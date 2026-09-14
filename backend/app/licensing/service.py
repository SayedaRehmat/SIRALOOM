from __future__ import annotations
import base64, json
from datetime import datetime, timezone
from hashlib import sha256
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

class LicenseError(RuntimeError):
    pass

def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

def sign_entitlement(private_key: Ed25519PrivateKey, payload: dict) -> str:
    return base64.urlsafe_b64encode(private_key.sign(canonical(payload))).decode().rstrip("=")

def verify_entitlement(public_key: Ed25519PublicKey, payload: dict, signature: str) -> bool:
    try:
        padded = signature + "=" * (-len(signature) % 4)
        public_key.verify(base64.urlsafe_b64decode(padded), canonical(payload))
        return True
    except (InvalidSignature, ValueError):
        return False

def entitlement_fingerprint(payload: dict, signature: str) -> str:
    return sha256(canonical({"payload": payload, "signature": signature})).hexdigest()

def validate_entitlement(payload: dict, *, installation_id: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if payload.get("installation_id") != installation_id:
        raise LicenseError("Installation identity mismatch")
    valid_from = datetime.fromisoformat(payload["valid_from"])
    valid_until = datetime.fromisoformat(payload["valid_until"])
    if now < valid_from or now >= valid_until:
        raise LicenseError("License lease is not currently valid")
    if payload.get("status") != "ACTIVE":
        raise LicenseError("License is not active")
