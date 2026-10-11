from PIL import Image
from typer.testing import CliRunner

from conftest import FIXTURES, TARGET
from crowdcheck.cli import app

runner = CliRunner()


def test_missing_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    result = runner.invoke(app, [TARGET])
    assert result.exit_code == 2
    assert "HELIUS_API_KEY is not set" in result.output
    assert "Traceback" not in result.output


def test_bad_mint_is_rejected():
    result = runner.invoke(app, ["not-a-mint"])
    assert result.exit_code == 2 and "does not look like" in result.output


def test_mock_run_writes_card_and_json(tmp_path):
    png, js = tmp_path / "card.png", tmp_path / "r.json"
    result = runner.invoke(app, [TARGET, "--provider", "mock", "--fixtures", str(FIXTURES / "basic"), "--top", "5",
                                 "--png", str(png), "--json", str(js), "--no-cache"])
    assert result.exit_code == 0, result.output
    assert "CROWD REPORT" in result.output and "we read the room" in result.output
    assert Image.open(png).size == (1600, 900)
    assert '"symbol": "ROOM"' in js.read_text()
