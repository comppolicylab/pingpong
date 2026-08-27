from pingpong.emails import parse_addresses


def test_parse_addresses_with_commas():
    results = parse_addresses("first@example.com, second@example.com")

    assert [result.email for result in results] == [
        "first@example.com",
        "second@example.com",
    ]
    assert all(result.valid for result in results)


def test_parse_addresses_with_newlines():
    results = parse_addresses("first@example.com\nsecond@example.com")

    assert [result.email for result in results] == [
        "first@example.com",
        "second@example.com",
    ]
    assert all(result.valid for result in results)


def test_parse_addresses_with_blank_lines():
    results = parse_addresses(
        "first@example.com\n\nsecond@example.com\n\nthird@example.com\n\nfourth@example.com"
    )

    assert [result.email for result in results] == [
        "first@example.com",
        "second@example.com",
        "third@example.com",
        "fourth@example.com",
    ]
    assert all(result.valid for result in results)


def test_parse_addresses_with_unicode_line_separators():
    results = parse_addresses(
        "first@example.com\u2028second@example.com\u2029third@example.com"
    )

    assert [result.email for result in results] == [
        "first@example.com",
        "second@example.com",
        "third@example.com",
    ]
    assert all(result.valid for result in results)


def test_parse_addresses_with_crlf_and_names():
    results = parse_addresses(
        "First Person <first@example.com>\r\nSecond Person <second@example.com>"
    )

    assert [(result.name, result.email) for result in results] == [
        ("First Person", "first@example.com"),
        ("Second Person", "second@example.com"),
    ]
    assert all(result.valid for result in results)


def test_parse_addresses_with_standalone_cr():
    results = parse_addresses("first@example.com\rsecond@example.com")

    assert [result.email for result in results] == [
        "first@example.com",
        "second@example.com",
    ]
    assert all(result.valid for result in results)


def test_parse_addresses_with_mixed_separators():
    results = parse_addresses("first@example.com,\nsecond@example.com")

    assert [result.email for result in results] == [
        "first@example.com",
        "second@example.com",
    ]
    assert all(result.valid for result in results)
