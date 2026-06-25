import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from agent_mesh.specialists.security_review import (
    _validate_file_path,
    _validate_repo,
    list_repo_tree,
    publish_security_findings,
    read_pr_diff,
    read_repo_file,
    security_review_health_check,
)

PATCH = "agent_mesh.specialists.security_review.subprocess.run"


def _mock_proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# --- _validate_repo ---


def test_validate_repo_valid():
    assert _validate_repo("org/repo") is not None
    assert _validate_repo("org/my.repo") is not None
    assert _validate_repo("org/my-repo_2") is not None


def test_validate_repo_invalid():
    assert _validate_repo("org") is None
    assert _validate_repo("org/repo/extra") is None
    assert _validate_repo("org/repo?x=1") is None
    assert _validate_repo("../etc/passwd") is None
    assert _validate_repo("org/repo.git") is None


# --- _validate_file_path ---


def test_validate_file_path_valid():
    assert _validate_file_path("src/foo.py")
    assert _validate_file_path("dir/sub/file.ts")


def test_validate_file_path_traversal():
    assert not _validate_file_path("../etc/passwd")
    assert not _validate_file_path("/etc/passwd")
    assert not _validate_file_path("a/../b")


# --- list_repo_tree ---


@pytest.mark.asyncio
async def test_list_repo_tree_success():
    with patch(PATCH, return_value=_mock_proc(stdout="src/foo.py\ntests/bar.py\n")):
        result = await list_repo_tree("org/repo")
    assert result["files"] == ["src/foo.py", "tests/bar.py"]
    assert not result.get("truncated")


@pytest.mark.asyncio
async def test_list_repo_tree_path_filter():
    stdout = "src/foo.py\ntests/bar.py\nsrcold/baz.py\n"
    with patch(PATCH, return_value=_mock_proc(stdout=stdout)):
        result = await list_repo_tree("org/repo", path="src/")
    assert result["files"] == ["src/foo.py"]


@pytest.mark.asyncio
async def test_list_repo_tree_500_cap():
    stdout = "\n".join(f"file{i}.py" for i in range(501))
    with patch(PATCH, return_value=_mock_proc(stdout=stdout)):
        result = await list_repo_tree("org/repo")
    assert len(result["files"]) == 500
    assert result["truncated"]


@pytest.mark.asyncio
async def test_list_repo_tree_error():
    with patch(PATCH, return_value=_mock_proc(returncode=1, stderr="not found")):
        result = await list_repo_tree("org/repo")
    assert "error_message" in result
    assert "not found" in result["error_message"]


@pytest.mark.asyncio
async def test_list_repo_tree_invalid_repo():
    with patch(PATCH) as mock_run:
        result = await list_repo_tree("bad-input")
    assert "error_message" in result
    mock_run.assert_not_called()


# --- read_repo_file ---


@pytest.mark.asyncio
async def test_read_repo_file_success():
    content = base64.b64encode(b"hello world").decode()
    payload = json.dumps({"encoding": "base64", "content": content})
    with patch(PATCH, return_value=_mock_proc(stdout=payload)):
        result = await read_repo_file("org/repo", "src/foo.py")
    assert result["content"] == "hello world"


@pytest.mark.asyncio
async def test_read_repo_file_directory():
    with patch(PATCH, return_value=_mock_proc(stdout="[]")):
        result = await read_repo_file("org/repo", "src")
    assert "error_message" in result
    assert "directory" in result["error_message"]


@pytest.mark.asyncio
async def test_read_repo_file_too_large():
    payload = json.dumps({"too_large": True})
    with patch(PATCH, return_value=_mock_proc(stdout=payload)):
        result = await read_repo_file("org/repo", "src/big.py")
    assert "error_message" in result
    assert "too large" in result["error_message"]


@pytest.mark.asyncio
async def test_read_repo_file_binary():
    payload = json.dumps({"encoding": "base64", "content": "!!!invalid!!!"})
    with patch(PATCH, return_value=_mock_proc(stdout=payload)):
        result = await read_repo_file("org/repo", "src/bin.so")
    assert "error_message" in result


@pytest.mark.asyncio
async def test_read_repo_file_path_traversal():
    with patch(PATCH) as mock_run:
        result = await read_repo_file("org/repo", "../secrets")
    assert "error_message" in result
    mock_run.assert_not_called()


# --- read_pr_diff ---


@pytest.mark.asyncio
async def test_read_pr_diff_success():
    diff_text = "diff --git a/foo.py b/foo.py\n+added line\n"
    with patch(PATCH, return_value=_mock_proc(stdout=diff_text)):
        result = await read_pr_diff("org/repo", 42)
    assert "diff" in result
    assert result["diff"] == diff_text


# --- publish_security_findings ---


@pytest.mark.asyncio
async def test_publish_success():
    sha_resp = json.dumps({"object": {"sha": "deadbeef123"}})
    mocks = [
        _mock_proc(stdout=sha_resp),
        _mock_proc(returncode=0),
        _mock_proc(returncode=0),
        _mock_proc(returncode=0, stdout="https://github.com/org/repo/pull/1"),
    ]
    with patch(PATCH, side_effect=mocks) as mock_run:
        result = await publish_security_findings("org/repo", "# Findings\n- issue")
    assert "pr_url" in result
    assert result["pr_url"] == "https://github.com/org/repo/pull/1"
    assert mock_run.call_count == 4


@pytest.mark.asyncio
async def test_publish_branch_already_exists():
    sha_resp = json.dumps({"object": {"sha": "deadbeef123"}})
    file_check_resp = json.dumps({"sha": "existingblobsha123", "content": ""})
    mocks = [
        _mock_proc(stdout=sha_resp),                                              # step 1: base SHA
        _mock_proc(returncode=1, stderr="422 already exists"),                    # step 2: branch exists
        _mock_proc(stdout=file_check_resp),                                       # step 3a: GET file SHA
        _mock_proc(returncode=0),                                                 # step 3: PUT with sha
        _mock_proc(returncode=0, stdout="https://github.com/org/repo/pull/1"),    # step 4: PR
    ]
    with patch(PATCH, side_effect=mocks) as mock_run:
        result = await publish_security_findings("org/repo", "# Findings\n- issue")
    assert "pr_url" in result
    assert mock_run.call_count == 5
    # Verify the PUT call included the blob sha from the file check
    put_call = mock_run.call_args_list[3]
    assert "sha=existingblobsha123" in " ".join(put_call.args[0])


@pytest.mark.asyncio
async def test_publish_pr_failure():
    sha_resp = json.dumps({"object": {"sha": "deadbeef123"}})
    mocks = [
        _mock_proc(stdout=sha_resp),
        _mock_proc(returncode=0),
        _mock_proc(returncode=0),
        _mock_proc(returncode=1, stderr="unprocessable entity"),
    ]
    with patch(PATCH, side_effect=mocks):
        result = await publish_security_findings("org/repo", "# Findings\n- issue")
    assert "error_message" in result
    assert "security-review-" in result["error_message"]


@pytest.mark.asyncio
async def test_publish_body_truncation():
    findings_md = "x" * 70_000
    sha_resp = json.dumps({"object": {"sha": "deadbeef123"}})
    mocks = [
        _mock_proc(stdout=sha_resp),
        _mock_proc(returncode=0),
        _mock_proc(returncode=0),
        _mock_proc(returncode=0, stdout="https://github.com/org/repo/pull/1"),
    ]
    with patch(PATCH, side_effect=mocks) as mock_run:
        await publish_security_findings("org/repo", findings_md)
    create_call = next(c for c in mock_run.call_args_list if "--body" in c.args[0])
    args_list = create_call.args[0]
    body_arg = args_list[args_list.index("--body") + 1]
    assert len(body_arg) < len(findings_md)
    assert "truncated" in body_arg


@pytest.mark.asyncio
async def test_publish_invalid_repo():
    with patch(PATCH) as mock_run:
        result = await publish_security_findings("bad", "# findings")
    assert "error_message" in result
    mock_run.assert_not_called()


# --- health check ---


@pytest.mark.asyncio
async def test_health_check_success():
    with patch(PATCH, return_value=_mock_proc(returncode=0, stdout="gh version 2.69.0")):
        assert await security_review_health_check()


@pytest.mark.asyncio
async def test_health_check_failure():
    with patch(PATCH, side_effect=FileNotFoundError):
        assert not await security_review_health_check()
