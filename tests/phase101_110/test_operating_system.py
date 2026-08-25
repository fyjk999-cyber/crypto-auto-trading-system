from decimal import Decimal

from crypto_trader.capital_deployment.approval import CapitalApproval
from crypto_trader.capital_deployment.gate import DeploymentGate
from crypto_trader.operating_system.backup import BackupOrchestrator
from crypto_trader.operating_system.jobs import JobScheduler
from crypto_trader.operating_system.kernel import OSKernel, ProcessState
from crypto_trader.operating_system.lifecycle import LifecycleStatus
from crypto_trader.operating_system.maintenance import MaintenanceManager
from crypto_trader.operating_system.monitoring import OSMonitor
from crypto_trader.operating_system.upgrades import UpgradeManager


def test_os_kernel_process_lifecycle():
    kernel = OSKernel()
    kernel.register("api")
    kernel.start("api")
    assert kernel.processes["api"].state == ProcessState.RUNNING
    kernel.degrade("api", "db timeout")
    assert kernel.processes["api"].state == ProcessState.DEGRADED
    kernel.restart("api")
    assert kernel.processes["api"].restart_count == 1


async def test_job_scheduler_idempotent():
    scheduler = JobScheduler()
    calls = []

    async def job():
        calls.append(1)

    r1 = await scheduler.run_once("daily_review", job)
    r2 = await scheduler.run_once("daily_review", job)
    assert r1.status == "COMPLETED"
    assert r2.status == "DUPLICATE_SKIPPED"
    assert len(calls) == 1


def test_os_monitor_and_lifecycle():
    monitor = OSMonitor()
    monitor.record("cpu", 0.9, 0.8, "CPU_HIGH")
    assert "CPU_HIGH" in monitor.active_alerts()
    lifecycle = LifecycleStatus()
    lifecycle.gate("db", True)
    lifecycle.gate("market", True)
    assert lifecycle.is_ready() is True


async def test_backup_orchestrator():
    orchestrator = BackupOrchestrator()
    await orchestrator.backup("b1")
    assert (await orchestrator.restore("b1")).status == "RESTORED"
    assert (await orchestrator.restore("missing")).status == "NOT_FOUND"


def test_maintenance_and_upgrades():
    maintenance = MaintenanceManager()
    maintenance.schedule("2026-08-25T00:00:00+00:00", "2026-08-25T02:00:00+00:00", "db")
    assert len(maintenance.active()) >= 0
    upgrades = UpgradeManager()
    upgrades.deploy("v1")
    upgrades.deploy("v2")
    rollback = upgrades.rollback()
    assert rollback is not None and rollback.version == "v1"


def test_deployment_gate_never_live():
    gate = DeploymentGate()
    result = gate.evaluate(
        certification_score=50,
        shadow_days=10,
        demo_days=10,
        max_drawdown_pct=Decimal("30"),
        profit_factor=Decimal("1.0"),
        risk_violations=2,
    )
    assert result.status == "NOT_READY"
    assert result.live_enabled is False
    ready = gate.evaluate(
        certification_score=90,
        shadow_days=120,
        demo_days=120,
        max_drawdown_pct=Decimal("10"),
        profit_factor=Decimal("1.5"),
        risk_violations=0,
    )
    assert ready.status == "READY"
    assert ready.live_enabled is False


def test_capital_approval_manual_required():
    approval = CapitalApproval()
    assert approval.required() is True
    approval.approve("human", "approved")
    assert approval.required() is False
