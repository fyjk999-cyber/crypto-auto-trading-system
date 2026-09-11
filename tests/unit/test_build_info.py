from crypto_trader.build_info import current_build_provenance


def test_build_provenance_prefers_explicit_release_sha(monkeypatch):
    sha = "a" * 40
    monkeypatch.setenv("CRYPTO_TRADER_SOURCE_SHA", sha)
    provenance = current_build_provenance()
    assert provenance.source_sha == sha
    assert provenance.sha_origin == "environment"
    assert provenance.source_path.endswith("crypto_trader/__init__.py")
    assert provenance.package_version == "0.1.0"
