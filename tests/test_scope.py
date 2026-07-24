import pytest

from core.scope import OutOfScopeError, Scope, ScopeConfig


@pytest.fixture
def scope() -> Scope:
    return Scope(
        ScopeConfig(allowed_networks=["10.0.0.0/24", "127.0.0.1/32"], allowed_hosts=["srv01"])
    )


def test_ip_in_scope(scope: Scope) -> None:
    assert scope.is_ip_in_scope("10.0.0.5")
    assert scope.is_ip_in_scope("127.0.0.1")


def test_ip_out_of_scope(scope: Scope) -> None:
    assert not scope.is_ip_in_scope("8.8.8.8")
    with pytest.raises(OutOfScopeError):
        scope.assert_ip_in_scope("8.8.8.8")


def test_host_scope(scope: Scope) -> None:
    assert scope.is_host_in_scope("srv01")
    assert not scope.is_host_in_scope("unknown-host")


def test_empty_scope_denies_everything() -> None:
    scope = Scope(ScopeConfig())
    assert not scope.is_ip_in_scope("127.0.0.1")
