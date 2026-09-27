# -*- coding: utf-8 -*-
"""automation.alert 失败告警(Phase5 Task5.1):收集 run_jobs 的 failed → 统一提醒。

- :func:`alert_failures` (res, mail=True):从 run_jobs 返回的结果字典收集
  failed 任务列表 → 经 automation.notify.notify 统一通道投递(终审修复波
  接线,5.4):``mail=False`` 时 channels=["log"](仅日志,输出 stdout);
  ``mail=True`` 时 channels=["log","mail"]。
- :func:`send_mail` (subject, body):发纯文本邮件。复用 ops/send_mail.py 的
  load_env(.env 163 SMTP 配置)与同款 SMTP_SSL 发送逻辑,**不修改
  ops/send_mail.py 本体**;发送失败仅记日志并返回 False,不抛异常(告警通道
  自身失败不得打断自动化主流程);notify 的 mail 通道内部即复用本函数。

注入约定:alert_failures 延迟 import automation.notify.notify(notify 模块级
引用本模块 send_mail,延迟 import 避免环依赖),测试 monkeypatch
``automation.notify.notify`` 即生效。
"""
import logging
import time

logger = logging.getLogger(__name__)

__all__ = ["alert_failures", "send_mail"]


def send_mail(subject, body):
    """发纯文本邮件(163 SMTP,.env 配置,同 ops/send_mail.py 口径)。

    Returns:
        True 发送成功;False 配置关闭(EMAIL_ENABLED 非 true)或发送失败。
    """
    import smtplib
    import ssl
    from email.header import Header
    from email.mime.text import MIMEText
    from email.utils import formataddr

    try:
        from ops.send_mail import ENV_PATH, load_env

        cfg = load_env(ENV_PATH)
        if cfg.get("EMAIL_ENABLED", "true").lower() not in ("true", "1", "yes"):
            logger.info("EMAIL_ENABLED 非 true,跳过发信")
            return False
        server = cfg.get("SMTP_SERVER", "smtp.163.com")
        port = int(cfg.get("SMTP_PORT", "465"))
        sender = cfg["EMAIL_FROM"]
        passwd = cfg["EMAIL_PASSWORD"]
        tos = [x.strip() for x in cfg["EMAIL_TO"].replace(";", ",").split(",") if x.strip()]

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr(("服务器检核", sender))
        msg["To"] = ",".join(tos)

        ctx = ssl.create_default_context()
        if port == 465:  # 163 隐式 SSL,同 ops/send_mail.py
            smtp = smtplib.SMTP_SSL(server, port, context=ctx, timeout=25)
        else:
            smtp = smtplib.SMTP(server, port, timeout=25)
            smtp.starttls(context=ctx)
        with smtp:
            smtp.login(sender, passwd)
            smtp.sendmail(sender, tos, msg.as_string())
        logger.info("失败告警邮件已发送 -> %s", tos)
        return True
    except Exception as exc:
        logger.warning("失败告警邮件发送失败: %s", exc)
        return False


def alert_failures(res, mail=True):
    """收集 run_jobs 结果中的 failed 任务 → 统一 notify 通道(5.4 接线)。

    Args:
        res: run_jobs 返回的 {name: ok|failed|skipped} 结果字典。
        mail: True 时 channels=["log","mail"];False 仅 ["log"]
            (log 通道输出 stdout,不触碰邮件通道)。

    Returns:
        None(告警通道失败不抛异常,不打断主流程)。
    """
    from automation.notify import notify  # 延迟 import:notify 模块级引用 alert.send_mail

    failed = sorted(name for name, status in (res or {}).items() if status == "failed")
    if not failed:
        notify("本轮自动化任务无失败,跳过告警", channels=["log"])
        return
    summary = "自动化任务失败告警:" + "、".join(failed)
    logger.warning(summary)
    channels = ["log", "mail"] if mail else ["log"]
    msg = summary
    if mail:
        subject = (f"[自动化风控复盘] {len(failed)} 个任务失败"
                   f"({time.strftime('%Y-%m-%d %H:%M')})")
        body = f"{summary}\n失败任务列表:\n" + "\n".join(
            f"- {name}: failed" for name in failed)
        msg = f"{subject}\n{body}"
    try:
        notify(msg, level="ERROR", channels=channels)
    except Exception as exc:  # notify 自身不抛,防御保留
        logger.warning("失败告警提醒异常: %s", exc)
