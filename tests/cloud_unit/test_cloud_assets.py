import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cloudflare_tree_exists():
    base = ROOT / "deployment" / "cloudflare"
    assert (base / "worker" / "src" / "index.js").exists()
    assert (base / "worker" / "wrangler.jsonc").exists()
    assert (base / "worker" / "package.json").exists()
    assert (base / "container" / "Dockerfile").exists()
    assert (base / "container" / "container.json").exists()
    assert (base / "access" / "policy.json").exists()
    assert (base / "scripts" / "backup.sh").exists()
    assert (base / "scripts" / "restore.sh").exists()


def test_wrangler_pinned_to_v4():
    package = json.loads((ROOT / "deployment/cloudflare/worker/package.json").read_text())
    assert package["devDependencies"]["wrangler"].startswith("4.")
    wrangler = (ROOT / "deployment/cloudflare/worker/wrangler.jsonc").read_text()
    assert '"compatibility_date"' in wrangler
    assert "crypto-trading-gateway" in wrangler


def test_container_is_non_root_with_healthcheck():
    dockerfile = (ROOT / "deployment/cloudflare/container/Dockerfile").read_text()
    assert "adduser" in dockerfile
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    container = json.loads((ROOT / "deployment/cloudflare/container/container.json").read_text())
    assert container["desired_state"] == "RUNNING"
    assert container["env"]["TRADING_MODE"] == "TESTNET"
    assert container["env"]["AUTO_START_RUNTIME"] == "true"
    assert container["env"]["LIVE_TRADING_ENABLED"] == "false"


def test_codex_is_read_only_in_access_policy():
    policy = json.loads((ROOT / "deployment/cloudflare/access/policy.json").read_text())
    codex = [p for p in policy["allow"] if p["identity"] == "codex"][0]
    assert codex["methods"] == ["GET", "HEAD"]
    assert codex["control_endpoints"] is False


def test_codex_example_has_placeholders_only():
    text = (ROOT / "CODEX_CLOUD_ACCESS.example").read_text()
    assert "CF_ACCESS_CLIENT_ID=<placeholder>" in text
    assert "CF_ACCESS_CLIENT_SECRET=<placeholder>" in text


def test_codex_handoff_json_has_no_real_secrets():
    data = json.loads((ROOT / "codex-cloud-handoff.json").read_text())
    assert data["environment"] == "testnet"
    assert data["api_base_url"].startswith("https://")
    assert data["access"]["client_secret_env"] == "CF_ACCESS_CLIENT_SECRET"


def test_cloudflare_docs_exist():
    for name in (
        "ARCHITECTURE.md",
        "DEPLOYMENT.md",
        "CONTAINERS.md",
        "WORKER_GATEWAY.md",
        "ACCESS.md",
        "POSTGRESQL.md",
        "R2_BACKUPS.md",
        "WORKFLOWS.md",
        "OBSERVABILITY.md",
        "TESTNET.md",
        "ROLLBACK.md",
        "DISASTER_RECOVERY.md",
        "CODEX_ACCESS.md",
    ):
        assert (ROOT / "docs" / "cloudflare" / name).exists(), name


def test_worker_gateway_control_endpoints_deny_codex():
    source = (ROOT / "deployment/cloudflare/worker/src/gateway.js").read_text()
    assert "allowedByRole" in source
    assert "/api/v1/kill-switch/off" in source
    assert 'role === "codex"' in source
    assert 'requestClass === "READ"' in source


def test_wrangler_container_durable_object_config():
    text = (ROOT / "deployment/cloudflare/worker/wrangler.jsonc").read_text()
    # Wrangler uses JSONC; our config is valid JSON after removing trailing comma concerns.
    # Check raw markers to avoid parser complications.
    assert '"containers"' in text
    assert '"crypto-trading-primary"' in text
    assert '"class_name": "TradingContainerV2"' in text
    assert '"new_sqlite_classes": ["TradingContainerV2"]' in text
    assert '"crons": ["* * * * *"]' in text
    worker_source = (ROOT / "deployment/cloudflare/worker/src/index.js").read_text()
    assert "export class TradingContainerV2 extends Container" in worker_source
    assert "getContainer(env.TRADING_CONTAINER" in worker_source
    assert "async function runWatchdog" in worker_source


def test_container_build_context_is_repository_root():
    config = (ROOT / "deployment/cloudflare/worker/wrangler.jsonc").read_text()
    assert '"image_build_context": "../../.."' in config


def test_gateway_has_no_placeholder_backend_or_header_only_jwt_trust():
    source = (ROOT / "deployment/cloudflare/worker/src/index.js").read_text()
    gateway = (ROOT / "deployment/cloudflare/worker/src/gateway.js").read_text()
    assert "BACKEND_URL" not in source
    assert "container-backend.example.internal" not in source
    assert "jwtVerify" in gateway
