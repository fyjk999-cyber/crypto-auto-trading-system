"""Retired plaintext credential store. Runtime access uses okx_vault.client."""


class EnvCredentialStore:
    """Compatibility tombstone: no disk or environment credential access."""

    def __init__(self, *args, **kwargs):
        pass

    def read(self):
        raise PermissionError("RAW_CREDENTIAL_ACCESS_REMOVED_USE_BROKER")

    def write(self, values):
        raise PermissionError("PLAINTEXT_STORAGE_REMOVED_USE_HUMAN_VAULT_CLI")

    def clear(self):
        raise PermissionError("CREDENTIAL_DELETE_REQUIRES_HUMAN_VAULT_CLI")
