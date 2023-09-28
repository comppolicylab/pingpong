import pytest

from .template import format_template, validate_template


def test_validate_template():
    with pytest.raises(ValueError):
        validate_template("Missing $my_var", {})
    validate_template("Missing $my_var", {"my_var": "value"})


def test_format_template():
    assert format_template("Hello $name", {"name": "World"}) == "Hello World"
