"""Sign-in problems must be reported clearly, before the server answers.

"530 Authentication Required" tells the user nothing about what to fix or
where, so the cases we can detect are caught first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qsl_send.config import SmtpConfig  # noqa: E402
from qsl_send.mailer import MailError, Mailer  # noqa: E402


def _cfg(**kw) -> SmtpConfig:
    base = dict(host="smtp.example.com", from_address="me@example.com",
                username="me@example.com", password="secret")
    base.update(kw)
    return SmtpConfig(**base)


class _FakeSMTP:
    """Stands in for smtplib so no connection is attempted."""

    def __init__(self, *a, **k):
        self.logged_in_with = None

    def ehlo(self):
        pass

    def starttls(self, **k):
        pass

    def login(self, user, password):
        self.logged_in_with = (user, password)


def test_a_missing_password_is_reported_before_contacting_the_server(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    with pytest.raises(MailError) as exc:
        Mailer(_cfg(password="")).connect()
    message = str(exc.value)
    assert "App Password" in message          # says what kind of password
    assert "Settings" in message              # and where to put it


def test_the_example_sign_in_address_is_rejected(monkeypatch):
    """A .env copied but never edited leaves myemail@gmail.com in place."""
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    with pytest.raises(MailError) as exc:
        Mailer(_cfg(username="myemail@gmail.com")).connect()
    assert "example value" in str(exc.value)
    assert "Sign in as" in str(exc.value)


def test_a_missing_from_address_is_reported(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    with pytest.raises(MailError) as exc:
        Mailer(_cfg(from_address="")).connect()
    assert "from_address" in str(exc.value)


def test_a_valid_configuration_logs_in(monkeypatch):
    fake = _FakeSMTP()
    monkeypatch.setattr("smtplib.SMTP", lambda *a, **k: fake)
    Mailer(_cfg()).connect()
    assert fake.logged_in_with == ("me@example.com", "secret")


def test_gmail_app_password_spaces_are_stripped(monkeypatch):
    fake = _FakeSMTP()
    monkeypatch.setattr("smtplib.SMTP", lambda *a, **k: fake)
    Mailer(_cfg(host="smtp.gmail.com", password="abcd efgh ijkl mnop")).connect()
    assert fake.logged_in_with[1] == "abcdefghijklmnop"
