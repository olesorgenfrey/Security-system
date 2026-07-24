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
