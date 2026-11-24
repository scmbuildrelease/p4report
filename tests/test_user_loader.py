import pytest

from p4report.config import DEFAULT_USERLIST
from p4report.user_loader import UserListError, load_users


def write(tmp_path, text, *, bom=False):
    path = tmp_path / "users.txt"
    path.write_bytes(text.encode("utf-8-sig" if bom else "utf-8"))
    return path


def test_valid_file_with_comments_blank_lines_and_whitespace(tmp_path):
    path = write(tmp_path, "# header\n\n  Ann Lee | ann@example.com | ann  \n"
                           "   # indented comment\nBo|bo@example.com|bo\n")
    users = load_users(path)
    assert [(u.name, u.email, u.username) for u in users] == [
        ("Ann Lee", "ann@example.com", "ann"), ("Bo", "bo@example.com", "bo")]


def test_utf8_bom_and_unicode_names(tmp_path):
    users = load_users(write(tmp_path, "Zoë Ñandú|zoe@example.com|zoe\n李雷|li@example.com|lilei\n", bom=True))
    assert [u.name for u in users] == ["Zoë Ñandú", "李雷"]


def test_duplicate_display_names_are_allowed(tmp_path):
    users = load_users(write(tmp_path, "Sam Lee|sam1@example.com|sam1\nSam Lee|sam2@example.com|sam2\n"))
    assert len(users) == 2


@pytest.mark.parametrize(("content", "needle"), [
    ("A|a@example.com|a\nB|b@example.com|A\n", "line 2: duplicate Perforce username 'A'"),
    ("A|a@example.com|a\nB|A@Example.com|b\n", "line 2: duplicate email address"),
    ("bad record\n", "line 1: expected 3 fields"),
    ("# c\nA|a@example.com|a|extra\n", "line 2: expected 3 fields name|email|p4_username, found 4"),
    ("A|a@example.com\n", "found 2"),
    ("|a@example.com|a\n", "line 1: name must not be empty"),
    ("A||a\n", "email must not be empty"),
    ("A|a@example.com|\n", "p4_username must not be empty"),
    ("A|bad|a\n", "invalid email address 'bad'"),
    ("A|a@@example.com|a\n", "invalid email"),
    ("A|not an@example.com|a\n", "invalid email"),
    ("A|a@example|a\n", "invalid email"),
    ("A|a..b@example.com|a\n", "invalid email"),
    ("A|a@example.com|a b\n", "must not contain whitespace"),
    ("", "no employee records"),
    ("# only comments\n\n", "no employee records"),
])
def test_invalid_records_are_rejected_with_location(tmp_path, content, needle):
    path = write(tmp_path, content)
    with pytest.raises(UserListError, match=None) as info:
        load_users(path)
    assert needle in str(info.value)
    assert str(path) in str(info.value)


def test_missing_file_raises_oserror(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_users(tmp_path / "nope.txt")


def test_bundled_demo_directory_is_synthetic():
    users = load_users(DEFAULT_USERLIST)
    assert len(users) == 5
    assert all(u.email.endswith("@example.com") for u in users)
