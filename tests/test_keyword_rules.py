from pathlib import Path

import pytest

from core.detection.keyword_rules import KeywordRule, load_rules


def test_curated_rules_load_from_disk() -> None:
    rules = load_rules()
    rule_ids = {r.id for r in rules}
    assert "new_admin_account" in rule_ids
    assert "suspicious_reverse_shell" in rule_ids


def test_keyword_rule_matches_any_group() -> None:
    rule = KeywordRule(
        id="test",
        title="Test",
        description="",
        mitre=None,
        severity=50,
        match_any=[["usermod", "sudo"], ["useradd", "wheel"]],
    )
    assert rule.matches("usermod -aG sudo bob")
    assert rule.matches("useradd -G wheel alice")
    assert not rule.matches("usermod -aG docker bob")


def test_keyword_rule_no_match() -> None:
    rule = KeywordRule(
        id="test", title="Test", description="", mitre=None, severity=50, match_any=[["nc", "-e"]]
    )
    assert not rule.matches("ls -la /home")


def test_rule_loader_rejects_empty_match_group(tmp_path: Path) -> None:
    (tmp_path / "invalid.yml").write_text(
        "id: invalid\ntitle: Invalid\nseverity: 50\nmatch_any:\n  - []\n"
    )
    with pytest.raises(ValueError, match="leere match_any"):
        load_rules(tmp_path)


def test_rule_loader_rejects_out_of_range_severity(tmp_path: Path) -> None:
    (tmp_path / "invalid.yml").write_text(
        "id: invalid\ntitle: Invalid\nseverity: 101\nmatch_any:\n  - [foo]\n"
    )
    with pytest.raises(ValueError, match="Severity"):
        load_rules(tmp_path)
