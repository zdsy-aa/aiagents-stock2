# -*- coding: utf-8 -*-
"""automation.alert 失败告警(Phase5 Task5.1):收集 run_jobs 的 failed → 日志 + 邮件。

- :func:`alert_failures` (res, mail=True):从 run_jobs 返回的结果字典收集
  failed 任务列表 → 输出告警摘要(print + logger);``mail=True`` 时经
  :func:`send_mail` 发邮件,``mail=False`` 仅日志,不触碰邮件通道。
- :func:`send_mail` (subject, body):发纯文本邮件。复用 ops/send_mail.py 的
  load_env(.env 163 SMTP 配置)与同款 SMTP_SSL 发送逻辑,**不修改
  ops/send_mail.py 本体**;发送失败仅记日志并返回 False,不抛异常(告警通道
  自身失败不得打断自动化主流程)。

注入约定:automation.jobs 在调用时把发送器解析为 ``jobs.send_mail``
(见 jobs.alert_failures 包装),测试 monkeypatch ``jobs.send_mail`` 即生效。
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


def alert_failures(res, mail=True, _sender=None):
    """收集 run_jobs 结果中的 failed 任务 → 告警摘要 + (可选)邮件。

    Args:
        res: run_jobs 返回的 {name: ok|failed|skipped} 结果字典。
        mail: True 时经 send_mail 发信;False 仅日志(不触碰邮件通道)。
        _sender: 邮件发送器(默认本模块 send_mail)。automation.jobs 的包装
            传入 ``jobs.send_mail``,使 monkeypatch ``jobs.send_mail`` 可注入。

    Returns:
        None(告警通道失败不抛异常,不打断主流程)。
    """
    failed = sorted(name for name, status in (res or {}).items() if status == "failed")
    if not failed:
        print("本轮自动化任务无失败,跳过告警")
        return
    summary = "自动化任务失败告警:" + "、".join(failed)
    print(summary)
    logger.warning(summary)
    if not mail:
        return
    subject = f"[自动化风控复盘] {len(failed)} 个任务失败({time.strftime('%Y-%m-%d %H:%M')})"
    body = f"{summary}\n失败任务列表:\n" + "\n".join(f"- {name}: failed" for name in failed)
    try:
        (_sender or send_mail)(subject, body)
    except Exception as exc:
        logger.warning("失败告警邮件发送异常: %s", exc)
