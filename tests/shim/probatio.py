"""Test shim: HA 2026.10 'probatio' mapped onto voluptuous (HA 2026.2 test env)."""
from voluptuous import *  # noqa: F401,F403
import voluptuous as _v


def Secret(key):  # noqa: N802
    return key
