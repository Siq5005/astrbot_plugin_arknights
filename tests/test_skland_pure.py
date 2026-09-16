import hashlib
import hmac
import json
import re

from core.skland import (
    aes_encrypt,
    apply_des_rules,
    derive_sanity,
    generate_signature,
    get_tn,
)


def test_get_tn_sorts_keys_and_scales_ints():
    assert get_tn({"b": 1, "a": "x"}) == "x10000"
    assert get_tn({"a": "", "b": 2}) == "20000"
    assert get_tn({"a": {"y": 1, "x": 2}}) == "2000010000"


def test_generate_signature_is_deterministic():
    sign, header = generate_signature("tok", "/api/x", "a=1", "did123", 1700000000)
    expected_raw = f"/api/xa=11700000000{json.dumps(header, separators=(',', ':'))}"
    expected = hashlib.md5(
        hmac.new(b"tok", expected_raw.encode(), hashlib.sha256).hexdigest().encode()
    ).hexdigest()
    assert sign == expected
    assert header["dId"] == "did123"
    assert header["platform"] == "3"
    assert header["timestamp"] == "1700000000"
    assert header["vName"] == "1.0.0"


def test_apply_des_rules_obfuscates_encrypted_keys():
    result = apply_des_rules({"platform": "Win32", "protocol": 102})
    # platform is encrypted and renamed to its obfuscated name
    assert "platform" not in result
    assert "gm" in result
    assert re.fullmatch(r"[A-Za-z0-9+/=]+", result["gm"])
    # protocol is not encrypted but is still renamed
    assert result["protocol"] == 102


def test_apply_des_rules_passes_through_unknown_keys():
    assert apply_des_rules({"not_a_rule": "keep"}) == {"not_a_rule": "keep"}


def test_aes_encrypt_is_deterministic_hex():
    first = aes_encrypt(b"payload", b"0123456789abcdef")
    second = aes_encrypt(b"payload", b"0123456789abcdef")
    assert first == second
    assert re.fullmatch(r"[0-9a-f]+", first)
    assert len(first) % 32 == 0


def test_derive_sanity_recovers_from_complete_recovery_time():
    now = 1_000_000.0
    assert derive_sanity(0, 120, int(now + 3600), 360, now) == 110
    assert derive_sanity(5, 120, int(now + 360), 360, now) == 119


def test_derive_sanity_clamps_low():
    now = 1_000_000.0
    assert derive_sanity(0, 10, int(now + 999_999), 360, now) == 0


def test_derive_sanity_full_when_no_countdown():
    now = 1_000_000.0
    assert derive_sanity(88, 120, -1, 360, now) == 120
    assert derive_sanity(500, 127, -1, 360, now) == 500


def test_derive_sanity_past_timestamp_treated_as_full():
    now = 1_000_000.0
    assert derive_sanity(30, 135, int(now - 60), 360, now) == 135


def test_derive_sanity_handles_missing_max():
    assert derive_sanity(None, None, None, 360, 1_000_000.0) == 0
