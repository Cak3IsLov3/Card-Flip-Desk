"""Warnings for settings that were pasted twice."""

import os

from django.urls import reverse

from config.env_checks import check_env_values, env_problems


def test_value_starting_with_a_name_is_reported_without_the_value():
    problems = env_problems({
        "EBAY_RUNAME": "EBAY_RUNAME=Some-RuName",
        "EBAY_CLIENT_SECRET": "EBAY_CLIENT_SECRET=PRD-very-secret",
        "EBAY_CLIENT_ID": "Martinus-CardFlip-PRD-1",
        "TOKEN_ENCRYPTION_KEYS": "abc123==",  # base64 padding is fine
        "PATH": "PATH=C:/x",  # not one of ours
    })
    assert len(problems) == 2
    assert problems[0].startswith("EBAY_CLIENT_SECRET: the value starts with 'EBAY_CLIENT_SECRET='")
    assert problems[1].startswith("EBAY_RUNAME:")
    assert "very-secret" not in " ".join(problems)
    assert "Some-RuName" not in " ".join(problems)


def test_export_prefix_is_also_caught():
    assert env_problems({"EBAY_RUNAME": "export EBAY_RUNAME=x"})


def test_system_check_warns(monkeypatch):
    monkeypatch.setenv("EBAY_RUNAME", "EBAY_RUNAME=x")
    assert [m.id for m in check_env_values(None)] == ["config.W001"]


def test_ebay_page_shows_the_warning(monkeypatch, user, client_for):
    monkeypatch.setenv("EBAY_RUNAME", "EBAY_RUNAME=x")
    html = client_for(user).get(reverse("ebay:connection")).content.decode()
    assert "Check your settings" in html
    assert "EBAY_RUNAME: the value starts with" in html


def test_no_warning_when_settings_are_fine(monkeypatch, user, client_for):
    monkeypatch.setenv("EBAY_RUNAME", "Some-RuName")
    for key in [k for k, v in os.environ.items() if env_problems({k: v})]:
        monkeypatch.delenv(key)
    assert "Check your settings" not in client_for(user).get(reverse("ebay:connection")).content.decode()
