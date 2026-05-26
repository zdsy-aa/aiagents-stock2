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
