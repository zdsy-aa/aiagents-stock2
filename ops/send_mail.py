#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 读取 aiagents-stock/.env 里的 163 SMTP 配置，发送纯文本邮件。
# 163 用 465 端口 = 隐式SSL，必须 SMTP_SSL，不能 starttls。
# 用法: send_mail.py "<邮件主题>" <正文文件路径>
import sys, smtplib, ssl
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

ENV_PATH = "/home/tdxback/aiagents-stock/.env"

def load_env(path):
    cfg = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg

def main():
    if len(sys.argv) < 3:
        print("用法: send_mail.py \"<主题>\" <正文文件路径>", file=sys.stderr)
        sys.exit(2)
    subject = sys.argv[1]
    with open(sys.argv[2], encoding="utf-8", errors="replace") as f:
        body = f.read()

    c = load_env(ENV_PATH)
    if c.get("EMAIL_ENABLED", "true").lower() not in ("true", "1", "yes"):
        print("EMAIL_ENABLED 非 true，跳过发信")
        return
    server = c.get("SMTP_SERVER", "smtp.163.com")
    port   = int(c.get("SMTP_PORT", "465"))
    sender = c["EMAIL_FROM"]
    passwd = c["EMAIL_PASSWORD"]
    tos = [x.strip() for x in c["EMAIL_TO"].replace(";", ",").split(",") if x.strip()]

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("服务器检核", sender))
    msg["To"] = ",".join(tos)

    ctx = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(server, port, context=ctx, timeout=25)
    else:
        smtp = smtplib.SMTP(server, port, timeout=25)
        smtp.starttls(context=ctx)
    with smtp:
        smtp.login(sender, passwd)
        smtp.sendmail(sender, tos, msg.as_string())
    print(f"邮件已发送 -> {tos}")

if __name__ == "__main__":
    main()
