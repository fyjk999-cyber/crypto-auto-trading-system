import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (
    ("com.lowrisk.mlcollector.plist", "com.lowrisk.mlcollector", "ml_collector"),
    ("com.lowrisk.mltrainer.plist", "com.lowrisk.mltrainer", "ml_trainer"),
    ("com.lowrisk.growth.plist", "com.lowrisk.growth", "growth"),
)


def test_launchagent_templates_are_valid_and_secret_free():
    for filename, label, token in ARTIFACTS:
        doc = plistlib.loads((ROOT / "deploy/launchagents" / filename).read_bytes())
        assert doc["Label"] == label
        assert doc["RunAtLoad"] is True and doc["KeepAlive"] is True
        assert token in doc["ProgramArguments"][0]
        env = doc.get("EnvironmentVariables") or {}
        for key in env:
            assert not any(x in key.upper() for x in ("KEY", "SECRET", "TOKEN", "CREDENTIAL"))


def test_macos_wrappers_are_llm_free_and_use_durable_paths():
    for name, script in (
        ("run_ml_collector_macos.sh", "ml_collector.py"),
        ("run_ml_trainer_macos.sh", "ml_trainer.py"),
    ):
        text = (ROOT / "scripts" / name).read_text()
        for forbidden in ("DEEPSEEK", "GLM", "LLM_", "API_KEY"):
            assert forbidden not in text
        assert "PYTHONPATH" in text and "__PYTHON__" in text
        assert "data/ml" in text and script in text
        assert "/tmp" not in text
