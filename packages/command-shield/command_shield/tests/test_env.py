"""Tests for clean_env()."""

from __future__ import annotations

import os

from command_shield import clean_env


class TestCleanEnv:
    def test_includes_path(self) -> None:
        assert "PATH" in clean_env()

    def test_excludes_aws_secret(self) -> None:
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret"
        try:
            assert "AWS_SECRET_ACCESS_KEY" not in clean_env()
        finally:
            del os.environ["AWS_SECRET_ACCESS_KEY"]

    def test_excludes_openai_key(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            assert "OPENAI_API_KEY" not in clean_env()
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_returns_plain_dict(self) -> None:
        env = clean_env()
        assert isinstance(env, dict)
        for k, v in env.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
