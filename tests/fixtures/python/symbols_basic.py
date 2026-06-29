"""Modul-Docstring (kein Symbol)."""
import os

CONST = 42
counter = 0


def top_level(a, b=1, *args):
    """Funktion auf Modulebene."""
    return a + b


def _hidden():
    pass


class Login:
    """Eine Klasse."""

    timeout = 30

    def validate(self, token):
        """Prueft das Token."""
        return True

    def _private(self):
        pass


class Sub(Login):
    pass
