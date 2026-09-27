# -*- coding: utf-8 -*-
"""automation.notify 统一提醒通道(Phase5 Task5.4):日志 / 邮件 / Telegram。

``notify(msg, level="INFO", channels=None)`` 把一条提醒投递到一个或多个通道,
返回 ``{channel: "ok"|"disabled"|"failed"}``(channels 默认 ``["log", "mail"]``)。

- log:print + logger,恒可用;
- mail:复用 automation.alert.send_mail —— 其内部即 ops/send_mail.py 的
  load_env(.env)与 SMTP_SSL 口径(**不修改 send_mail 本体**);EMAIL_ENABLED
  非 true → disabled;
- telegram:token/chat 取 TG_BOT_TOKEN/TG_CHAT_ID(环境变量优先,回退 .env),
  任一缺失 → disabled 且不发请求;发送用 urllib 直发(不引第三方库)。

单通道失败或多通道异常只影响自身状态,其余通道照常投递;notify 不抛异常。
本模块只依赖标准库,便于单测与后续任务复用。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

from automation.alert import send_mail as _alert_send_mail

logger = logging.getLogger(__name__)

__all__ = ["notify"]

DEFAULT_CHANNELS = ("log", "mail")
_TG_API = "https://api.telegram.org/bot{token}/sendMessage"
# 模块级别名:测试 monkeypatch nt._urlopen 即可拦截 Telegram 网络调用
_urlopen = urllib.request.urlopen

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}


def _load_env():
    """读 .env 配置,复用 ops/send_mail.py 的 load_env(不改其本体)。"""
    try:
        from ops.send_mail import ENV_PATH, load_env

        return load_env(ENV_PATH)
    except Exception as exc:  # .env 缺失/不可读时退化为空配置,不外抛
        logger.warning("notify 读取 .env 失败: %s", exc)
        return {}


def _pick(key, cfg):
    """配置取值:环境变量已设置(含空串)优先,否则回退 .env。"""
    if key in os.environ:
        return os.environ[key].strip()
    return (cfg.get(key) or "").strip()


def _as_status(value):
    """把通道实现的返回值归一为 ok/disabled/failed(兼容注入的假实现)。"""
    if value in ("ok", "disabled", "failed"):
        return value
    return "ok" if value else "failed"


def _channel_log(msg, level):
    """日志通道:stdout + logger(不依赖任何外部配置)。"""
    print(f"[{level}] {msg}")
    logger.log(_LEVELS.get(str(level).upper(), logging.INFO), "%s", msg)
    return "ok"


def _send_mail(subject, body):
    """发纯文本邮件,返回 ok/disabled/failed(不抛异常)。

    复用 automation.alert.send_mail(其内部即 ops/send_mail.py 的 load_env 与
    SMTP_SSL 口径);EMAIL_ENABLED 非 true → disabled,不触碰 SMTP。
    """
    cfg = _load_env()
    if cfg.get("EMAIL_ENABLED", "true").lower() not in ("true", "1", "yes"):
        logger.info("EMAIL_ENABLED 非 true,mail 通道 disabled")
        return "disabled"
    return "ok" if _alert_send_mail(subject, body) else "failed"


def _channel_mail(msg, level):
    subject = f"[自动化提醒][{level}] " + (str(msg).splitlines() or [""])[0][:60]
    return _as_status(_send_mail(subject, str(msg)))


def _send_telegram(token, chat_id, text):
    """urllib 直发 Telegram sendMessage;HTTP 非 200 抛异常(由调用方转 failed)。"""
    data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        _TG_API.format(token=token), data=data, headers={"Content-Type": "application/json"}
    )
    with _urlopen(req, timeout=10) as resp:
        status = getattr(resp, "status", 200)
    if status != 200:
        raise RuntimeError(f"Telegram HTTP {status}")
    return True


def _channel_telegram(msg, level):
    cfg = _load_env()
    token = _pick("TG_BOT_TOKEN", cfg)
    chat_id = _pick("TG_CHAT_ID", cfg)
    if not token or not chat_id:
        logger.info("TG_BOT_TOKEN/TG_CHAT_ID 未配置,telegram 通道 disabled")
        return "disabled"
    return _as_status(_send_telegram(token, chat_id, f"[{level}] {msg}"))


_CHANNEL_FNS = {"log": _channel_log, "mail": _channel_mail, "telegram": _channel_telegram}


def notify(msg, level="INFO", channels=None):
    """把提醒投递到指定通道,返回 {channel: "ok"|"disabled"|"failed"}。

    Args:
        msg: 提醒正文(任意可 str 化对象)。
        level: 级别标签,仅用于日志/邮件主题/Telegram 文本,默认 "INFO"。
        channels: 通道名序列,默认 ["log", "mail"];单个字符串按单通道处理;
            未知通道名标 "failed"(记 warning),不影响其他通道。

    Returns:
        dict: 本次请求的每个通道 → ok(已投递)/ disabled(未配置,未投递)/
        failed(投递失败)。notify 自身不抛异常。
    """
    if isinstance(channels, str):
        channels = [channels]
    chans = list(DEFAULT_CHANNELS if channels is None else channels)
    out = {}
    for ch in chans:
        name = str(ch).strip().lower()
        fn = _CHANNEL_FNS.get(name)
        if fn is None:
            logger.warning("未知提醒通道 %r,该通道标 failed", ch)
            out[name] = "failed"
            continue
        try:
            out[name] = fn(msg, level)
        except Exception as exc:  # 单通道失败不得影响其他通道
            logger.warning("%s 通道提醒失败: %s", name, exc)
            out[name] = "failed"
    return out
