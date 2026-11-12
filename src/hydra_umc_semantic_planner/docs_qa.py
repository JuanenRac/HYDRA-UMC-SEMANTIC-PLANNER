# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - src/hydra_umc_semantic_planner/docs_qa.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The documentation of an error code, read from HYDRA-UMC-DOCS-QA and attached to a recovery proposal.

`POST /recover` answers with an action and a reason taken from a fixed table. With `docs_qa.enabled` the answer also carries a
`documentation` block: what the project documentation says about the error code (`GET /error?code=` of HYDRA-UMC-DOCS-QA), with its
citation. The block is advice for the person reading the proposal. It never changes the action, the reason or any step, it is never
turned into a step, and when DOCS-QA is down, slow, unknown or answers something odd the block says so (`unavailable`, `not_found`) and
the proposal is exactly what it was without it.

OFF by default (`docs_qa.enabled`). Only the configured address is contacted, it must be loopback unless `docs_qa.allow_remote` is true,
it must carry no credentials, a redirect is never followed, the answer is limited in size, and the text is cleaned of control
characters and cut to `docs_qa.max_answer_chars`. The token of DOCS-QA (when it has one) is read from `docs_qa.token_file`, never from
the configuration itself.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .recovery import CONFIG_ENV

_KNOWN_KEYS = {"enabled", "url", "allow_remote", "timeout_s", "token_file", "max_answer_chars"}
_CODE = re.compile(r"[A-Za-z0-9_]{1,64}")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_RESPONSE_BYTES = 64 * 1024
MAX_MATCHES = 3
MAX_CITATION_CHARS = 300

STATUS_ANSWERED = "answered"
STATUS_NOT_FOUND = "not_found"
STATUS_UNAVAILABLE = "unavailable"


class DocsQaConfigError(ValueError):
    """The `docs_qa` section of the configuration file, or the token file it names, cannot be used."""


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class DocsQaPolicy:
    enabled: bool = False
    url: str = "http://127.0.0.1:8110"
    allow_remote: bool = False
    timeout_s: float = 3.0
    token_file: str = ""
    max_answer_chars: int = 400

    def __post_init__(self) -> None:
        for name in ("enabled", "allow_remote"):
            if not isinstance(getattr(self, name), bool):
                raise DocsQaConfigError(f"docs_qa.{name} must be true or false")
        if not isinstance(self.url, str):
            raise DocsQaConfigError("docs_qa.url must be an http(s) address")
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise DocsQaConfigError("docs_qa.url must be an http(s) address")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise DocsQaConfigError("docs_qa.url must carry no credentials, query or fragment")
        if not self.allow_remote and not _is_loopback(parsed.hostname):
            raise DocsQaConfigError("docs_qa.url is not a loopback address; set docs_qa.allow_remote to true to use it")
        if isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float)) or not 0.1 <= self.timeout_s <= 30:
            raise DocsQaConfigError("docs_qa.timeout_s must be a number from 0.1 to 30")
        if not isinstance(self.token_file, str):
            raise DocsQaConfigError("docs_qa.token_file must be text")
        if isinstance(self.max_answer_chars, bool) or not isinstance(self.max_answer_chars, int) or not 40 <= self.max_answer_chars <= 4000:
            raise DocsQaConfigError("docs_qa.max_answer_chars must be a whole number from 40 to 4000")


def load_docs_qa_policy(path: str | os.PathLike[str] | None = None) -> DocsQaPolicy:
    """The `docs_qa` policy of the file `path`, or of the file named by the planner's configuration variable, or the default (off)."""
    chosen = str(path) if path else os.environ.get(CONFIG_ENV, "")
    if not chosen:
        return DocsQaPolicy()
    try:
        data = json.loads(Path(chosen).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DocsQaConfigError(f"cannot read the configuration file {chosen}: {error}") from error
    if not isinstance(data, dict):
        raise DocsQaConfigError(f"{chosen} must hold a JSON object")
    section = data.get("docs_qa", {})
    if not isinstance(section, dict):
        raise DocsQaConfigError("docs_qa must be a JSON object")
    unknown = sorted(set(section) - _KNOWN_KEYS)
    if unknown:
        raise DocsQaConfigError(f"docs_qa has unknown keys: {', '.join(unknown)}")
    return DocsQaPolicy(**section)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None


def _clean(text: str, limit: int) -> str:
    text = " ".join(_CONTROL.sub(" ", text).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


class DocsQaClient:
    """Asks DOCS-QA what a code means. Every failure becomes a status; nothing is raised to the caller."""

    def __init__(self, policy: DocsQaPolicy, token: str = "") -> None:
        self.policy = policy
        self._token = token

    @classmethod
    def from_policy(cls, policy: DocsQaPolicy) -> "DocsQaClient | None":
        if not policy.enabled:
            return None
        token = ""
        if policy.token_file:
            try:
                token = Path(policy.token_file).read_text(encoding="utf-8").splitlines()[0].strip()
            except (OSError, UnicodeDecodeError, IndexError) as error:
                raise DocsQaConfigError("cannot read the token file of docs_qa") from error
        return cls(policy, token)

    def lookup(self, error_code: str) -> dict[str, Any]:
        """`{"status": ..., "text": ..., "sources": [...]}`; text and sources are empty unless the status is `answered`."""
        if not _CODE.fullmatch(error_code):
            return {"status": STATUS_NOT_FOUND, "text": "", "sources": []}
        url = f"{self.policy.url.rstrip('/')}/error?{urllib.parse.urlencode({'code': error_code})}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.build_opener(_NoRedirect).open(request, timeout=self.policy.timeout_s) as response:  # noqa: S310 - scheme checked in the policy
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return _unavailable()
            data = json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return _unavailable()
        matches = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(matches, list):
            return _unavailable()
        if not matches:
            return {"status": STATUS_NOT_FOUND, "text": "", "sources": []}
        parts: list[str] = []
        sources: list[str] = []
        for item in matches[:MAX_MATCHES]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("text"), str):
                continue
            value = item.get("value")
            label = f"{item['name']} (0x{value:02X})" if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else item["name"]
            parts.append(f"{label}: {item['text']}")
            if isinstance(item.get("citation"), str):
                sources.append(_clean(item["citation"], MAX_CITATION_CHARS))
        if not parts:
            return _unavailable()
        return {"status": STATUS_ANSWERED, "text": _clean(" / ".join(parts), self.policy.max_answer_chars), "sources": sources}


def _unavailable() -> dict[str, Any]:
    return {"status": STATUS_UNAVAILABLE, "text": "", "sources": []}
