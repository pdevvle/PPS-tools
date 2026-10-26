"""`pps books` commands."""

from __future__ import annotations

from click.testing import CliRunner

from pps_tools.cli import main


def test_demo_check_schedule_backup_and_password_reset(tmp_path):
    runner = CliRunner()
    data = str(tmp_path / "books")
    r = runner.invoke(main, ["books", "demo", "--data-dir", data, "--password", "demo-pass-123"])
    assert r.exit_code == 0, r.output
    assert "Demo company built" in r.output
    again = runner.invoke(main, ["books", "demo", "--data-dir", data])
    assert again.exit_code != 0 and "already has a company" in again.output

    r = runner.invoke(main, ["books", "check", "--data-dir", data])
    assert r.exit_code == 0, r.output
    assert "transactions balance" in r.output

    r = runner.invoke(main, ["books", "run-scheduled", "--data-dir", data])
    assert r.exit_code == 0, r.output
    assert "reminders" in r.output

    backup = tmp_path / "backup.sqlite"
    r = runner.invoke(main, ["books", "backup", "--data-dir", data, str(backup)])
    assert r.exit_code == 0, r.output
    assert backup.read_bytes()[:15] == b"SQLite format 3"

    r = runner.invoke(main, ["books", "reset-password", "--data-dir", data, "demo@example.com",
                             "--password", "a-new-password"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["books", "reset-password", "--data-dir", data, "nobody@example.com", "--password", "x" * 10])
    assert r.exit_code != 0


def test_setup_creates_the_company(tmp_path):
    runner = CliRunner()
    data = str(tmp_path / "books")
    r = runner.invoke(main, ["books", "setup", "--data-dir", data, "--company", "Test Co", "--email", "me@example.com",
                             "--name", "Me", "--password", "password123"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["books", "setup", "--data-dir", data, "--company", "Again", "--email", "x@example.com",
                             "--name", "X", "--password", "password123"])
    assert r.exit_code != 0 and "already set up" in r.output
