import json

from quant_system.config.app_config import feishu_config, save_data_source_config, save_tickflow_config, tickflow_config, tushare_config


def test_tickflow_config_file_round_trip(tmp_path):
    path = tmp_path / "local.json"
    save_tickflow_config("secret-key", "https://example.test", path)
    assert tickflow_config(path) == {"api_key": "secret-key", "base_url": "https://example.test"}
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["tickflow"]["api_key"] == "secret-key"


def test_feishu_config_round_trip(tmp_path):
    path = tmp_path / "local.json"
    save_data_source_config(feishu_webhook_url="https://example.test/hook/secret", path=path)
    assert feishu_config(path)["webhook_url"].endswith("/secret")
    assert path.stat().st_mode & 0o777 == 0o600


def test_data_source_config_preserves_existing_keys(tmp_path):
    path = tmp_path / "local.json"
    save_data_source_config(tickflow_api_key="tick", tushare_token="ts", path=path)
    save_data_source_config(tushare_token="new-ts", path=path)

    assert tickflow_config(path)["api_key"] == "tick"
    assert tushare_config(path)["token"] == "new-ts"
    assert path.stat().st_mode & 0o777 == 0o600
