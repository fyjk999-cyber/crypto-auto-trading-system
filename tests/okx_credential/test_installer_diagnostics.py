"""No administrator calls or host mutations in diagnostic regression tests."""

import errno
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_real_entrypoint_reports_safe_exception():
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "deploy/macos/install.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "INSTALL_STAGE = PREFLIGHT_PLATFORM" in result.stdout
    assert "ERROR_TYPE = RuntimeError" in result.stdout
    assert "CREDENTIALS_ENROLLED = NO" in result.stdout


def load_installer():
    spec = importlib.util.spec_from_file_location(
        "installer_diagnostics", ROOT / "deploy/macos/install.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host(monkeypatch, tmp_path):
    mod = load_installer()
    monkeypatch.setattr(mod, "BASE", tmp_path / "install")
    monkeypatch.setattr(mod, "HOME", tmp_path / "broker")
    monkeypatch.setattr(mod, "DAEMONS", tmp_path / "daemons")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.os, "getuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", "test-client")
    client = SimpleNamespace(pw_uid=501, pw_gid=20, pw_name="test-client")

    def user(name):
        if name == "test-client":
            return client
        raise KeyError(name)

    def group(name):
        raise KeyError(name)

    monkeypatch.setattr(mod.pwd, "getpwnam", user)
    monkeypatch.setattr(mod.pwd, "getpwuid", lambda uid: client)
    monkeypatch.setattr(mod.pwd, "getpwall", lambda: [client])
    monkeypatch.setattr(mod.grp, "getgrnam", group)
    monkeypatch.setattr(mod.grp, "getgrall", lambda: [])
    calls = []

    def readonly_command(argv, **kwargs):
        calls.append(argv)
        assert argv[0] in {"/usr/bin/sudo", "/usr/bin/git"}
        assert "-create" not in argv
        return subprocess.CompletedProcess(argv, 0, stdout=b"(ALL) ALL", stderr=b"")

    monkeypatch.setattr(mod.subprocess, "run", readonly_command)
    return mod, calls


def forbid_mutations(monkeypatch, mod):
    def forbidden(*args, **kwargs):
        pytest.fail("Read-only preflight attempted a mutation")

    for method in ("mkdir", "write_text", "write_bytes", "chmod", "rename", "unlink", "symlink_to"):
        monkeypatch.setattr(Path, method, forbidden)
    monkeypatch.setattr(mod.os, "chown", forbidden)
    monkeypatch.setattr(mod.shutil, "copytree", forbidden)
    monkeypatch.setattr(mod.shutil, "copyfile", forbidden)


def test_successful_preflight_zero_mutations(host, monkeypatch, capsys):
    mod, calls = host
    forbid_mutations(monkeypatch, mod)
    assert mod.entry(["--preflight"]) == 0
    output = capsys.readouterr().out
    assert "PREFLIGHT_RESULT = PASS" in output
    assert "SYSTEM_MUTATIONS = ZERO" in output
    assert all("-create" not in args for args in calls)


def test_unprivileged_preflight_defers_root_audit(host, monkeypatch, capsys):
    mod, calls = host
    monkeypatch.setattr(mod.os, "getuid", lambda: 501)
    forbid_mutations(monkeypatch, mod)
    assert mod.entry(["--preflight"]) == 2
    assert all(args[0] != "/usr/bin/sudo" for args in calls)
    assert "PREFLIGHT_RESULT = ADMIN_AUDIT_REQUIRED" in capsys.readouterr().out


def test_missing_original_dscl_is_caught_before_mutation(host, monkeypatch, capsys):
    mod, calls = host
    monkeypatch.setattr(mod, "DSCL", "/usr/sbin/dscl")
    forbid_mutations(monkeypatch, mod)
    assert mod.entry(["--preflight"]) == 1
    output = capsys.readouterr().out
    assert "INSTALL_STAGE = CHECK_TOOLS_AND_RUNTIME" in output
    assert "ERROR_TYPE = FileNotFoundError" in output
    assert "ERROR_COMMAND = dscl" in output
    assert "ERROR_CODE = 2" in output
    assert all(args[0] != mod.DSCL for args in calls)


@pytest.mark.parametrize("mode", [[], ["--preflight"]])
@pytest.mark.parametrize("existing", ["BASE", "HOME", "daemon", "dangling_symlink"])
def test_existing_state_refused_without_mutation(host, monkeypatch, capsys, mode, existing):
    mod, _ = host
    if existing == "daemon":
        mod.DAEMONS.mkdir()
        (mod.DAEMONS / "com.crypto-trader.okx-broker.plist").write_text("preserve")
    elif existing == "dangling_symlink":
        mod.BASE.symlink_to(mod.HOME)
    else:
        getattr(mod, existing).mkdir()
    forbid_mutations(monkeypatch, mod)
    assert mod.entry(mode) == 1
    output = capsys.readouterr().out
    assert "INSTALL_STAGE = CHECK_EXISTING_INSTALL" in output
    assert "REQUIRES_ADMIN_REVIEW" in output or "EXISTING_DAEMON_REFUSED" in output


def test_uid_exhaustion_is_named(host, monkeypatch, capsys):
    mod, _ = host
    monkeypatch.setattr(
        mod.pwd, "getpwall", lambda: [SimpleNamespace(pw_uid=n) for n in range(450, 500)]
    )
    forbid_mutations(monkeypatch, mod)
    assert mod.entry(["--preflight"]) == 1
    assert "UID_GID_RANGE_EXHAUSTED" in capsys.readouterr().out


def test_command_failure_exposes_diagnostic_not_payload(host, monkeypatch, capsys):
    mod, _ = host
    canary = "private-diagnostic-canary-98204"
    monkeypatch.setenv("DIAGNOSTIC_SECRET", canary)

    def failed(argv, **kwargs):
        raise subprocess.CalledProcessError(
            13,
            ["sudo", canary],
            output=canary.encode(),
            stderr=f"Permission denied; ENV={canary}".encode(),
        )

    monkeypatch.setattr(mod.subprocess, "run", failed)
    forbid_mutations(monkeypatch, mod)
    assert mod.entry(["--preflight"]) == 1
    output = capsys.readouterr().out
    assert "INSTALL_STAGE = AUDIT_SUDOERS" in output
    assert "ERROR_TYPE = CalledProcessError" in output
    assert "ERROR_COMMAND = sudo" in output
    assert "ERROR_CODE = 13" in output
    assert "ERROR_DETAIL = Permission denied" in output
    assert canary not in output
    assert "ENV=" not in output


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("private-value-988"),
        KeyError("private-value-988"),
        ValueError("private-value-988"),
        OSError(errno.EACCES, "private-value-988"),
    ],
)
def test_exception_text_never_echoed(error, capsys):
    mod = load_installer()
    mod.report_error(error)
    text = capsys.readouterr().out
    assert "private-value-988" not in text
    assert f"ERROR_TYPE = {type(error).__name__}" in text
    assert "CREDENTIALS_ENROLLED = NO" in text


def test_unknown_stderr_is_not_echoed(capsys):
    mod = load_installer()
    mod.report_error(subprocess.CalledProcessError(1, "ignored", stderr=b"opaque-secret-742"))
    assert "opaque-secret-742" not in capsys.readouterr().out


def test_nopasswd_preflight_refuses_without_mutations(host, monkeypatch, capsys):
    mod, _ = host
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=b"(ALL) NOPASSWD: ALL"),
    )
    forbid_mutations(monkeypatch, mod)
    assert mod.entry(["--preflight"]) == 1
    assert "PASSWORDLESS_SUDO_RULES_REQUIRE_ADMIN_REVIEW" in capsys.readouterr().out


def test_correct_native_dscl_path():
    assert load_installer().DSCL == "/usr/bin/dscl"


def test_invalid_arguments_do_not_echo_secret(capsys):
    mod = load_installer()
    assert mod.entry(["--credential", "never-echo-this-9872"]) == 1
    output = capsys.readouterr()
    assert "never-echo-this-9872" not in output.out + output.err
    assert "INVALID_INSTALLER_ARGUMENTS" in output.out


def test_install_without_human_terminal_fails_before_mutation(host, monkeypatch, capsys):
    mod, _ = host
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    forbid_mutations(monkeypatch, mod)
    assert mod.entry([]) == 1
    output = capsys.readouterr().out
    assert "INSTALL_STAGE = CHECK_ENROLLMENT_TERMINAL" in output
    assert "HUMAN_TERMINAL_REQUIRED" in output
