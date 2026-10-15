"""The local .env loader in settings."""

import os

from config.settings import _load_dotenv


def test_reads_values_skips_empty_comments_and_keeps_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "﻿# comment\nCFD_TEST_A=one\nCFD_TEST_B=\nCFD_TEST_C=\"quoted value\"\nCFD_TEST_D=from-file\nnot a line\n",
        encoding="utf-8",
    )
    for key in ("CFD_TEST_A", "CFD_TEST_B", "CFD_TEST_C"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CFD_TEST_D", "from-environment")
    _load_dotenv(env)
    assert os.environ["CFD_TEST_A"] == "one"
    assert "CFD_TEST_B" not in os.environ  # empty: the default stays
    assert os.environ["CFD_TEST_C"] == "quoted value"
    assert os.environ["CFD_TEST_D"] == "from-environment"  # real environment wins
    for key in ("CFD_TEST_A", "CFD_TEST_C"):
        monkeypatch.delenv(key)


def test_missing_file_is_fine(tmp_path):
    _load_dotenv(tmp_path / "nope.env")
