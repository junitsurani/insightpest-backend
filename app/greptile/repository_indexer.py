from __future__ import annotations

import base64
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import quote

import requests

from app.models import db

from .models import GreptileCodeFile, GreptileRepository, GreptileRepositorySnapshot


MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_FILES = 120
MAX_TREE_BYTES = 20 * 1024 * 1024
SOURCE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".ex", ".exs", ".go", ".graphql",
    ".h", ".hpp", ".html", ".java", ".js", ".jsx", ".json", ".kt", ".kts",
    ".md", ".php", ".prisma", ".py", ".rb", ".rs", ".scala", ".sh", ".sql",
    ".swift", ".toml", ".ts", ".tsx", ".vue", ".xml", ".yaml", ".yml",
}
EXCLUDED_PARTS = {
    ".git", ".next", ".venv", "build", "coverage", "dist", "node_modules",
    "target", "vendor", "__pycache__",
}
EXCLUDED_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
    "composer.lock", "Cargo.lock",
}
LANGUAGES = {
    ".c": "C", ".cc": "C++", ".cpp": "C++", ".cs": "C#", ".css": "CSS",
    ".ex": "Elixir", ".exs": "Elixir", ".go": "Go", ".html": "HTML",
    ".java": "Java", ".js": "JavaScript", ".jsx": "JavaScript",
    ".json": "JSON", ".kt": "Kotlin", ".kts": "Kotlin", ".md": "Markdown",
    ".php": "PHP", ".py": "Python", ".rb": "Ruby", ".rs": "Rust",
    ".sh": "Shell", ".sql": "SQL", ".swift": "Swift", ".toml": "TOML",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".vue": "Vue",
    ".yaml": "YAML", ".yml": "YAML",
}


class RepositoryConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteFile:
    path: str
    sha: str | None
    size: int


@dataclass(frozen=True)
class RepositoryTarget:
    provider: str
    owner: str
    name: str


@dataclass(frozen=True)
class RemoteRepository:
    default_branch: str
    commit_sha: str
    files: list[RemoteFile]


def _source_file(path: str, size: int) -> bool:
    candidate = PurePosixPath(path)
    if size > MAX_FILE_BYTES or candidate.name in EXCLUDED_NAMES:
        return False
    if any(part in EXCLUDED_PARTS for part in candidate.parts):
        return False
    if candidate.name.endswith(".min.js") or candidate.name.endswith(".map"):
        return False
    return candidate.suffix.lower() in SOURCE_EXTENSIONS


class RepositoryClient:
    def __init__(self, get: Callable = requests.get):
        self.get = get

    @staticmethod
    def _headers(provider: str) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "Greptile-Demo-Indexer/1.0"}
        token = os.getenv("GITHUB_TOKEN" if provider == "github" else "GITLAB_TOKEN", "").strip()
        if token:
            if provider == "github":
                headers["Authorization"] = f"Bearer {token}"
                headers["X-GitHub-Api-Version"] = "2022-11-28"
            else:
                headers["PRIVATE-TOKEN"] = token
        return headers

    def _request(self, url: str, provider: str, *, params: dict | None = None):
        try:
            response = self.get(
                url,
                headers=self._headers(provider),
                params=params,
                timeout=(4, 15),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RepositoryConnectionError("The repository provider could not be reached.") from exc
        if response.status_code in (401, 403):
            raise RepositoryConnectionError("Repository access was denied. Connect a public repository or configure the provider token.")
        if response.status_code == 404:
            raise RepositoryConnectionError("Repository or branch not found.")
        if response.status_code < 200 or response.status_code >= 300:
            raise RepositoryConnectionError(f"Repository provider returned HTTP {response.status_code}.")
        if len(response.content) > MAX_TREE_BYTES:
            raise RepositoryConnectionError("Repository metadata is too large to index safely.")
        return response

    def describe(self, repository: GreptileRepository) -> RemoteRepository:
        if repository.provider == "github":
            return self._describe_github(repository)
        return self._describe_gitlab(repository)

    def _describe_github(self, repository: GreptileRepository) -> RemoteRepository:
        base = f"https://api.github.com/repos/{quote(repository.owner)}/{quote(repository.name)}"
        metadata = self._request(base, "github").json()
        branch = str(metadata.get("default_branch") or repository.default_branch or "main")
        tree = self._request(f"{base}/git/trees/{quote(branch, safe='')}", "github", params={"recursive": "1"}).json()
        if tree.get("truncated"):
            raise RepositoryConnectionError("This repository tree is too large for the demo indexer.")
        files = [
            RemoteFile(path=item["path"], sha=item.get("sha"), size=int(item.get("size") or 0))
            for item in tree.get("tree", [])
            if item.get("type") == "blob" and isinstance(item.get("path"), str)
            and _source_file(item["path"], int(item.get("size") or 0))
        ][:MAX_FILES]
        commit_sha = str(tree.get("sha") or "")
        if not commit_sha:
            raise RepositoryConnectionError("The repository branch did not return a commit.")
        return RemoteRepository(branch, commit_sha, files)

    def _describe_gitlab(self, repository: GreptileRepository) -> RemoteRepository:
        project_path = quote(f"{repository.owner}/{repository.name}", safe="")
        base = f"https://gitlab.com/api/v4/projects/{project_path}"
        metadata = self._request(base, "gitlab").json()
        branch = str(metadata.get("default_branch") or repository.default_branch or "main")
        branch_data = self._request(f"{base}/repository/branches/{quote(branch, safe='')}", "gitlab").json()
        commit_sha = str((branch_data.get("commit") or {}).get("id") or "")
        files: list[RemoteFile] = []
        for page in range(1, 4):
            rows = self._request(
                f"{base}/repository/tree",
                "gitlab",
                params={"ref": branch, "recursive": "true", "per_page": 100, "page": page},
            ).json()
            if not isinstance(rows, list):
                raise RepositoryConnectionError("GitLab returned an invalid repository tree.")
            for item in rows:
                path = item.get("path")
                if item.get("type") == "blob" and isinstance(path, str) and _source_file(path, 0):
                    files.append(RemoteFile(path=path, sha=item.get("id"), size=0))
                    if len(files) >= MAX_FILES:
                        break
            if len(rows) < 100 or len(files) >= MAX_FILES:
                break
        if not commit_sha:
            raise RepositoryConnectionError("The repository branch did not return a commit.")
        return RemoteRepository(branch, commit_sha, files)

    def fetch_content(self, target: RepositoryTarget, remote: RemoteRepository, item: RemoteFile) -> str | None:
        if target.provider == "github":
            base = f"https://api.github.com/repos/{quote(target.owner)}/{quote(target.name)}"
            payload = self._request(f"{base}/git/blobs/{quote(item.sha or '', safe='')}", "github").json()
            if payload.get("encoding") != "base64":
                return None
            raw = base64.b64decode(str(payload.get("content") or ""), validate=False)
        else:
            project_path = quote(f"{target.owner}/{target.name}", safe="")
            file_path = quote(item.path, safe="")
            response = self._request(
                f"https://gitlab.com/api/v4/projects/{project_path}/repository/files/{file_path}/raw",
                "gitlab",
                params={"ref": remote.commit_sha},
            )
            raw = response.content
        if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None


def index_repository(repository: GreptileRepository, client: RepositoryClient | None = None) -> GreptileRepositorySnapshot:
    client = client or RepositoryClient()
    target = RepositoryTarget(repository.provider, repository.owner, repository.name)
    repository.status = "indexing"
    repository.progress = 5
    snapshot = GreptileRepositorySnapshot(
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        remote_url=f"https://{repository.provider}.com/{repository.owner}/{repository.name}",
        default_branch=repository.default_branch,
        status="indexing",
    )
    db.session.add(snapshot)
    db.session.commit()

    try:
        remote = client.describe(repository)
        if not remote.files:
            raise RepositoryConnectionError("No supported source files were found in the repository.")
        snapshot.default_branch = remote.default_branch
        snapshot.commit_sha = remote.commit_sha
        snapshot.file_count = len(remote.files)
        repository.default_branch = remote.default_branch
        repository.progress = 20
        db.session.commit()

        fetched: list[tuple[RemoteFile, str]] = []
        fetch_errors: list[RepositoryConnectionError] = []
        total_bytes = 0
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_items = {executor.submit(client.fetch_content, target, remote, item): item for item in remote.files}
            for future in as_completed(future_items):
                item = future_items[future]
                try:
                    content = future.result()
                except RepositoryConnectionError as exc:
                    fetch_errors.append(exc)
                    continue
                if content is None:
                    continue
                size = len(content.encode("utf-8"))
                if total_bytes + size > MAX_TOTAL_BYTES:
                    continue
                total_bytes += size
                fetched.append((item, content))

        fetched.sort(key=lambda pair: pair[0].path)
        if not fetched:
            if fetch_errors:
                raise fetch_errors[0]
            raise RepositoryConnectionError("The repository did not contain readable source files within the indexing limits.")
        db.session.add_all([
            GreptileCodeFile(
                workspace_id=repository.workspace_id,
                repository_id=repository.id,
                snapshot_id=snapshot.id,
                path=item.path,
                language=LANGUAGES.get(PurePosixPath(item.path).suffix.lower(), "Text"),
                source_sha=item.sha,
                size_bytes=len(content.encode("utf-8")),
                line_count=len(content.splitlines()),
                content=content,
            )
            for item, content in fetched
        ])
        snapshot.indexed_file_count = len(fetched)
        snapshot.total_bytes = total_bytes
        snapshot.status = "ready"
        repository.status = "ready"
        repository.progress = 100
        from datetime import datetime, timezone
        repository.last_indexed_at = datetime.now(timezone.utc)
        db.session.commit()
        return snapshot
    except Exception as exc:
        db.session.rollback()
        persisted = db.session.get(GreptileRepositorySnapshot, snapshot.id)
        persisted_repository = db.session.get(GreptileRepository, repository.id)
        message = str(exc)[:500] if isinstance(exc, RepositoryConnectionError) else "Repository indexing failed."
        if persisted:
            persisted.status = "failed"
            persisted.error_message = message
        if persisted_repository:
            persisted_repository.status = "failed"
            persisted_repository.progress = 0
        db.session.commit()
        if isinstance(exc, RepositoryConnectionError):
            raise
        raise RepositoryConnectionError(message) from exc
