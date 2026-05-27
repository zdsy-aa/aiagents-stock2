"""notification_service 统一传输入口：未配置时安全返回 False（不发任何真实通知）。"""
from notification_service import NotificationService


def _svc_empty():
    """构造一个配置为空的服务实例，确保不会真的发送邮件/Webhook。"""
    s = NotificationService()
    s.config = {
        'email_enabled': False, 'smtp_server': '', 'smtp_port': 587,
        'email_from': '', 'email_password': '', 'email_to': '',
        'webhook_enabled': False, 'webhook_url': '',
        'webhook_type': 'dingtalk', 'webhook_keyword': '',
    }
    return s


def test_send_email_incomplete_config_returns_false():
    # 配置不完整时应直接返回 False，不尝试连接 SMTP
    assert _svc_empty().send_email("subj", "body") is False


def test_send_webhook_without_url_returns_false():
    assert _svc_empty().send_webhook("title", "content") is False


def test_enabled_properties_reflect_config():
    s = _svc_empty()
    assert s.email_enabled is False
    assert s.webhook_enabled is False
    s.config['email_enabled'] = True
    s.config['webhook_enabled'] = True
    assert s.email_enabled is True
    assert s.webhook_enabled is True


class _FakeSMTP:
    """记录用法的假 SMTP，不发任何真实邮件。"""
    def __init__(self, calls, kind):
        self.calls = calls
        calls['kind'] = kind
    def starttls(self):
        self.calls['starttls'] = True
    def login(self, *a):
        self.calls['login'] = True
    def send_message(self, *a):
        self.calls['sent'] = True
    def quit(self):
        self.calls['quit'] = True
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _svc_for_email(monkeypatch, port):
    """构造一个填好收发件信息、并把 smtplib 替换为假实现的服务。"""
    import notification_service as ns
    calls = {}
    monkeypatch.setattr(ns.smtplib, 'SMTP_SSL', lambda *a, **k: _FakeSMTP(calls, 'ssl'))
    monkeypatch.setattr(ns.smtplib, 'SMTP', lambda *a, **k: _FakeSMTP(calls, 'plain'))
    s = _svc_empty()
    s.config.update({
        'smtp_server': 'smtp.163.com', 'smtp_port': port,
        'email_from': 'a@163.com', 'email_password': 'x', 'email_to': 'b@qq.com',
    })
    return s, calls


def test_send_custom_email_uses_ssl_on_465(monkeypatch):
    # 465 是隐式 SSL 端口：必须用 SMTP_SSL，且不能再 starttls，否则卡在握手
    s, calls = _svc_for_email(monkeypatch, 465)
    assert s._send_custom_email('subj', '<b>h</b>', 't') is True
    assert calls.get('kind') == 'ssl'
    assert calls.get('starttls') is None


def test_send_custom_email_uses_starttls_on_587(monkeypatch):
    # 587 是 STARTTLS 端口：用 SMTP + starttls
    s, calls = _svc_for_email(monkeypatch, 587)
    assert s._send_custom_email('subj', '<b>h</b>', 't') is True
    assert calls.get('kind') == 'plain'
    assert calls.get('starttls') is True
