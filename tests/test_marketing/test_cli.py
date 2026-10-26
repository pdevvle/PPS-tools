"""`pps marketing` command-line tests (demo data, temporary database)."""

import json

from click.testing import CliRunner

from pps_tools.cli import main


def run(tmp_path, *args):
    env = {"MARKETING_DB_PATH": str(tmp_path / "m.db"), "MARKETING_DEMO": "on"}
    return CliRunner().invoke(main, ["marketing", *args], env=env)


def test_report_json(tmp_path):
    result = run(tmp_path, "report", "--range", "7d", "--format", "json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["demo"] is True
    assert {"google", "facebook", "instagram"} <= set(data["channels"])
    assert data["total"]["spend"] > 0


def test_report_csv_and_table(tmp_path):
    csv_out = run(tmp_path, "report", "--format", "csv")
    assert csv_out.exit_code == 0 and csv_out.output.splitlines()[0].startswith("channel,spend")
    table = run(tmp_path, "report")
    assert table.exit_code == 0 and "(demo data)" in table.output and "Spend" in table.output


def test_status_publish_due_and_rules(tmp_path):
    status = run(tmp_path, "status")
    assert status.exit_code == 0 and "Google Ads" in status.output and "Demo mode" in status.output
    assert "No posts due" in run(tmp_path, "publish-due").output
    assert "No enabled rules" in run(tmp_path, "run-rules", "--dry-run").output
