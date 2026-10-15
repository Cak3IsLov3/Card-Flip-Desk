"""Spot settings that were pasted wrong, e.g. EBAY_RUNAME=EBAY_RUNAME=value.

Only the names of the settings are reported, never their values: those can
be secrets.
"""

import os
import re

from django.core.checks import Warning, register

CHECKED_PREFIXES = ("DJANGO_", "EBAY_", "EMAIL_", "TOKEN_", "DATABASE_", "SITE_", "POSTGRES_", "DEFAULT_FROM_")
_NAME_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=")


def env_problems(environ=None) -> list[str]:
    """Messages for settings whose value itself starts with NAME=."""
    environ = os.environ if environ is None else environ
    problems = []
    for key in sorted(environ):
        if not key.startswith(CHECKED_PREFIXES):
            continue
        match = _NAME_ASSIGNMENT.match(environ[key])
        if match:
            problems.append(
                f"{key}: the value starts with '{match.group(1)}='. The line was probably pasted twice; "
                f"keep only one '{key}=' in .env and restart the server."
            )
    return problems


@register()
def check_env_values(app_configs, **kwargs):
    return [Warning(message, id="config.W001") for message in env_problems()]
