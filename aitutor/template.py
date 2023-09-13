import string
from datetime import datetime


def _get_date():
    return datetime.today().strftime("%A, %B %d, %Y")


HARDCODED = {
        "date": _get_date(),
        }


def validate_template(tpl: str, variables: dict[str, str]) -> None:
    """Validate that a template string has all variables.

    Args:
        tpl: The template string to validate.
        variables: A dictionary of variables to substitute into the template.

    Raises:
        ValueError: If the template string has variables that are not defined
    """
    needed = set(string.Template(tpl).get_identifiers())
    supplied = set(HARDCODED.keys()) | set(variables.keys())
    missing = needed - supplied
    if missing:
        raise ValueError(f"Missing variables {missing} in template {tpl}")


def format_template(tpl: str, variables: dict[str, str]) -> str:
    """Format a template string with variables.

    Args:
        tpl: The template string to format.
        variables: A dictionary of variables to substitute into the template.

    Returns:
        The formatted string.
    """
    all_vars = {
            k: v() if callable(v) else v
            for k, v in HARDCODED.items()
            }
    all_vars.update(variables)
    return string.Template(tpl).safe_substitute(all_vars)
