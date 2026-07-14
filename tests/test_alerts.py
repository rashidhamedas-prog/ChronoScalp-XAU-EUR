from __future__ import annotations

from unittest.mock import MagicMock, patch

from chronoscalp.orchestration.alerts import AlertConfig, AlertLevel, AlertNotifier


def test_alert_notifier_disabled_by_default():
    notifier = AlertNotifier(cfg=AlertConfig(enabled=False))
    with patch("requests.post") as mock_post:
        notifier.notify("title", "body")
        mock_post.assert_not_called()


def test_alert_notifier_sends_telegram_when_configured():
    notifier = AlertNotifier(
        cfg=AlertConfig(enabled=True, telegram_enabled=True, discord_enabled=False),
        telegram_bot_token="token123",
        telegram_chat_id="chat456",
    )
    assert notifier.is_configured is True

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.notify("Trade opened", "XAUUSD buy", AlertLevel.INFO)

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "token123" in call_kwargs.args[0]
    assert call_kwargs.kwargs["json"]["chat_id"] == "chat456"


def test_alert_notifier_sends_discord_when_configured():
    notifier = AlertNotifier(
        cfg=AlertConfig(enabled=True, telegram_enabled=False, discord_enabled=True),
        discord_webhook_url="https://discord.com/api/webhooks/test",
    )

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.notify("Error", "something failed", AlertLevel.ERROR)

    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == "https://discord.com/api/webhooks/test"
