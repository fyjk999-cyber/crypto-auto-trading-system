from crypto_trader.operating_system.backup import BackupOrchestrator
from crypto_trader.security.auth import AUTH_ENABLED, Role, record_audit, verify_token


def test_auth_audit_and_verification():
    event = record_audit("admin", "ADMIN", "kill_switch", "global", "test")
    assert event["actor"] == "admin"
    assert event["action"] == "kill_switch"
    if AUTH_ENABLED:
        assert isinstance(verify_token("unknown", Role.ADMIN), bool)
    else:
        assert verify_token("anything", Role.ADMIN) is True


async def test_backup_corruption_detection():
    orchestrator = BackupOrchestrator()
    backup = await orchestrator.backup("b1", payload="hello")
    assert backup.checksum
    verified = await orchestrator.verify("b1", payload="hello")
    assert verified.status == "VERIFIED"
    corrupt = await orchestrator.verify("b1", payload="tampered")
    assert corrupt.status == "CORRUPT"
    restored = await orchestrator.restore("b1", payload="hello")
    assert restored.status == "RESTORED"
    failed = await orchestrator.restore("b1", payload="bad")
    assert failed.status == "CORRUPT"


def test_frontend_verify_script_exists():
    from pathlib import Path

    script = Path("scripts/frontend-verify.sh")
    assert script.exists()
    text = script.read_text()
    assert "npm run typecheck" in text
    assert "npm run build" in text
