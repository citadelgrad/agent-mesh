import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess

from google.adk.agents import LlmAgent

# --- Constants ---

_GH_ENV = {
    "GH_TOKEN": os.environ.get("GH_TOKEN", ""),
    "GH_PROMPT_DISABLED": "1",  # critical: prevents gh hanging in headless Vertex containers
    "GH_NO_UPDATE_NOTIFIER": "1",
    "GH_CONFIG_DIR": "/tmp/gh-config",  # nosec B108  # noqa: S108 — gh CLI config in container
    "NO_COLOR": "1",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/root",
}

# ponytail: GitHub body hard limit is 65536 chars; truncate before POST
_GH_PR_BODY_LIMIT = 65_000

_OWNER_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")
_REPO_RE = re.compile(r"^[a-zA-Z0-9._-]{1,100}$")


# --- Private helpers ---


def _validate_repo(repo: str) -> tuple | None:
    if any(c in repo for c in ("?", "#", "\n", "\r", "\x00")):
        return None
    parts = repo.split("/")
    if len(parts) != 2:
        return None
    owner, name = parts
    if not _OWNER_RE.match(owner):
        return None
    if not _REPO_RE.match(name):
        return None
    if name.endswith(".git"):
        return None
    return owner, name


def _validate_file_path(file_path: str) -> bool:
    if not file_path:
        return False
    if file_path.startswith("/"):
        return False
    if "\x00" in file_path or "\n" in file_path:
        return False
    if any(seg == ".." for seg in file_path.split("/")):
        return False
    return True


async def _gh_run(args: list, timeout: float = 15.0) -> subprocess.CompletedProcess:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(  # noqa: S603 — args validated by _validate_repo/_validate_file_path
            args, capture_output=True, text=True, timeout=timeout, env=_GH_ENV, check=False
        ),
    )


# --- FunctionTools ---


async def list_repo_tree(repo: str, path: str = "", ref: str = "HEAD") -> dict[str, object]:
    """List files in a GitHub repository tree.

    Args:
        repo: Repository in owner/name format (e.g. acme/webapp).
        path: Optional path prefix to filter results. Empty string returns all files.
        ref: Git ref (branch, tag, or SHA). Defaults to HEAD.

    Returns:
        dict with 'files' list and optional 'truncated' bool, or 'error_message' on failure.
    """
    parts = _validate_repo(repo)
    if parts is None:
        return {"error_message": f"Invalid repository: {repo!r}"}
    owner, name = parts
    try:
        result = await _gh_run(
            [
                "gh",
                "api",
                f"repos/{owner}/{name}/git/trees/{ref}?recursive=1",
                "--jq",
                ".tree[].path",
            ]
        )
    except subprocess.TimeoutExpired:
        return {"error_message": "gh api timed out listing repo tree"}
    if result.returncode != 0:
        return {"error_message": result.stderr.strip()}
    files = [f for f in result.stdout.splitlines() if f]
    if path:
        files = [f for f in files if f.startswith(path)]
    truncated = len(files) > 500
    return {"files": files[:500], "truncated": truncated}


async def read_repo_file(
    repo: str, file_path: str, ref: str = "HEAD"
) -> dict[str, object]:
    """Read a file from a GitHub repository.

    Args:
        repo: Repository in owner/name format (e.g. acme/webapp).
        file_path: Relative path to the file within the repository (no leading slash).
        ref: Git ref (branch, tag, or SHA). Defaults to HEAD.

    Returns:
        dict with 'content' string, or 'error_message' on failure.
        May include 'too_large': True when the file exceeds GitHub's contents API limit.
    """
    parts = _validate_repo(repo)
    if parts is None:
        return {"error_message": f"Invalid repository: {repo!r}"}
    if not _validate_file_path(file_path):
        return {"error_message": f"Invalid file path: {file_path!r}"}
    owner, name = parts
    try:
        result = await _gh_run(
            ["gh", "api", f"repos/{owner}/{name}/contents/{file_path}?ref={ref}"]
        )
    except subprocess.TimeoutExpired:
        return {"error_message": "gh api timed out reading file"}
    if result.returncode != 0:
        return {"error_message": result.stderr.strip()}
    try:
        data = json.JSONDecoder().decode(result.stdout)
    except json.JSONDecodeError:
        return {"error_message": "Failed to parse GitHub API response"}
    if isinstance(data, list):
        return {"error_message": f"{file_path!r} is a directory, not a file"}
    if data.get("too_large"):
        return {
            "error_message": f"{file_path!r} is too large to fetch via contents API",
            "too_large": True,
        }
    try:
        content = base64.b64decode(data.get("content", "")).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return {"error_message": f"{file_path!r} is not valid UTF-8 (binary file)"}
    return {"content": content}


async def read_pr_diff(repo: str, pr_number: int) -> dict[str, object]:
    """Read the unified diff for a GitHub pull request.

    Args:
        repo: Repository in owner/name format (e.g. acme/webapp).
        pr_number: Pull request number (integer).

    Returns:
        dict with 'diff' string, or 'error_message' on failure.
    """
    parts = _validate_repo(repo)
    if parts is None:
        return {"error_message": f"Invalid repository: {repo!r}"}
    owner, name = parts
    try:
        result = await _gh_run(
            [
                "gh",
                "api",
                f"repos/{owner}/{name}/pulls/{pr_number}",
                "--header",
                "Accept: application/vnd.github.diff",
            ]
        )
    except subprocess.TimeoutExpired:
        return {"error_message": "gh api timed out reading PR diff"}
    if result.returncode != 0:
        return {"error_message": result.stderr.strip()}
    return {"diff": result.stdout}


async def publish_security_findings(
    repo: str, findings_md: str, base_branch: str = "main"
) -> dict[str, object]:
    """Publish a security findings report as a GitHub pull request.

    Creates a deterministic branch name from the findings content hash,
    writes SECURITY_FINDINGS.md to that branch, and opens a PR against base_branch.
    Safe to call multiple times for the same findings (idempotent branch creation).

    Args:
        repo: Repository in owner/name format (e.g. acme/webapp).
        findings_md: Markdown content of the full security findings report.
        base_branch: Target branch for the PR. Defaults to main.

    Returns:
        dict with 'pr_url' on success, or 'error_message' on failure.
        Failures in steps 2-4 include the created branch name for debugging.
    """
    parts = _validate_repo(repo)
    if parts is None:
        return {"error_message": f"Invalid repository: {repo!r}"}
    owner, name = parts
    digest = hashlib.sha256(findings_md.encode()).hexdigest()[:12]
    branch = f"security-review-{digest}"

    # Step 1: GET base branch HEAD SHA
    try:
        result = await _gh_run(
            ["gh", "api", f"repos/{owner}/{name}/git/refs/heads/{base_branch}"]
        )
    except subprocess.TimeoutExpired:
        return {"error_message": "Timed out getting base branch SHA"}
    if result.returncode != 0:
        return {"error_message": f"Failed to get base branch: {result.stderr.strip()}"}
    try:
        _ref = json.JSONDecoder().decode(result.stdout)
        base_sha = _ref["object"]["sha"]
    except (json.JSONDecodeError, KeyError):
        return {"error_message": "Failed to parse base branch ref response"}

    # Step 2: POST git/refs to create branch (422 = already exists → idempotent)
    try:
        result = await _gh_run(
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/{owner}/{name}/git/refs",
                "--field",
                f"ref=refs/heads/{branch}",
                "--field",
                f"sha={base_sha}",
            ]
        )
    except subprocess.TimeoutExpired:
        return {"error_message": f"Timed out creating branch {branch}"}
    branch_existed = result.returncode != 0
    if branch_existed and "422" not in result.stderr and "already exists" not in result.stderr:
        return {"error_message": f"Failed to create branch {branch}: {result.stderr.strip()}"}

    # Step 3: PUT contents/SECURITY_FINDINGS.md on the new branch.
    # If the branch pre-existed, SECURITY_FINDINGS.md may already be there.
    # GitHub Contents PUT requires the existing blob SHA to update a file; omitting it
    # returns 422 "sha wasn't supplied". Fetch it before PUT when the branch existed.
    encoded_content = base64.b64encode(findings_md.encode()).decode()
    put_args = [
        "gh", "api", "--method", "PUT",
        f"repos/{owner}/{name}/contents/SECURITY_FINDINGS.md",
        "--field", "message=chore: add security findings report",
        "--field", f"content={encoded_content}",
        "--field", f"branch={branch}",
    ]
    if branch_existed:
        try:
            file_check = await _gh_run(
                ["gh", "api", f"repos/{owner}/{name}/contents/SECURITY_FINDINGS.md?ref={branch}"]
            )
            if file_check.returncode == 0:
                try:
                    blob_sha = json.JSONDecoder().decode(file_check.stdout).get("sha", "")
                    if blob_sha:
                        put_args += ["--field", f"sha={blob_sha}"]
                except (json.JSONDecodeError, AttributeError):
                    pass
        except subprocess.TimeoutExpired:
            pass  # proceed without SHA — PUT will surface the error if the file exists
    try:
        result = await _gh_run(put_args)
    except subprocess.TimeoutExpired:
        return {"error_message": f"Timed out writing SECURITY_FINDINGS.md on branch {branch}"}
    if result.returncode != 0:
        return {
            "error_message": f"Failed to write findings on branch {branch}: {result.stderr.strip()}"
        }

    # Step 4: gh pr create
    body = findings_md[:_GH_PR_BODY_LIMIT]
    if len(findings_md) > _GH_PR_BODY_LIMIT:
        body += "\n\n---\n_Findings truncated. See SECURITY_FINDINGS.md for the full report._"
    try:
        result = await _gh_run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                f"{owner}/{name}",
                "--head",
                branch,
                "--base",
                base_branch,
                "--title",
                "Security Review Findings",
                "--body",
                body,
            ],
            timeout=30.0,
        )
    except subprocess.TimeoutExpired:
        return {"error_message": f"Timed out creating PR from branch {branch}"}
    if result.returncode != 0:
        return {
            "error_message": f"Failed to create PR from branch {branch}: {result.stderr.strip()}"
        }
    return {"pr_url": result.stdout.strip()}


# --- System prompt ---

_SECURITY_REVIEW_INSTRUCTION = """You are a security specialist agent with deep expertise in the OWASP Top 10 and secure coding practices. You analyze code, diffs, and GitHub repositories for vulnerabilities.

## Input Detection

Detect the input type automatically:
- **Raw code snippet**: Analyze the provided code directly for vulnerabilities.
- **Diff / patch**: Review changed lines for newly introduced vulnerabilities.
- **owner/repo** (e.g., `acme/webapp`): Use `list_repo_tree` to discover files, then `read_repo_file` on priority files in order.
- **PR URL** (e.g., `https://github.com/acme/webapp/pull/42`): Extract owner, repo, and PR number, then call `read_pr_diff`.

## OWASP Top 10 Review Checklist

| ID  | Category                          | What to Look For                                                          |
|-----|-----------------------------------|---------------------------------------------------------------------------|
| A01 | Broken Access Control             | Missing auth checks, IDOR, path traversal, privilege escalation           |
| A02 | Cryptographic Failures            | Weak algorithms, hardcoded secrets, plaintext sensitive data, missing TLS |
| A03 | Injection                         | SQL/command/LDAP/XSS injection, unsanitized user input reaching sinks     |
| A04 | Insecure Design                   | No rate limiting, unsafe defaults, missing threat model                   |
| A05 | Security Misconfiguration         | Debug mode enabled, default creds, verbose errors, open CORS              |
| A06 | Vulnerable Components             | Outdated dependencies, known CVEs, unpatched libraries                    |
| A07 | Auth & Session Failures           | Weak passwords, insecure session tokens, missing MFA, session fixation    |
| A08 | Software Integrity Failures       | Unverified deps, unsigned artifacts, insecure CI/CD pipelines             |
| A09 | Logging & Monitoring Failures     | Missing audit logs, no alerting, sensitive data written to logs           |
| A10 | SSRF                              | Unvalidated server-side URL fetches, internal network exposure            |

## GitHub Repo Review: File Priority Order

When reviewing an owner/repo, examine files in this order:
1. **Entry points**: `main.py`, `app.py`, `index.js`, `server.py`, `wsgi.py`
2. **Auth/authz**: `auth/`, `middleware/`, `decorators.py`, `permissions.py`
3. **Route handlers**: `routes/`, `views/`, `controllers/`, `api/`
4. **Database layer**: `models/`, `migrations/`, `db.py`, `orm.py`
5. **Config / secrets**: `settings.py`, `config.py`, `.env.example`, `docker-compose.yml`
6. **Dependencies**: `requirements.txt`, `package.json`, `Pipfile`, `pyproject.toml`

## Output Format

Always produce a structured findings report:

### Summary Table
| Severity | Count |
|----------|-------|
| Critical | N |
| High     | N |
| Medium   | N |
| Low      | N |
| Info     | N |

### Per Finding

**[SEVERITY] Finding Title**
- **OWASP**: A0X – Category Name
- **File**: `path/to/file.py:LINE` (or `N/A` for config/design issues)
- **Description**: What the vulnerability is and how it could be exploited.
- **Remediation**: Specific fix with a code example where applicable.

## Side Effects

Only call `publish_security_findings` when the user **explicitly** instructs you to publish findings or create a PR. Never call it automatically during analysis.

## Error Handling

When a tool returns an `error_message` field, incorporate it into the report rather than stopping. For example: if `read_repo_file` fails for a priority file, note it as _"Unable to review `path/to/file.py`: {error_message}"_ and continue with remaining files.
"""


# --- Agent and capabilities ---

SECURITY_REVIEW_CAPABILITIES = [
    "security_review",
    "vulnerability_scan",
    "github_review",
    "pr_creation",
]

SECURITY_REVIEW_AGENT = LlmAgent(
    name="SecurityReviewAgent",
    model="gemini-2.5-flash",
    description=(
        "Security specialist that performs OWASP Top 10 vulnerability reviews on code, "
        "diffs, and GitHub repositories. Can read repo files and PR diffs via GitHub CLI "
        "and publish findings as a pull request."
    ),
    instruction=_SECURITY_REVIEW_INSTRUCTION,
    tools=[list_repo_tree, read_repo_file, read_pr_diff, publish_security_findings],
)


async def security_review_health_check() -> bool:
    try:
        result = await _gh_run(["gh", "--version"])
        return result.returncode == 0
    except Exception:
        return False
