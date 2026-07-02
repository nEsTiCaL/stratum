"""I-REST.2: Auth-Modul und Repository-Vertrag fuer Capabilities."""

from __future__ import annotations

from core.auth import generate_api_key, hash_key, key_prefix_display
from core.repository import Repository
from tests.conftest import TEST_API_KEY, TEST_OWNER


class TestKeyGeneration:
    def test_key_has_correct_prefix(self):
        key = generate_api_key()
        assert key.startswith("sk-stratum-")

    def test_key_is_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100

    def test_hash_is_deterministic(self):
        key = generate_api_key()
        assert hash_key(key) == hash_key(key)

    def test_different_keys_have_different_hashes(self):
        k1, k2 = generate_api_key(), generate_api_key()
        assert hash_key(k1) != hash_key(k2)

    def test_key_prefix_display_shorter_than_full_key(self):
        key = generate_api_key()
        assert len(key_prefix_display(key)) < len(key)

    def test_key_prefix_display_starts_with_prefix(self):
        key = generate_api_key()
        assert key_prefix_display(key).startswith("sk-stratum-")


class TestVerifyApiKey:
    def test_valid_key_returns_owner(self, conn):
        repo = Repository(conn)
        assert repo.verify_api_key(TEST_API_KEY) == TEST_OWNER

    def test_unknown_key_returns_none(self, conn):
        repo = Repository(conn)
        assert repo.verify_api_key("sk-stratum-" + "f" * 64) is None

    def test_revoked_key_returns_none(self, conn):
        repo = Repository(conn)
        conn.execute(
            "UPDATE capabilities SET revoked = true WHERE owner = %s", (TEST_OWNER,)
        )
        assert repo.verify_api_key(TEST_API_KEY) is None

    def test_register_and_verify_new_key(self, conn):
        repo = Repository(conn)
        new_key = generate_api_key()
        repo.register_capability(
            "alice", hash_key(new_key), key_prefix_display(new_key)
        )
        assert repo.verify_api_key(new_key) == "alice"

    def test_multiple_owners_independent(self, conn):
        repo = Repository(conn)
        key_a = generate_api_key()
        key_b = generate_api_key()
        repo.register_capability("alice", hash_key(key_a), key_prefix_display(key_a))
        repo.register_capability("bob", hash_key(key_b), key_prefix_display(key_b))
        assert repo.verify_api_key(key_a) == "alice"
        assert repo.verify_api_key(key_b) == "bob"
        assert repo.verify_api_key(TEST_API_KEY) == TEST_OWNER
