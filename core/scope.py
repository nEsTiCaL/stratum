"""scope-Parser/Serializer/Normalizer (I-1.1).

Scope key: [<repo-id>::]<typ>:<path>[#<symbol>[/<arity>]]
  typ    : {repo, file, module, symbol}
  path   : relative to repo root, no ./ or .. segments
  symbol : dot-nested, overloads via /<arity>
  repo-id: optional; absent means default repo
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_REPO_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class ScopeType(StrEnum):
    repo = "repo"
    file = "file"
    module = "module"
    symbol = "symbol"


@dataclass(frozen=True)
class Scope:
    typ: ScopeType
    path: str
    symbol: str | None = None
    arity: int | None = None
    repo_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_path(self.path))

        if self.typ == ScopeType.repo and self.path:
            raise ValueError(f"'repo' scope must have empty path, got {self.path!r}")
        if self.typ != ScopeType.repo and not self.path:
            raise ValueError(f"'{self.typ}' scope requires a non-empty path")
        if self.arity is not None and self.symbol is None:
            raise ValueError("arity requires symbol to be set")
        if self.repo_id is not None and not _REPO_ID_RE.match(self.repo_id):
            raise ValueError(
                f"invalid repo_id {self.repo_id!r}: must match [A-Za-z0-9_.-]+"
            )

    @classmethod
    def parse(cls, raw: str) -> Scope:
        if not raw:
            raise ValueError("scope string must not be empty")

        repo_id: str | None = None
        rest = raw

        if "::" in raw:
            repo_id, rest = raw.split("::", 1)
            if not repo_id:
                raise ValueError("repo_id must not be empty when '::' is present")

        if ":" not in rest:
            raise ValueError(f"missing ':' separator in scope {raw!r}")

        typ_str, path_and_sym = rest.split(":", 1)

        try:
            typ = ScopeType(typ_str)
        except ValueError:
            valid = [t.value for t in ScopeType]
            raise ValueError(
                f"unknown scope type {typ_str!r}; valid types: {valid}"
            ) from None

        raw_path = path_and_sym
        symbol: str | None = None
        arity: int | None = None

        if "#" in path_and_sym:
            raw_path, sym_part = path_and_sym.split("#", 1)
            if "/" in sym_part:
                sym_name, arity_str = sym_part.rsplit("/", 1)
                if not arity_str.isdigit():
                    raise ValueError(
                        f"arity must be a non-negative integer, "
                        f"got {arity_str!r} in {raw!r}"
                    )
                symbol = sym_name
                arity = int(arity_str)
            else:
                symbol = sym_part

        return cls(typ=typ, path=raw_path, symbol=symbol, arity=arity, repo_id=repo_id)

    def format(self) -> str:
        out = ""
        if self.repo_id is not None:
            out += f"{self.repo_id}::"
        out += f"{self.typ}:{self.path}"
        if self.symbol is not None:
            out += f"#{self.symbol}"
            if self.arity is not None:
                out += f"/{self.arity}"
        return out


def _normalize_path(raw: str) -> str:
    """Forward slashes, no leading ./ and no .. segments."""
    if not raw:
        return raw
    result: list[str] = []
    for part in raw.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if result:
                result.pop()
        else:
            result.append(part)
    return "/".join(result)
