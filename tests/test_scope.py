"""I-1.1: scope-Parser/Serializer/Normalizer."""

import pytest

from core.scope import Scope, ScopeType


class TestScopeParse:
    def test_file(self):
        s = Scope.parse("file:src/auth.py")
        assert s.typ == ScopeType.file
        assert s.path == "src/auth.py"
        assert s.symbol is None
        assert s.arity is None
        assert s.repo_id is None

    def test_repo(self):
        s = Scope.parse("repo:")
        assert s.typ == ScopeType.repo
        assert s.path == ""

    def test_module(self):
        s = Scope.parse("module:src/auth")
        assert s.typ == ScopeType.module
        assert s.path == "src/auth"

    def test_symbol_with_arity(self):
        s = Scope.parse("symbol:src/auth/auth.py#Login.validate/2")
        assert s.typ == ScopeType.symbol
        assert s.path == "src/auth/auth.py"
        assert s.symbol == "Login.validate"
        assert s.arity == 2

    def test_symbol_without_arity(self):
        s = Scope.parse("symbol:src/auth/auth.py#Login.validate")
        assert s.symbol == "Login.validate"
        assert s.arity is None

    def test_repo_prefix(self):
        s = Scope.parse("backend::file:src/main.py")
        assert s.repo_id == "backend"
        assert s.typ == ScopeType.file
        assert s.path == "src/main.py"

    def test_repo_prefix_with_symbol_and_arity(self):
        s = Scope.parse("myrepo::symbol:src/auth.py#MyClass.method/1")
        assert s.repo_id == "myrepo"
        assert s.symbol == "MyClass.method"
        assert s.arity == 1


class TestScopeFormat:
    def test_file(self):
        assert (
            Scope(typ=ScopeType.file, path="src/auth.py").format() == "file:src/auth.py"
        )

    def test_repo(self):
        assert Scope(typ=ScopeType.repo, path="").format() == "repo:"

    def test_module(self):
        assert (
            Scope(typ=ScopeType.module, path="src/auth").format() == "module:src/auth"
        )

    def test_symbol_with_arity(self):
        s = Scope(
            typ=ScopeType.symbol,
            path="src/auth/auth.py",
            symbol="Login.validate",
            arity=2,
        )
        assert s.format() == "symbol:src/auth/auth.py#Login.validate/2"

    def test_symbol_without_arity(self):
        s = Scope(
            typ=ScopeType.symbol, path="src/auth/auth.py", symbol="Login.validate"
        )
        assert s.format() == "symbol:src/auth/auth.py#Login.validate"

    def test_with_repo_prefix(self):
        s = Scope(typ=ScopeType.file, path="src/main.py", repo_id="backend")
        assert s.format() == "backend::file:src/main.py"


class TestScopeRoundtrip:
    @pytest.mark.parametrize(
        "raw",
        [
            "repo:",
            "file:src/auth.py",
            "module:src/auth",
            "symbol:src/auth/auth.py#Login.validate/2",
            "symbol:src/auth/auth.py#Login.validate",
            "backend::file:src/main.py",
        ],
    )
    def test_parse_format_roundtrip(self, raw):
        assert Scope.parse(raw).format() == raw


class TestScopeNormalization:
    def test_removes_dot_slash(self):
        assert Scope.parse("file:./src/auth.py").path == "src/auth.py"

    def test_resolves_dotdot(self):
        assert Scope.parse("file:src/../auth.py").path == "auth.py"

    def test_resolves_nested_dotdot(self):
        assert Scope.parse("file:src/auth/../utils.py").path == "src/utils.py"

    def test_backslash_normalized(self):
        assert Scope.parse(r"file:src\auth.py").path == "src/auth.py"

    def test_format_reflects_normalization(self):
        assert Scope.parse("file:./src/auth.py").format() == "file:src/auth.py"

    def test_direct_construction_also_normalizes(self):
        s = Scope(typ=ScopeType.file, path="./src/auth.py")
        assert s.path == "src/auth.py"


class TestScopeValidation:
    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="unknown"):
            Scope.parse("unknown:src/foo.py")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            Scope.parse("")

    def test_no_colon_raises(self):
        with pytest.raises(ValueError):
            Scope.parse("src/foo.py")

    def test_file_empty_path_raises(self):
        with pytest.raises(ValueError, match="path"):
            Scope.parse("file:")

    def test_module_empty_path_raises(self):
        with pytest.raises(ValueError, match="path"):
            Scope.parse("module:")

    def test_symbol_empty_path_raises(self):
        with pytest.raises(ValueError, match="path"):
            Scope.parse("symbol:")

    def test_repo_with_path_raises(self):
        with pytest.raises(ValueError, match="path"):
            Scope.parse("repo:src/foo")

    def test_invalid_arity_raises(self):
        with pytest.raises(ValueError, match="arity"):
            Scope.parse("symbol:src/auth.py#Login.validate/notanumber")

    def test_arity_without_symbol_raises(self):
        with pytest.raises(ValueError, match="arity"):
            Scope(typ=ScopeType.file, path="src/auth.py", arity=2)
