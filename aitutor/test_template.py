import pytest

from .config import Config, config
from .template import format_template, validate_template


@pytest.fixture(autouse=True)
def test_config():
    print("FIXTURE")
    config._f.config = Config()
    config._f.reload = 0


def test_validate_template():
    with pytest.raises(ValueError):
        validate_template("Missing $my_var", {})
    validate_template("Missing $my_var", {"my_var": "value"})


def test_format_template():
    assert format_template("Hello $name", {"name": "World"}) == "Hello World"
