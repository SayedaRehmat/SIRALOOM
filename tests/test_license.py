from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from backend.app.licensing.service import sign_entitlement, verify_entitlement, validate_entitlement

def test_signed_entitlement():
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    now = datetime.now(timezone.utc)
    payload = {"installation_id": "INS-1", "status": "ACTIVE", "valid_from": now.isoformat(), "valid_until": (now + timedelta(days=1)).isoformat()}
    sig = sign_entitlement(private, payload)
    assert verify_entitlement(public, payload, sig)
    validate_entitlement(payload, installation_id="INS-1", now=now)
