from lingji_agent.execution.coding_supervisor import (
    detect_needs_input,
    git_url_allowed,
    normalize_git_url,
)


def test_normalize_git_url():
    assert normalize_git_url("https://github.com/AUrlius/lingji-zero.git/") == (
        "https://github.com/aurlius/lingji-zero"
    )
    assert normalize_git_url("") == ""


def test_git_url_allowed():
    allow = ["https://github.com/AUrlius/lingji-zero"]
    assert git_url_allowed("https://github.com/AUrlius/lingji-zero.git", allow)
    assert not git_url_allowed("https://evil.example/r", allow)
    assert not git_url_allowed("https://github.com/AUrlius/lingji-zero", [])


def test_detect_needs_input():
    assert detect_needs_input("Please choose A or B")
    assert not detect_needs_input("compiled successfully")
