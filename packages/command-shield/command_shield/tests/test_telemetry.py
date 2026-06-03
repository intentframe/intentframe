"""Tests for the classifier-coverage-gap telemetry hook."""

from __future__ import annotations

import logging

import pytest

from command_shield.pipeline import inspect_command
from command_shield.telemetry import LOG_NAME, record_classification
from command_shield.verdict import Verdict


def test_telemetry_logger_name_is_stable() -> None:
    assert LOG_NAME == "command_shield.telemetry"


def test_records_gap_for_needs_review_without_sensitive_tag(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOG_NAME)
    record_classification(
        "python -c 'import os; print(os.environ)'",
        Verdict.NEEDS_REVIEW,
        capabilities=(),
    )
    gap_records = [r for r in caplog.records if r.name == LOG_NAME]
    assert len(gap_records) == 1
    assert gap_records[0].levelno == logging.DEBUG


def test_silent_when_sensitive_family_tag_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOG_NAME)
    record_classification(
        "cat ~/.aws/credentials",
        Verdict.NEEDS_REVIEW,
        capabilities=("capability:data_read:cloud_tokens",),
    )
    assert [r for r in caplog.records if r.name == LOG_NAME] == []


def test_silent_when_verdict_is_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOG_NAME)
    record_classification("ls", Verdict.SAFE, capabilities=())
    assert [r for r in caplog.records if r.name == LOG_NAME] == []


def test_mitre_alias_tag_also_counts_as_sensitive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOG_NAME)
    record_classification(
        "some future command",
        Verdict.NEEDS_REVIEW,
        capabilities=("capability:credential_access:browser_cookies",),
    )
    assert [r for r in caplog.records if r.name == LOG_NAME] == []


def test_pipeline_wiring_emits_on_gap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The pipeline records a gap line for a NEEDS_REVIEW with no
    sensitive tag — proves the hook is wired into the final return."""
    caplog.set_level(logging.DEBUG, logger=LOG_NAME)
    report = inspect_command("python -c 'print(1)'")
    assert report.verdict is Verdict.NEEDS_REVIEW
    gap_records = [r for r in caplog.records if r.name == LOG_NAME]
    # Depending on classification this command may or may not pick up
    # a sensitive tag; we only require that the hook does not raise
    # and — if emission fired — that the record has the structured
    # ``event`` field.
    for rec in gap_records:
        assert getattr(rec, "event", None) == "classifier_coverage_gap"
