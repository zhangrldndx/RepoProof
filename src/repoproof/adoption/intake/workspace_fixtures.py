"""Human-confirmable fixture blueprints for workspace-bundle Product tasks.

An LLM may propose scenario metadata, but only a frozen task-owned builder
creates bytes.  Confirmations bind the exact builder and generated file tree;
candidate regeneration never silently drops an already confirmed fixture.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repoproof.domain.models import validate_workspace_relative_path
from repoproof.execution.core_execution import atomic_write_json
from repoproof.execution.offline_sandbox import (
    OfflineSandboxUnavailable,
    offline_sandbox_argv,
    sanitised_subprocess_env,
)
from repoproof.execution.workspace_bundle import (
    InputPathIdentityV1,
    WorkspaceBundleError,
    snapshot_admitted_path,
)

_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")
_RUNNER = r'''import importlib.util
import json
import sys
from pathlib import Path

source, blueprint_json, output_path = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("repoproof_task_fixture_builder", source)
if spec is None or spec.loader is None:
    raise RuntimeError("fixture builder cannot be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
build = getattr(module, "build", None)
if not callable(build):
    raise TypeError("fixture builder must export build(blueprint, output_path)")
blueprint = json.loads(blueprint_json)
try:
    build(blueprint, Path(output_path))
except Exception as exc:
    # Mirror the reference runner: the builder is the model's own draft, so its
    # message and in-source frames are repair evidence, not answer keys
    # (incident-builder-failure-diagnostics-opaque-*).  Raw tracebacks and
    # parameters still never leave the child.
    import traceback
    frames = []
    innermost = None
    for frame in traceback.extract_tb(exc.__traceback__):
        innermost = {"file": Path(frame.filename).name, "line": int(frame.lineno or 0), "name": frame.name}
        if frame.filename == source:
            frames.append({"line": int(frame.lineno or 0), "name": frame.name})
    print(
        "REPOPROOF_FIXTURE_BUILDER_FAILURE="
        + json.dumps(
            {
                "exception_type": type(exc).__name__,
                "exception_message": " ".join(str(exc).split())[:240],
                "builder_frames": frames[-6:],
                "innermost_frame": innermost,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    raise SystemExit(90) from None
'''

_BUILDER_FAILURE_MARKER = "REPOPROOF_FIXTURE_BUILDER_FAILURE="
_EXCEPTION_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


_PUBLIC_BUILDER_FRAME_NAME_RE = re.compile(r"[A-Za-z_<][A-Za-z0-9_>]{0,79}")
_PUBLIC_BUILDER_FILE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,120}")


def _builder_failure_public_class(stderr: str, *, private_root: str = "") -> str:
    """One public line: ``Type: message @ fixture_builder.py:line fn (innermost ...)``.

    The builder is the model's own draft; its message and in-source frames are
    repair evidence, not answer keys.  Everything is bounded, the private temp
    root is masked, and a missing or malformed marker still projects to "".
    """

    for line in reversed(stderr.splitlines()):
        line = line.strip()
        if not line.startswith(_BUILDER_FAILURE_MARKER):
            continue
        try:
            payload = json.loads(line[len(_BUILDER_FAILURE_MARKER):]) or {}
        except ValueError:
            return ""
        name = str(payload.get("exception_type") or "")
        if _EXCEPTION_CLASS_RE.fullmatch(name) is None:
            return ""
        message = " ".join(str(payload.get("exception_message") or "").split())
        if private_root:
            message = message.replace(private_root, "<builder-root>")
        message = message[:240]
        frames: list[str] = []
        for frame in reversed(list(payload.get("builder_frames") or [])[-6:]):
            if not isinstance(frame, dict):
                continue
            frame_name = str(frame.get("name") or "")
            frame_line = frame.get("line")
            if (
                not isinstance(frame_line, int)
                or frame_line <= 0
                or _PUBLIC_BUILDER_FRAME_NAME_RE.fullmatch(frame_name) is None
            ):
                continue
            frames.append(f"fixture_builder.py:{frame_line} {frame_name}")
        suffix = ""
        innermost = payload.get("innermost_frame")
        if isinstance(innermost, dict):
            file_name = str(innermost.get("file") or "")
            inner_name = str(innermost.get("name") or "")
            inner_line = innermost.get("line")
            if (
                file_name != "fixture_builder.py"
                and isinstance(inner_line, int)
                and inner_line > 0
                and _PUBLIC_BUILDER_FILE_NAME_RE.fullmatch(file_name) is not None
                and _PUBLIC_BUILDER_FRAME_NAME_RE.fullmatch(inner_name) is not None
            ):
                suffix = f" (innermost {file_name}:{inner_line} {inner_name})"
        head = f"{name}: {message}" if message else name
        return head + (" @ " + "; ".join(frames) if frames else "") + suffix
    return ""


class FixtureBlueprintV1(BaseModel):
    """Natural scenario metadata; never an LLM-supplied binary payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    scenario: str = Field(min_length=1, max_length=1200)
    input_kind: Literal["file", "directory"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    # An open-API scenario whose identifiers (repositories, accounts, ids,
    # place codes) are real, public and known to exist today.  Fixture
    # identifiers are otherwise invented by design, so the rehearsal's live
    # probe can only tell "endpoint gone" from "resource never existed" by
    # asking the real host about a real resource
    # (incident-live-probe-misreads-fictional-resource-*).
    live_anchor: bool = False

    @field_validator("blueprint_id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if value[0] not in "abcdefghijklmnopqrstuvwxyz0123456789" or any(
            char not in _ID_CHARS for char in value
        ):
            raise ValueError("blueprint_id must be a lowercase safe slug")
        return value

    @field_validator("parameters")
    @classmethod
    def _json_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 32_000:
            raise ValueError("fixture blueprint parameters are too large")
        return value


class InputFixtureCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    blueprint: FixtureBlueprintV1
    builder_id: str = Field(min_length=1, max_length=128)
    builder_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_path: str
    fixture_identity: InputPathIdentityV1
    confirmed: bool = False

    @model_validator(mode="after")
    def _kind_matches_blueprint(self) -> InputFixtureCandidateV1:
        if self.fixture_identity.kind != self.blueprint.input_kind:
            raise ValueError("fixture builder output kind mismatches blueprint")
        return self


class InputFixtureBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    generation_id: str = Field(min_length=1, max_length=128)
    candidates: tuple[InputFixtureCandidateV1, ...] = Field(
        min_length=1, max_length=12
    )

    @model_validator(mode="after")
    def _candidate_ids_are_unique(self) -> InputFixtureBundleV1:
        ids = [item.blueprint.blueprint_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("fixture blueprint ids must be unique")
        input_identities = [
            (item.fixture_identity.kind, item.fixture_identity.sha256)
            for item in self.candidates
        ]
        if len(input_identities) != len(set(input_identities)):
            raise ValueError("fixture inputs must be unique")
        return self


class FixtureBuilderError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


_PATH_VALUE_FIELDS = frozenset(
    {"file", "files", "filename", "filenames", "path", "paths", "relative_path"}
)


_REQUEST_ROW_KEYS = frozenset({"path", "paths", "query"})


def _parameter_field_name(parent: dict, key: object) -> str:
    """A ``path`` beside a ``host`` is a request key, not a fixture file path.

    Recorded open-API responses are parameters too; their URL paths begin with
    a slash and must stay exactly what the producer will ask for.  The
    portable-path projection once rewrote them into fixture-<hash> aliases and
    the recording could never match a request
    (incident-blueprint-sanitiser-mangles-request-path-*).
    """

    name = str(key).lower()
    if "host" in parent and name in _REQUEST_ROW_KEYS:
        return "request_key"
    return name


def _portable_path_map(seed_values: tuple[object, ...]) -> bool:
    dictionaries = [value for value in seed_values if isinstance(value, dict)]
    if not dictionaries:
        return False
    keys = [str(key) for value in dictionaries for key in value]
    return bool(keys) and any("/" in key or "." in Path(key).name for key in keys)


def _portable_fixture_path_alias(value: str) -> str:
    """Return a stable portable alias without preserving unsafe path segments."""

    suffix = Path(value.replace("\\", "/")).suffix
    if not (
        suffix.startswith(".")
        and 1 < len(suffix) <= 12
        and suffix[1:].isascii()
        and suffix[1:].isalnum()
    ):
        suffix = ""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"fixture-{digest}{suffix.lower()}"


def _project_parameter_paths(
    value: object,
    *,
    seed_values: tuple[object, ...],
    field_name: str = "",
) -> object:
    if isinstance(value, dict):
        path_map = _portable_path_map(seed_values)
        seed_dicts = [item for item in seed_values if isinstance(item, dict)]
        projected: dict[str, object] = {}
        for key, child in value.items():
            projected_key = str(key)
            if path_map:
                try:
                    validate_workspace_relative_path(projected_key)
                except ValueError:
                    projected_key = _portable_fixture_path_alias(projected_key)
            if projected_key in projected:
                raise FixtureBuilderError("FIXTURE_BLUEPRINT_PATH_ALIAS_COLLISION")
            child_seeds = tuple(item[key] for item in seed_dicts if key in item)
            projected[projected_key] = _project_parameter_paths(
                child,
                seed_values=child_seeds,
                field_name=_parameter_field_name(value, key),
            )
        return projected
    if isinstance(value, list):
        seed_items = tuple(
            child
            for item in seed_values
            if isinstance(item, list)
            for child in item
        )
        return [
            _project_parameter_paths(
                child,
                seed_values=seed_items,
                field_name=field_name,
            )
            for child in value
        ]
    if isinstance(value, str) and field_name in _PATH_VALUE_FIELDS:
        seed_strings = tuple(item for item in seed_values if isinstance(item, str))
        if seed_strings:
            try:
                validate_workspace_relative_path(value)
            except ValueError:
                return _portable_fixture_path_alias(value)
    return value


def project_fixture_blueprint_portable_paths(
    blueprint: FixtureBlueprintV1,
    *,
    seeds: tuple[FixtureBlueprintV1, ...],
) -> FixtureBlueprintV1:
    """Project only path-bearing model parameters to deterministic safe aliases.

    Fixture paths are transport representation, not user-authored semantic truth.
    Core therefore owns this projection instead of spending another model call on
    a mechanical safety correction. Scenario prose and file contents remain
    byte-for-byte unchanged and the projected blueprint is validated normally.
    """

    parameters = _project_parameter_paths(
        blueprint.parameters,
        seed_values=tuple(seed.parameters for seed in seeds),
    )
    assert isinstance(parameters, dict)
    projected = blueprint.model_copy(update={"parameters": parameters})
    validate_fixture_blueprint_portable_paths(projected, seeds=(projected,))
    return projected


def _validate_parameter_paths(
    value: object,
    *,
    seed_values: tuple[object, ...],
    field_name: str = "",
) -> None:
    if isinstance(value, dict):
        if _portable_path_map(seed_values):
            for key in value:
                try:
                    validate_workspace_relative_path(str(key))
                except ValueError as exc:
                    raise FixtureBuilderError(
                        "FIXTURE_BLUEPRINT_NONPORTABLE_PATH"
                    ) from exc
        seed_dicts = [item for item in seed_values if isinstance(item, dict)]
        for key, child in value.items():
            child_seeds = tuple(item[key] for item in seed_dicts if key in item)
            _validate_parameter_paths(
                child,
                seed_values=child_seeds,
                field_name=_parameter_field_name(value, key),
            )
        return
    if isinstance(value, list):
        seed_items = tuple(
            child
            for item in seed_values
            if isinstance(item, list)
            for child in item
        )
        for child in value:
            _validate_parameter_paths(
                child,
                seed_values=seed_items,
                field_name=field_name,
            )
        return
    if isinstance(value, str) and field_name in _PATH_VALUE_FIELDS:
        seed_strings = tuple(item for item in seed_values if isinstance(item, str))
        if not seed_strings:
            return
        try:
            for seed in seed_strings:
                validate_workspace_relative_path(seed)
            validate_workspace_relative_path(value)
        except ValueError as exc:
            raise FixtureBuilderError(
                "FIXTURE_BLUEPRINT_NONPORTABLE_PATH"
            ) from exc


def validate_fixture_blueprint_portable_paths(
    blueprint: FixtureBlueprintV1,
    *,
    seeds: tuple[FixtureBlueprintV1, ...],
) -> None:
    """Reject model parameters that would create non-portable fixture paths.

    Path-bearing parameter positions are inferred from the frozen seed shape;
    arbitrary Unicode scenario text and file contents remain valid.  This keeps
    task-specific builders expressive without letting a model-proposed filename
    reach the filesystem before the common workspace policy is applied.
    """

    _validate_parameter_paths(
        blueprint.parameters,
        seed_values=tuple(seed.parameters for seed in seeds),
    )


def assert_distinct_fixture_inputs(
    candidates: list[InputFixtureCandidateV1]
    | tuple[InputFixtureCandidateV1, ...],
) -> None:
    """Reject multiple scenarios that bind to the same exact input bytes.

    Blueprint labels are suggestions, not coverage evidence.  Two distinct
    labels backed by the same admitted input cannot count as two representative
    fixtures, regardless of whether their expected artifacts are also equal.
    """

    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        identity = (
            candidate.fixture_identity.kind,
            candidate.fixture_identity.sha256,
        )
        if identity in seen:
            raise FixtureBuilderError("FIXTURE_INPUT_DUPLICATE")
        seen.add(identity)


def _read_builder_source(path: Path) -> bytes:
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FixtureBuilderError("FIXTURE_BUILDER_UNREADABLE") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise FixtureBuilderError("FIXTURE_BUILDER_UNSAFE")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise FixtureBuilderError("FIXTURE_BUILDER_CHANGED_DURING_READ")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def build_fixture_candidate(
    *,
    blueprint: FixtureBlueprintV1,
    builder_id: str,
    builder_source: Path,
    fixture_root: Path,
    python_exe: str,
    isolation_required: bool = True,
    timeout_s: int = 60,
) -> InputFixtureCandidateV1:
    """Execute a frozen builder and publish one exact, inspectable fixture."""

    if not python_exe:
        raise FixtureBuilderError("FIXTURE_BUILDER_PYTHON_MISSING")
    source_bytes = _read_builder_source(Path(builder_source))
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    fixture_root = Path(fixture_root)
    fixture_root.mkdir(parents=True, exist_ok=True)
    if fixture_root.is_symlink():
        raise FixtureBuilderError("FIXTURE_ROOT_UNSAFE")
    destination = fixture_root / blueprint.blueprint_id
    if destination.exists() or destination.is_symlink():
        raise FixtureBuilderError("FIXTURE_DESTINATION_EXISTS")

    with tempfile.TemporaryDirectory(prefix="rp-fixture-builder-") as temp:
        root = Path(temp)
        source_snapshot = root / "fixture_builder.py"
        source_snapshot.write_bytes(source_bytes)
        source_snapshot.chmod(0o400)
        runner = root / "runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        runner.chmod(0o400)
        generated = root / "generated"
        argv = [
            python_exe,
            str(runner),
            str(source_snapshot),
            json.dumps(blueprint.model_dump(mode="json"), ensure_ascii=False),
            str(generated),
        ]
        if isolation_required:
            try:
                argv = offline_sandbox_argv(argv, root)
            except OfflineSandboxUnavailable as exc:
                raise FixtureBuilderError("FIXTURE_BUILDER_ISOLATION_UNAVAILABLE") from exc
        try:
            process = subprocess.run(  # noqa: S603 - frozen argv, no shell
                argv,
                cwd=root,
                env=sanitised_subprocess_env(root, [str(root)]),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FixtureBuilderError("FIXTURE_BUILDER_EXECUTION_FAILED") from exc
        if process.returncode != 0:
            raise FixtureBuilderError(
                "FIXTURE_BUILDER_FAILED",
                _builder_failure_public_class(process.stderr or "", private_root=str(root)),
            )
        try:
            identity = snapshot_admitted_path(generated, destination)
        except WorkspaceBundleError as exc:
            raise FixtureBuilderError(exc.code, exc.detail) from exc
        if identity.kind != blueprint.input_kind:
            # The builder's own defect, named for the builder repair: a
            # pydantic message here once became the public code and ended a
            # journey with no repair route (incident-public-code-is-exception-text-*).
            raise FixtureBuilderError(
                "FIXTURE_BUILDER_OUTPUT_KIND_MISMATCH",
                f"blueprint {blueprint.blueprint_id!r} declares input_kind={blueprint.input_kind!r} "
                f"but the builder wrote a {identity.kind}; write one file for 'file' blueprints and "
                "a directory for 'directory' blueprints",
            )

    return InputFixtureCandidateV1(
        blueprint=blueprint,
        builder_id=builder_id,
        builder_source_sha256=source_sha,
        fixture_path=str(destination.resolve()),
        fixture_identity=identity,
    )


def confirm_fixture_candidate(
    candidate: InputFixtureCandidateV1,
) -> InputFixtureCandidateV1:
    """Human gate: bind confirmation to the already generated exact bytes."""

    return candidate.model_copy(update={"confirmed": True})


def merge_regenerated_fixture_bundle(
    previous: InputFixtureBundleV1 | None,
    generated: InputFixtureBundleV1,
) -> InputFixtureBundleV1:
    """Keep confirmed exact fixtures while replacing unconfirmed suggestions."""

    if previous is None:
        return generated
    current = {item.blueprint.blueprint_id: item for item in generated.candidates}
    retained: list[InputFixtureCandidateV1] = []
    for old in previous.candidates:
        if not old.confirmed:
            continue
        replacement = current.get(old.blueprint.blueprint_id)
        if replacement is not None and (
            replacement.builder_source_sha256 == old.builder_source_sha256
            and replacement.fixture_identity == old.fixture_identity
        ):
            current[old.blueprint.blueprint_id] = replacement.model_copy(
                update={"confirmed": True}
            )
        else:
            retained.append(old)
            # A regenerated suggestion may reuse the same human-facing id with
            # different bytes.  The confirmed exact fixture wins; keeping both
            # would either erase the confirmation or create an invalid duplicate.
            current.pop(old.blueprint.blueprint_id, None)
    seen_inputs = {
        (item.fixture_identity.kind, item.fixture_identity.sha256)
        for item in retained
    }
    for item in generated.candidates:
        candidate = current.get(item.blueprint.blueprint_id)
        if candidate is None:
            continue
        identity = (
            candidate.fixture_identity.kind,
            candidate.fixture_identity.sha256,
        )
        if identity in seen_inputs:
            continue
        retained.append(candidate)
        seen_inputs.add(identity)
    return InputFixtureBundleV1(
        generation_id=generated.generation_id,
        candidates=tuple(retained),
    )


def write_fixture_bundle(path: Path, bundle: InputFixtureBundleV1) -> Path:
    """Atomically update editable pre-freeze fixture navigation state."""

    atomic_write_json(Path(path), bundle.model_dump(mode="json"))
    return Path(path)


def remove_unconfirmed_fixture(candidate: InputFixtureCandidateV1) -> None:
    """Cleanup helper for discarded pre-freeze bytes; confirmed bytes are immutable."""

    if candidate.confirmed:
        raise FixtureBuilderError("CONFIRMED_FIXTURE_IS_IMMUTABLE")
    path = Path(candidate.fixture_path)
    if path.is_symlink():
        raise FixtureBuilderError("FIXTURE_PATH_UNSAFE")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()


# Boundary codes that are walls: no fixture may record such an endpoint again.
# Credentials and gone endpoints cannot be drafted around; a drifted shape is a
# fact the rules teach.
BLOCKING_BOUNDARY_CODES = frozenset({"PLATFORM_REQUIRES_CREDENTIALS", "ENDPOINT_GONE", "METHOD_NOT_ALLOWED"})


RECORDED_KEYS_LIMIT = 64


def manifest_request_keys(fixture_root: Path) -> list[str]:
    """``METHOD host/path?canonical-query`` for every row a materialised fixture records (no bodies)."""

    from repoproof.execution.open_api_replay import RESPONSES_DIRNAME, canonical_query

    manifest = Path(fixture_root) / RESPONSES_DIRNAME / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        return []
    try:
        rows = json.loads(manifest.read_text(encoding="utf-8")).get("responses") or []
    except (OSError, ValueError, AttributeError):
        return []
    keys: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        host = str(row.get("host") or "").strip().lower()
        if not host:
            continue
        path = "/" + str(row.get("path") or "").strip().lstrip("/")
        query = canonical_query(str(row.get("query") or ""))
        method = str(row.get("method") or "GET").upper()
        keys.add(f"{method} {host}{path}" + (f"?{query}" if query else ""))
    return sorted(keys)[:RECORDED_KEYS_LIMIT]


def blocked_boundary_endpoints(known_boundaries) -> dict[tuple[str, str], str]:
    """``(host, path) -> code`` for the boundaries that are walls."""

    blocked: dict[tuple[str, str], str] = {}
    for row in known_boundaries or ():
        if not isinstance(row, dict) or str(row.get("code") or "") not in BLOCKING_BOUNDARY_CODES:
            continue
        host = str(row.get("host") or "").strip().lower()
        path = "/" + str(row.get("path") or "").strip().lstrip("/")
        if host:
            blocked.setdefault((host, path), str(row.get("code")))
    return blocked


def assert_recordings_avoid_known_boundaries(
    fixture_path: Path, known_boundaries: list[dict] | tuple[dict, ...], *, fixture_id: str
) -> None:
    """No materialised recording may target an endpoint an earlier rehearsal proved unusable.

    The blueprint-level gate reads request rows; a builder whose *code*
    assembles the requests recorded the gone endpoint again and the journey
    hit the same wall a second time
    (incident-known-boundary-reused-by-builder-code-*).
    """

    from repoproof.execution.open_api_replay import RESPONSES_DIRNAME

    blocked = blocked_boundary_endpoints(known_boundaries)
    if not blocked:
        return
    manifest = Path(fixture_path) / RESPONSES_DIRNAME / "manifest.json"
    if not manifest.is_file():
        return
    try:
        rows = json.loads(manifest.read_text(encoding="utf-8")).get("responses") or []
    except (OSError, ValueError, AttributeError):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        host = str(row.get("host") or "").strip().lower()
        path = "/" + str(row.get("path") or "").strip().lstrip("/")
        code = blocked.get((host, path))
        if code is None:
            continue
        raise WorkspaceBundleError(
            "FIXTURE_RECORDS_KNOWN_BOUNDARY",
            f"{host}{path}",
            diagnostics=(
                f"fixture {fixture_id} records GET {host}{path}, which the rehearsal proved {code}; "
                "record a usable endpoint instead — and the producer must call that one",
            ),
        )


def assert_recordings_well_formed(fixture_path: Path, *, fixture_id: str) -> None:
    """A recorded body of under two bytes, or JSON that does not parse, is the builder's defect.

    Raised before any producer runs: a producer cannot decode what was never
    written, and blaming it for six rounds taught nobody anything
    (incident-degenerate-recording-blamed-on-producer-*).
    """

    from repoproof.execution.open_api_replay import RESPONSES_DIRNAME
    from repoproof.execution.workspace_bundle import WorkspaceBundleError

    responses = Path(fixture_path) / RESPONSES_DIRNAME
    manifest = responses / "manifest.json"
    if not manifest.is_file():
        return
    try:
        rows = json.loads(manifest.read_text(encoding="utf-8")).get("responses") or []
    except (OSError, ValueError, AttributeError):
        return  # the replay stub reports an unreadable manifest itself
    problems: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("body") or "")
        body_path = responses / name
        if not name or not body_path.is_file():
            continue
        size = body_path.stat().st_size
        content_type = str(row.get("content_type") or "").lower()
        if size < 2:
            problems.append(f"{fixture_id}/{RESPONSES_DIRNAME}/{name}: {size} byte(s) — a degenerate body")
            continue
        if "json" in content_type:
            try:
                json.loads(body_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                problems.append(f"{fixture_id}/{RESPONSES_DIRNAME}/{name}: declared {content_type} but does not parse")
    if problems:
        raise WorkspaceBundleError(
            "FIXTURE_RECORDING_DEGENERATE",
            problems[0],
            diagnostics=(
                "the builder wrote a recorded body no producer could read; fix the builder's encoding "
                "of that body, never the producer",
                *problems[:8],
            ),
        )


_FRONTEND_ASSET_MIN_BYTES = 1024


def assert_frontend_assets_from_upstream(expected_dir: Path, upstream_dir: Path) -> None:
    """Every delivered .js/.css of 1 KB or more is a file the pinned upstream ships, byte for byte.

    A library written from memory has no truth to check against; when the
    upstream ships none, the interactive form is the boundary to propose
    (incident-fabricated-frontend-asset-*).
    """

    import hashlib

    from repoproof.execution.workspace_bundle import WorkspaceBundleError

    expected_dir = Path(expected_dir)
    delivered = [
        path
        for path in sorted(expected_dir.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in {".js", ".css"}
        and path.stat().st_size >= _FRONTEND_ASSET_MIN_BYTES
    ]
    if not delivered:
        return
    upstream_dir = Path(upstream_dir)
    shipped: set[str] = set()
    if upstream_dir.is_dir():
        for path in upstream_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".js", ".css"} and ".git" not in path.parts:
                try:
                    shipped.add(hashlib.sha256(path.read_bytes()).hexdigest())
                except OSError:
                    continue
    foreign = [
        path.relative_to(expected_dir).as_posix()
        for path in delivered
        if hashlib.sha256(path.read_bytes()).hexdigest() not in shipped
    ]
    if foreign:
        raise WorkspaceBundleError(
            "FRONTEND_ASSET_NOT_FROM_UPSTREAM",
            foreign[0],
            diagnostics=(
                f"FRONTEND_ASSET_NOT_FROM_UPSTREAM: {', '.join(foreign[:4])} — not shipped by the pinned upstream; "
                "a library written from memory has no truth to verify against, and the sealed delivery "
                "cannot fetch one: deliver a static image plus data files instead",
            ),
        )


_FONT_SUBTYPE_RE = re.compile(rb"/Subtype\s*/(Type1|MMType1|TrueType|Type0|Type3|CIDFontType0|CIDFontType2)\b")
_FONT_FILE_RE = re.compile(rb"/FontFile[23]?\b")
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


def _pdf_font_kinds(payload: bytes) -> tuple[set[str], bool]:
    """(font subtypes seen, any embedded font program) across raw objects and inflated streams."""

    import zlib

    chunks = [payload]
    for index, match in enumerate(_STREAM_RE.finditer(payload)):
        if index >= 64:
            break
        try:
            chunks.append(zlib.decompress(match.group(1)))
        except zlib.error:
            continue
    subtypes: set[str] = set()
    embedded = False
    for chunk in chunks:
        subtypes.update(m.group(1).decode("ascii") for m in _FONT_SUBTYPE_RE.finditer(chunk))
        if _FONT_FILE_RE.search(chunk):
            embedded = True
    return subtypes, embedded


def non_latin_samples(texts, *, limit: int = 8) -> list[str]:
    """Runs of letters outside the Latin ranges found in the user's text (CJK, Kana, Hangul, Arabic…)."""

    import unicodedata

    samples: list[str] = []
    for text in texts:
        run = ""
        for char in str(text):
            if ord(char) >= 0x0370 and unicodedata.category(char).startswith("L"):
                run += char
                continue
            if len(run) >= 2 and run not in samples:
                samples.append(run[:12])
            run = ""
        if len(run) >= 2 and run not in samples:
            samples.append(run[:12])
        if len(samples) >= limit:
            break
    return samples[:limit]


def pdf_missing_input_script(pdf_path: Path, input_texts) -> list[str]:
    """Non-Latin text from the input that this PDF cannot show: its fonts are the 14 core Type1 only.

    A PDF whose only fonts are the built-in Type1 set has no glyphs for CJK and
    the like; one with any embedded TrueType/Type0/Type3 font is left to the
    judge (incident-pdf-cannot-render-input-script-*).
    """

    samples = non_latin_samples(input_texts)
    if not samples:
        return []
    try:
        payload = Path(pdf_path).read_bytes()
    except OSError:
        return []
    subtypes, embedded = _pdf_font_kinds(payload)
    if not subtypes or embedded or (subtypes - {"Type1", "MMType1"}):
        return []
    return samples


def assert_pdf_shows_input_script(pdf_path: Path, input_texts, *, relative: str) -> None:
    from repoproof.execution.workspace_bundle import WorkspaceBundleError

    missing = pdf_missing_input_script(pdf_path, input_texts)
    if missing:
        raise WorkspaceBundleError(
            "PDF_CANNOT_RENDER_INPUT_SCRIPT",
            relative,
            diagnostics=(
                f"PDF_CANNOT_RENDER_INPUT_SCRIPT: {relative} uses only the built-in Type1 fonts, which have no "
                f"glyphs for the user's own text ({', '.join(missing[:4])}); no font the pinned upstream ships "
                "can show it — deliver an HTML print page (the browser supplies fonts) instead of a PDF",
            ),
        )


def input_text_samples(input_path: Path, *, limit_bytes: int = 200_000) -> list[str]:
    """Text file contents of an input directory (recordings excluded), bounded, for script checks."""

    from repoproof.execution.open_api_replay import RESPONSES_DIRNAME

    root = Path(input_path)
    if root.is_file():
        candidates = [root]
    else:
        candidates = [p for p in sorted(root.rglob("*")) if p.is_file() and RESPONSES_DIRNAME not in p.parts]
    texts: list[str] = []
    budget = limit_bytes
    for path in candidates:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        texts.append(text[:budget])
        budget -= len(text)
        if budget <= 0:
            break
    return texts
