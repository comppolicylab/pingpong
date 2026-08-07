import pytest

from pingpong.http_utils import content_disposition


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("report.csv", 'attachment; filename="report.csv"'),
        ("annual report.csv", "attachment; filename*=utf-8''annual%20report.csv"),
        ("résumé.csv", "attachment; filename*=utf-8''r%C3%A9sum%C3%A9.csv"),
        (
            "revenue\u202fchart.png",
            "attachment; filename*=utf-8''revenue%E2%80%AFchart.png",
        ),
        ('report"; x=y.csv', "attachment; filename*=utf-8''report%22%3B%20x%3Dy.csv"),
        (
            "report\r\nX-Test: yes.csv",
            "attachment; filename*=utf-8''report%0D%0AX-Test%3A%20yes.csv",
        ),
    ],
)
def test_content_disposition(filename: str, expected: str):
    assert content_disposition("attachment", filename) == expected
