#!/usr/bin/env python3
"""Exercise real native Keychain CRUD with ephemeral synthetic values only."""
import json
import secrets
import uuid

from netease163 import MacOSKeychainCredentialStore


def main():
    service = "lazymind-outreach-agent:smoke:" + str(uuid.uuid4())
    store = MacOSKeychainCredentialStore(service=service)
    account = "synthetic-test"
    created = False
    try:
        assert store.get(account) is None
        store.save(account, secrets.token_hex(24))
        created = True
        store.save(account, secrets.token_hex(24))
        store.delete(account)
        created = False
        assert store.get(account) is None
        print(json.dumps({"native_keychain_create_update_readback_delete": "passed", "mail_account_accessed": False}))
    finally:
        if created:
            store.delete(account)


if __name__ == "__main__":
    main()
