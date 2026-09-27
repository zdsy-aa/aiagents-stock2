# -*- coding: utf-8 -*-
"""automation.notify 统一提醒通道测试(Phase5 Task5.4)。

全部用例不真实发信、不发 Telegram:邮件发送函数一律 monkeypatch;Telegram 只覆盖
未配置(disabled)与假 _urlopen 注入两条路径,不产生任何网络请求。
"""
import json

import automation.notify as nt


# ---- 简报用例(逐字保留) ----

def test_notify_log_only(monkeypatch, capsys):
    monkeypatch.setenv("TG_BOT_TOKEN", "")           # 未配置
    r = nt.notify("测试消息", channels=["log", "telegram"])
    assert r["log"] == "ok" and r["telegram"] == "disabled"
    assert "测试消息" in capsys.readouterr().out


def test_notify_mail_failure_isolated(monkeypatch):
    def boom(subj, body): raise RuntimeError("smtp down")
    monkeypatch.setattr(nt, "_send_mail", boom)
    r = nt.notify("x", channels=["mail", "log"])
    assert r["mail"] == "failed" and r["log"] == "ok"


# ---- 补充用例:默认通道 / 单通道隔离 / 配置分支 ----

def test_default_channels_log_and_mail(monkeypatch, capsys):
    """默认通道为 log+mail,不含 telegram;level 出现在日志与邮件正文。"""
    sent = {}

    def fake_mail(subj, body):
        sent["subject"], sent["body"] = subj, body
        return "ok"

    monkeypatch.setattr(nt, "_send_mail", fake_mail)
    r = nt.notify("默认通道消息", level="WARNING")
    assert r == {"log": "ok", "mail": "ok"}
    out = capsys.readouterr().out
    assert "WARNING" in out and "默认通道消息" in out
    assert "默认通道消息" in sent["body"]


def test_all_three_channels_ok(monkeypatch, capsys):
    """三通道齐全时各返回 ok;Telegram 经假 _urlopen 验证 URL 与报文体。"""
    monkeypatch.setenv("TG_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TG_CHAT_ID", "chat456")
    monkeypatch.setattr(nt, "_send_mail", lambda subj, body: "ok")
    calls = []

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return FakeResp()

    monkeypatch.setattr(nt, "_urlopen", fake_urlopen)
    r = nt.notify("三通道消息", channels=["log", "mail", "telegram"])
    assert r == {"log": "ok", "mail": "ok", "telegram": "ok"}
    assert len(calls) == 1
    assert "tok123" in calls[0].full_url and "sendMessage" in calls[0].full_url
    payload = json.loads(calls[0].data.decode("utf-8"))
    assert payload["chat_id"] == "chat456" and "三通道消息" in payload["text"]


def test_telegram_failure_isolated(monkeypatch, capsys):
    """Telegram 发送异常只影响自身,log 通道照常 ok。"""
    monkeypatch.setenv("TG_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TG_CHAT_ID", "chat456")

    def boom(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(nt, "_urlopen", boom)
    r = nt.notify("x", channels=["telegram", "log"])
    assert r["telegram"] == "failed" and r["log"] == "ok"
    assert "x" in capsys.readouterr().out


def test_telegram_disabled_without_config(monkeypatch):
    """token/chat_id 任一缺失即 disabled,且不发起请求。"""
    monkeypatch.setenv("TG_BOT_TOKEN", "")
    monkeypatch.setenv("TG_CHAT_ID", "chat456")

    def should_not_call(req, timeout=None):
        raise AssertionError("未配置时不应发起 Telegram 请求")

    monkeypatch.setattr(nt, "_urlopen", should_not_call)
    assert nt.notify("x", channels=["telegram"]) == {"telegram": "disabled"}


def test_mail_disabled_when_email_disabled(monkeypatch):
    """EMAIL_ENABLED 非 true 时 mail 通道返回 disabled,且不触碰发送函数。"""
    monkeypatch.setattr(nt, "_load_env", lambda: {"EMAIL_ENABLED": "false"})
    monkeypatch.setattr(
        nt, "_alert_send_mail",
        lambda subj, body: (_ for _ in ()).throw(AssertionError("不应发信")),
    )
    assert nt.notify("x", channels=["mail"]) == {"mail": "disabled"}


def test_unknown_channel_marked_failed(monkeypatch, capsys):
    """未知通道名单通道标 failed,其余通道不受影响。"""
    r = nt.notify("x", channels=["log", "sms"])
    assert r == {"log": "ok", "sms": "failed"}
    assert "x" in capsys.readouterr().out


def test_empty_channels_returns_empty_dict():
    """channels 为空列表返回空字典,不触碰任何通道。"""
    assert nt.notify("x", channels=[]) == {}


def test_channels_accepts_single_string(capsys):
    """单个字符串按单通道处理,不按字符拆开。"""
    assert nt.notify("x", channels="log") == {"log": "ok"}
    assert "x" in capsys.readouterr().out
