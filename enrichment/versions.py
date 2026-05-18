"""Per-run version metadata collection.

Called at run-start to snapshot the schema/prompt/SDK/model versions
this run will use. The output is written into config.json:versions
(see BleakHouse-vwwg / docs/version_pinning_propagation_plan.md).

The five blocks:

  schemas        — {ClassName: schema_version} for every Pydantic
                   class in enrichment.llm.schemas that declares
                   schema_version: ClassVar[str].
  prompts        — {PROMPT_NAME: '2026-05-18'} for every
                   *_VERSION constant in enrichment.llm.*_prompts.
  sdks           — {pkg_name: installed_version} for the five LLM
                   SDKs we care about (anthropic, openai,
                   cerebras-cloud-sdk, google-genai, pydantic).
                   Missing packages report None.
  models         — {task_name: 'provider/api_model'} for every task
                   the seam currently resolves. Snapshot of
                   resolved state at call time, so it reflects the
                   active profile + any --provider-override flags.
  pyproject_commit — short SHA of git HEAD, or None if not a git
                   repo or git is unavailable.

This helper is read-only; it doesn't mutate the seam or anything
else. Idempotent.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_SDKS_PINNED: tuple[str, ...] = (
    "anthropic",
    "openai",
    "cerebras-cloud-sdk",
    "google-genai",
    "pydantic",
)
"""The SDK package names whose versions get recorded in every run.

Extend deliberately as new providers land. Removing a pin is a
behaviour change (older runs continue to reference the removed
key); prefer to keep historical pins."""


_PROMPT_MODULES: tuple[str, ...] = (
    "enrichment.llm.host_prep_prompts",
    "enrichment.llm.design_segments_prompts",
    "enrichment.llm.generation_prompts",
    "enrichment.llm.curation_prompts",
)
"""Modules walked by `collect_prompt_versions()`. Add a new module
here when a new *_prompts.py is introduced under enrichment/llm/."""


def collect_schema_versions() -> dict[str, str]:
    """Return {ClassName: schema_version} for every Pydantic class
    in enrichment.llm.schemas that declares schema_version."""
    schemas = importlib.import_module("enrichment.llm.schemas")
    out: dict[str, str] = {}
    for name in dir(schemas):
        obj = getattr(schemas, name)
        if not inspect.isclass(obj):
            continue
        # Only classes defined in this module (skip imports).
        if obj.__module__ != "enrichment.llm.schemas":
            continue
        version = getattr(obj, "schema_version", None)
        if isinstance(version, str):
            out[name] = version
    return out


def collect_prompt_versions() -> dict[str, str]:
    """Return {VERSION_CONSTANT_NAME: value} for every *_VERSION
    constant in the prompt modules. The key is the constant name
    minus the trailing '_VERSION' suffix, which makes the output
    align with the prompt itself's name (e.g. 'INTERVIEW_SYSTEM').
    """
    out: dict[str, str] = {}
    for modname in _PROMPT_MODULES:
        mod = importlib.import_module(modname)
        for name in dir(mod):
            if not name.endswith("_VERSION"):
                continue
            value = getattr(mod, name)
            if not isinstance(value, str):
                continue
            # Strip the trailing '_VERSION' for the output key.
            key = name[: -len("_VERSION")]
            out[key] = value
    return out


def collect_sdk_versions() -> dict[str, str | None]:
    """Return {pkg_name: installed_version} for the SDKs we pin.

    None means the package isn't installed in the current venv —
    captured deliberately so a run that didn't have, say,
    cerebras-cloud-sdk available reads as missing rather than
    silently absent.
    """
    out: dict[str, str | None] = {}
    for pkg in _SDKS_PINNED:
        try:
            out[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def collect_resolved_models() -> dict[str, str]:
    """Snapshot of the seam's resolved (task → ModelSpec) map at
    call time. Reflects the active provider profile + any
    --provider-override flags that have been layered on.

    Output value shape: 'provider/api_model' (e.g.
    'anthropic/claude-haiku-4-5-20251001',
    'openai_compatible/Qwen/Qwen3-235B-A22B-Instruct-2507').
    """
    settings = importlib.import_module("enrichment.llm.settings")
    resolved = settings.resolved_providers()  # dict[task_name, ModelSpec]
    out: dict[str, str] = {}
    for task, spec in resolved.items():
        out[task] = f"{spec.provider}/{spec.model}"
    return out


def collect_pyproject_commit(repo_root: Path | None = None) -> str | None:
    """Short git SHA of HEAD, or None if not in a git repo or git
    isn't available. Defaults to the repo root inferred from this
    file's location."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def collect_run_versions(
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Top-level collector — assembles the full `versions` block.

    Output shape (suitable for embedding directly in config.json):

        {
          "schemas": {ClassName: schema_version, ...},
          "prompts": {PROMPT_NAME: VERSION, ...},
          "sdks": {pkg_name: installed_version or None, ...},
          "models": {task_name: "provider/api_model", ...},
          "pyproject_commit": "abc12345" or None,
        }
    """
    return {
        "schemas": collect_schema_versions(),
        "prompts": collect_prompt_versions(),
        "sdks": collect_sdk_versions(),
        "models": collect_resolved_models(),
        "pyproject_commit": collect_pyproject_commit(repo_root),
    }
