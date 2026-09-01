"""Provider 兼容性：不同厂商对附加参数的容忍度不同，必须能自动适配。"""
import json

from app.translator.base import OpenAICompatProvider, parse_segments


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    @property
    def text(self):
        return json.dumps(self._b, ensure_ascii=False)

    def json(self):
        return self._b


class _StrictClient:
    """模拟 OpenAI 风格端点：不认识的请求体字段直接 400。"""

    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append(json)
        if "enable_thinking" in json:
            return _Resp(400, {"error": {"message": "Unrecognized request argument supplied: enable_thinking"}})
        return _Resp(200, {
            "choices": [{"message": {"content": "你好，世界。"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

    def close(self):
        pass


def _provider(client):
    p = OpenAICompatProvider(
        "https://fake/v1", "k", "m", name="fake",
        extra_body={"enable_thinking": False},
    )
    p._client = client
    return p


def test_unsupported_extra_body_falls_back():
    """把通义特有的 enable_thinking 发给不认识它的端点，应自动去掉重试。"""
    c = _StrictClient()
    p = _provider(c)
    text, _ = p.chat("sys", "user")

    assert text == "你好，世界。"
    assert len(c.calls) == 2                        # 首次失败 + 降级重试
    assert "enable_thinking" in c.calls[0]
    assert "enable_thinking" not in c.calls[1]
    assert p._extra_ok is False


def test_fallback_is_remembered():
    """降级后不再对每个请求重复试探。"""
    c = _StrictClient()
    p = _provider(c)
    p.chat("sys", "user")
    c.calls.clear()
    p.chat("sys", "user2")

    assert len(c.calls) == 1
    assert "enable_thinking" not in c.calls[0]


def test_extra_body_kept_when_supported():
    """端点接受该参数时必须保留 —— 通义关掉思考能省约 40 倍成本。"""
    class Lenient(_StrictClient):
        def post(self, url, json=None, headers=None):
            self.calls.append(json)
            return _Resp(200, {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            })

    c = Lenient()
    p = _provider(c)
    p.chat("sys", "user")
    assert c.calls[0]["enable_thinking"] is False
    assert p._extra_ok is True


def test_no_auth_header_without_key():
    """本地模型（Ollama / llama.cpp）通常不需要密钥，不该硬塞 Authorization。"""
    p = OpenAICompatProvider("http://localhost:8080/v1", "", "local")
    assert "Authorization" not in p._headers()
    p2 = OpenAICompatProvider("https://api.example.com/v1", "sk-x", "m")
    assert p2._headers()["Authorization"] == "Bearer sk-x"


def test_parse_segments_tolerates_real_model_output():
    """实测模型会返回这几种格式，都必须解析出来。"""
    assert parse_segments('[{"id":0,"zh":"甲"},{"id":1,"zh":"乙"}]', 2) == {0: "甲", 1: "乙"}
    assert parse_segments('{"id":0,"zh":"裸对象"}', 1) == {0: "裸对象"}
    assert parse_segments("[0] 模仿输入的编号格式", 1) == {0: "模仿输入的编号格式"}
    assert parse_segments('```json\n[{"id":0,"zh":"围栏"}]\n```', 1) == {0: "围栏"}
    assert parse_segments("整段就是译文", 1) == {0: "整段就是译文"}


def test_cache_id_ignores_profile_name():
    """缓存归属看端点+模型，不看档案名 —— 改名或重建档案不该让缓存失效。"""
    a = OpenAICompatProvider("https://api.x.com/v1", "k", "m", name="我的配置")
    b = OpenAICompatProvider("https://api.x.com/v1", "k", "m", name="换个名字")
    assert a.cache_id == b.cache_id

    c = OpenAICompatProvider("https://other.com/v1", "k", "m", name="我的配置")
    assert a.cache_id != c.cache_id


def test_strips_echoed_segment_marker():
    """模型会把输入的 [N] 标号抄进译文值里，必须剥掉。"""
    raw = '[{"id":0,"zh":"[0] 条件"},{"id":1,"zh":"[1] GPT-5"}]'
    assert parse_segments(raw, 2) == {0: "条件", 1: "GPT-5"}


def test_keeps_unrelated_bracket_numbers():
    """编号与段号不一致时是正文内容，不能动。"""
    raw = '[{"id":0,"zh":"[12] 见参考文献"}]'
    assert parse_segments(raw, 1) == {0: "[12] 见参考文献"}


def test_word_list_excludes_hyphen_fragments():
    """词表不能被它本该消歧的断词碎片污染。

    "Daphne Ip-" / "polito," 若让 ip 与 polito 双双进表，
    "两半各自成词"这条判据就会把 Ippolito 误判成复合词。
    """
    from app.parser.extract import collect_words

    words = collect_words(["Daphne Ip-", "polito, and Chris wrote this paper"])
    assert "ip" not in words
    assert "polito" not in words
    assert "chris" in words and "paper" in words
