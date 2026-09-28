from pathlib import Path

import pytest

from ingest.main import Config, load_config, parse_dotenv, run
from ingest.use_case import IngestReport

REQUIRED_ENV = {
    "DRIVE_FOLDER_ID": "folder-123",
    "GOOGLE_API_KEY": "api-key-1",
    "R2_ACCOUNT_ID": "account-1",
    "R2_ACCESS_KEY_ID": "key-id",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET": "bucket-1",
    "R2_PUBLIC_BASE_URL": "https://videos.example.com",
}


def test_load_config_builds_config_with_defaults():
    config = load_config(REQUIRED_ENV)

    assert isinstance(config, Config)
    assert config.drive_folder_id == "folder-123"
    assert config.google_api_key == "api-key-1"
    assert config.google_service_account_file is None
    assert config.r2_account_id == "account-1"
    assert config.r2_access_key_id == "key-id"
    assert config.r2_secret_access_key == "secret"
    assert config.r2_bucket == "bucket-1"
    assert config.r2_public_base_url == "https://videos.example.com"
    assert config.manifest_path == Path("site/manifest.json")
    assert config.state_path == Path("ingest/state.json")


def _env_with_bucket(**extra):
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "R2_BUCKET"}
    env.update(extra)
    return env


def test_load_config_accepts_r2_bucket_name():
    config = load_config(_env_with_bucket(R2_BUCKET_NAME="named-bucket"))

    assert config.r2_bucket == "named-bucket"


def test_load_config_still_accepts_legacy_r2_bucket():
    config = load_config(_env_with_bucket(R2_BUCKET="legacy-bucket"))

    assert config.r2_bucket == "legacy-bucket"


def test_load_config_missing_bucket_lists_canonical_name():
    with pytest.raises(ValueError) as exc_info:
        load_config(_env_with_bucket())

    assert "R2_BUCKET_NAME" in str(exc_info.value)


def test_load_config_reads_optional_r2_endpoint():
    assert load_config(REQUIRED_ENV).r2_endpoint is None

    config = load_config({**REQUIRED_ENV, "R2_ENDPOINT": "https://custom.example.com"})

    assert config.r2_endpoint == "https://custom.example.com"


def test_load_config_honors_optional_overrides():
    env = dict(REQUIRED_ENV)
    env["MANIFEST_PATH"] = "custom/manifest.json"
    env["STATE_PATH"] = "custom/state.json"
    env["WORKDIR"] = "custom/workdir"

    config = load_config(env)

    assert config.manifest_path == Path("custom/manifest.json")
    assert config.state_path == Path("custom/state.json")
    assert config.workdir == Path("custom/workdir")


def test_load_config_raises_with_every_missing_var_name():
    env = {"DRIVE_FOLDER_ID": "folder-123"}

    with pytest.raises(ValueError) as exc_info:
        load_config(env)

    message = str(exc_info.value)
    for missing in (
        "GOOGLE_API_KEY",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_BASE_URL",
    ):
        assert missing in message
    assert "DRIVE_FOLDER_ID" not in message.split(":", 1)[1]


def test_parse_dotenv_ignores_comments_and_blank_lines():
    text = """
# a comment
DRIVE_FOLDER_ID=folder-abc

R2_BUCKET=my-bucket
# another comment
R2_PUBLIC_BASE_URL=https://videos.example.com
"""

    result = parse_dotenv(text)

    assert result == {
        "DRIVE_FOLDER_ID": "folder-abc",
        "R2_BUCKET": "my-bucket",
        "R2_PUBLIC_BASE_URL": "https://videos.example.com",
    }


def test_apply_dotenv_does_not_override_existing_env_vars():
    from ingest.main import apply_dotenv

    env = {"R2_BUCKET": "already-set-bucket"}
    text = "R2_BUCKET=from-dotenv\nDRIVE_FOLDER_ID=folder-abc\n"

    apply_dotenv(text, env)

    assert env["R2_BUCKET"] == "already-set-bucket"
    assert env["DRIVE_FOLDER_ID"] == "folder-abc"


def test_run_wires_source_and_publisher_and_returns_report(tmp_path):
    env = dict(REQUIRED_ENV)
    env["MANIFEST_PATH"] = str(tmp_path / "manifest.json")
    env["STATE_PATH"] = str(tmp_path / "state.json")
    env["WORKDIR"] = str(tmp_path / "work")
    config = load_config(env)

    source_calls = []
    publisher_calls = []

    class FakeSource:
        def list_zips(self):
            return []

    class FakePublisher:
        pass

    def source_builder(cfg):
        source_calls.append(cfg)
        return FakeSource()

    def publisher_builder(cfg):
        publisher_calls.append(cfg)
        return FakePublisher()

    report = run(config, source_builder=source_builder, publisher_builder=publisher_builder)

    assert isinstance(report, IngestReport)
    assert report.processed == []
    assert len(source_calls) == 1
    assert len(publisher_calls) == 1


def test_load_config_accepts_service_account_alone():
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "GOOGLE_API_KEY"}
    env["GOOGLE_SERVICE_ACCOUNT_FILE"] = "/creds/sa.json"

    config = load_config(env)

    assert config.google_api_key is None
    assert config.google_service_account_file == Path("/creds/sa.json")


def test_load_config_without_any_google_credential_names_api_key():
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "GOOGLE_API_KEY"}

    with pytest.raises(ValueError) as exc_info:
        load_config(env)

    assert "GOOGLE_API_KEY" in str(exc_info.value)


def _run_with_patched_builders(monkeypatch, env):
    import ingest.main as main_mod

    calls = []
    monkeypatch.setattr(
        main_mod, "build_drive_source_with_api_key",
        lambda folder_id, api_key: calls.append(("key", folder_id, api_key)) or _EmptySource(),
    )
    monkeypatch.setattr(
        main_mod, "build_drive_source",
        lambda folder_id, path: calls.append(("sa", folder_id, path)) or _EmptySource(),
    )
    run(load_config(env), publisher_builder=lambda cfg: object())
    return calls


class _EmptySource:
    def list_zips(self):
        return []


def test_run_uses_api_key_builder_when_key_set(monkeypatch, tmp_path):
    env = {**REQUIRED_ENV, "GOOGLE_SERVICE_ACCOUNT_FILE": "/creds/sa.json",
           "MANIFEST_PATH": str(tmp_path / "m.json"), "STATE_PATH": str(tmp_path / "s.json"),
           "WORKDIR": str(tmp_path / "w")}

    calls = _run_with_patched_builders(monkeypatch, env)

    assert calls == [("key", "folder-123", "api-key-1")]


def test_run_uses_service_account_builder_when_no_key(monkeypatch, tmp_path):
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "GOOGLE_API_KEY"}
    env.update({"GOOGLE_SERVICE_ACCOUNT_FILE": "/creds/sa.json",
                "MANIFEST_PATH": str(tmp_path / "m.json"), "STATE_PATH": str(tmp_path / "s.json"),
                "WORKDIR": str(tmp_path / "w")})

    calls = _run_with_patched_builders(monkeypatch, env)

    assert calls == [("sa", "folder-123", Path("/creds/sa.json"))]


def test_load_config_max_zips_per_run_defaults_to_10():
    assert load_config(REQUIRED_ENV).max_zips_per_run == 10


def test_load_config_parses_max_zips_per_run():
    assert load_config({**REQUIRED_ENV, "MAX_ZIPS_PER_RUN": "3"}).max_zips_per_run == 3


def test_run_passes_max_zips_to_use_case(monkeypatch, tmp_path):
    import ingest.main as main_mod

    captured = {}

    def fake_run_ingest(**kwargs):
        captured.update(kwargs)
        return IngestReport()

    monkeypatch.setattr(main_mod, "run_ingest", fake_run_ingest)
    env = {
        **REQUIRED_ENV,
        "MAX_ZIPS_PER_RUN": "4",
        "STATE_PATH": str(tmp_path / "s.json"),
        "WORKDIR": str(tmp_path / "w"),
    }

    run(load_config(env), source_builder=lambda c: None, publisher_builder=lambda c: None)

    assert captured["max_zips"] == 4
