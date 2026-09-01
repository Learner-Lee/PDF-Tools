"""Provider 档案存储：密钥不外泄、编辑不丢失。"""
from app.store import ProviderProfile, SettingsStore


def _store(tmp_path):
    # seed=False：不让本机 .env 渗进测试库
    return SettingsStore(tmp_path / "t.db", seed=False)


def test_api_key_is_masked(tmp_path):
    s = _store(tmp_path)
    s.upsert(ProviderProfile(id="a", label="A", base_url="https://x/v1",
                             api_key="sk-1234567890abcdef"))
    m = s.get("a").masked()
    assert "sk-1234567890abcdef" not in str(m)
    assert m["has_key"] is True


def test_blank_key_does_not_erase_existing(tmp_path):
    """前端回显的是遮蔽值，提交时若密钥为空必须视为"不改动"。"""
    s = _store(tmp_path)
    s.upsert(ProviderProfile(id="a", label="A", base_url="https://x/v1", api_key="sk-real"))
    s.upsert(ProviderProfile(id="a", label="改了名", base_url="https://y/v1", api_key=""))

    p = s.get("a")
    assert p.api_key == "sk-real"
    assert p.label == "改了名" and p.base_url == "https://y/v1"


def test_first_profile_becomes_active(tmp_path):
    s = _store(tmp_path)
    s.upsert(ProviderProfile(id="a", label="A", base_url="https://x/v1"))
    assert s.active_id() == "a"


def test_deleting_active_falls_back(tmp_path):
    s = _store(tmp_path)
    s.upsert(ProviderProfile(id="a", label="A", base_url="https://x/v1"))
    s.upsert(ProviderProfile(id="b", label="B", base_url="https://y/v1"))
    s.set_active("a")
    s.delete("a")
    assert s.active_id() == "b"


def test_extra_body_roundtrips(tmp_path):
    s = _store(tmp_path)
    s.upsert(ProviderProfile(id="a", label="A", base_url="https://x/v1",
                             extra_body={"enable_thinking": False}))
    assert s.get("a").extra_body == {"enable_thinking": False}


def test_placeholder_env_key_is_treated_as_unset(tmp_path, monkeypatch):
    """全新部署时 .env 里是占位符，不能报告成"已配置"。

    否则用户以为能用，一调就鉴权失败，还查不出原因。
    """
    import app.store as store_mod

    class Env:
        qwen_base_url = "https://api.example.com/v1"
        qwen_model_translate = "m"
        qwen_model_gloss = "m"
        qwen_api_key = "sk-xxxxxxxx"

    monkeypatch.setattr(store_mod, "env", Env)
    s = SettingsStore(tmp_path / "seed.db")
    assert s.active().api_key == ""


def test_real_env_key_is_seeded(tmp_path, monkeypatch):
    import app.store as store_mod

    class Env:
        qwen_base_url = "https://api.example.com/v1"
        qwen_model_translate = "m"
        qwen_model_gloss = "m"
        qwen_api_key = "sk-sp-real-key-123"

    monkeypatch.setattr(store_mod, "env", Env)
    s = SettingsStore(tmp_path / "seed.db")
    assert s.active().api_key == "sk-sp-real-key-123"
