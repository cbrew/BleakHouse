"""Task → ModelSpec resolution.

Task → model routing is profile-driven and configured in params.yaml.
At import time we load the default profile (`production`); CLI flags or
test code can activate() a different profile or layer overrides.

Profile resolution (highest precedence first):
  1. Per-task overrides passed to activate(...)
  2. The active profile's entries (provider_profiles.<name> in params.yaml)
  3. The task_models defaults in params.yaml

Public API preserved across the 2026-05-15 refactor:
  - for_task(task) → ModelSpec
  - register_task(task, spec) — programmatic override
  - known_tasks() → tuple[str, ...]

New API:
  - activate(profile, overrides=None) — switch the active profile
  - active_profile_name() — current profile name
  - resolved_providers() → dict[task, ModelSpec] — full self-describing
    snapshot of the current resolution; write this into run config.json
    for provenance.

Generator IDs (e.g. `anthropic_haiku_4_5`, `openai_5_mini`) live in
params.yaml's `generators` list and are translated to ModelSpec by
_generator_to_modelspec below. The translation is the only place that
maps params.yaml's `provider: anthropic|openai|cerebras` vocabulary into
the seam's `provider: anthropic | openai_compatible` + `hosting: ...`
vocabulary; callers see only the seam vocabulary.
"""
from __future__ import annotations

from threading import Lock

from enrichment.llm.types import ModelSpec

# Hosting base URLs for openai-compatible providers. Anthropic and
# OpenAI native don't need an explicit base_url; the SDKs default to
# the right endpoint. Cerebras and others do.
_BASE_URL_BY_HOSTING: dict[str, str | None] = {
    "anthropic": None,
    "openai": None,
    "cerebras": "https://api.cerebras.ai/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
    "together": "https://api.together.xyz/v1",
    "alibaba": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}


def _generator_to_modelspec(gen: dict) -> ModelSpec:
    """Translate a params.yaml generators[] entry into the seam vocabulary.

    params.yaml uses `provider: anthropic | openai | cerebras` (the
    semantic platform). The seam uses `provider: anthropic |
    openai_compatible` (the SDK shape). The mapping:
      anthropic → provider=anthropic, hosting=anthropic
      openai    → provider=openai_compatible, hosting=openai
      cerebras  → provider=openai_compatible, hosting=cerebras
      <other>   → provider=openai_compatible, hosting=<as-given>
    """
    platform = gen["provider"]
    api_model = gen["api_model"]
    if platform == "anthropic":
        return ModelSpec(provider="anthropic", model=api_model, hosting="anthropic")
    # Everything else routes through the openai-compatible provider; the
    # `hosting` field distinguishes per-platform behaviour (gpt-5 family
    # API surface differences, reasoning_effort placement, etc.).
    hosting = "openai" if platform == "openai" else platform
    return ModelSpec(
        provider="openai_compatible",
        model=api_model,
        hosting=hosting,
        base_url=_BASE_URL_BY_HOSTING.get(hosting),
    )


def _load_from_params() -> tuple[dict[str, ModelSpec], dict[str, dict[str, str]], str]:
    """Read params.yaml and return (task_models, provider_profiles, default_profile_name).

    task_models is dict[task_name, ModelSpec] — the base layer.
    provider_profiles is dict[profile_name, dict[task_name, model_id]] —
      empty inner dict means "use task_models as-is".
    default_profile_name is the active profile at import time.

    Raises at import time on any malformed entry — fail loudly during
    config load rather than at first call.
    """
    from enrichment import params as _params

    generators_raw = _params.get("generators", default=[]) or []
    generator_by_id: dict[str, dict] = {}
    for g in generators_raw:
        if not isinstance(g, dict):
            raise ValueError(f"params.yaml generators: expected dict, got {g!r}")
        generator_by_id[str(g["id"])] = g

    def _spec_for(model_id: str, source: str) -> ModelSpec:
        gen = generator_by_id.get(model_id)
        if gen is None:
            raise ValueError(
                f"{source} references unknown generator id {model_id!r}; "
                f"registered generators: {sorted(generator_by_id)}"
            )
        return _generator_to_modelspec(gen)

    task_models_raw = _params.get("task_models", default={}) or {}
    if not isinstance(task_models_raw, dict):
        raise ValueError(
            f"params.yaml task_models: expected mapping, got {task_models_raw!r}"
        )
    task_models: dict[str, ModelSpec] = {
        task: _spec_for(str(model_id), f"task_models.{task}")
        for task, model_id in task_models_raw.items()
    }

    profiles_raw = _params.get("provider_profiles", default={}) or {}
    if not isinstance(profiles_raw, dict):
        raise ValueError(
            f"params.yaml provider_profiles: expected mapping, got {profiles_raw!r}"
        )
    profiles: dict[str, dict[str, str]] = {}
    for name, body in profiles_raw.items():
        body = body or {}
        if not isinstance(body, dict):
            raise ValueError(
                f"params.yaml provider_profiles.{name}: expected mapping, got {body!r}"
            )
        # Validate every model_id in the profile resolves to a generator —
        # cheaper to fail at config load than at run time.
        for task, model_id in body.items():
            _spec_for(str(model_id), f"provider_profiles.{name}.{task}")
        profiles[str(name)] = {str(t): str(m) for t, m in body.items()}

    default_profile = str(_params.get("default_provider_profile", default="production"))
    if default_profile not in profiles:
        raise ValueError(
            f"params.yaml default_provider_profile={default_profile!r} "
            f"not in provider_profiles; defined: {sorted(profiles)}"
        )

    return task_models, profiles, default_profile


# ---------------------------------------------------------------------------
# Active-resolution state. Module-level singletons protected by a lock so
# accidental concurrent activate() calls are serialised. The active map is
# the source of truth for for_task().
# ---------------------------------------------------------------------------

_state_lock = Lock()
_TASK_MODELS: dict[str, ModelSpec]
_PROFILES: dict[str, dict[str, str]]
_DEFAULT_PROFILE: str
_active_profile: str
_active_overrides: dict[str, str]
_resolved: dict[str, ModelSpec]


def _resolve(
    profile: str, overrides: dict[str, str],
) -> dict[str, ModelSpec]:
    """Compose the active resolution: task_models < profile < overrides."""
    if profile not in _PROFILES:
        raise ValueError(
            f"unknown provider profile {profile!r}; defined: {sorted(_PROFILES)}"
        )
    # Generator id → ModelSpec lookup, via the generators registry.
    from enrichment import params as _params
    generators_raw = _params.get("generators", default=[]) or []
    by_id = {str(g["id"]): g for g in generators_raw if isinstance(g, dict)}

    def spec_for(model_id: str, source: str) -> ModelSpec:
        gen = by_id.get(model_id)
        if gen is None:
            raise ValueError(
                f"{source} references unknown generator id {model_id!r}"
            )
        return _generator_to_modelspec(gen)

    resolved = dict(_TASK_MODELS)
    for task, model_id in _PROFILES[profile].items():
        resolved[task] = spec_for(model_id, f"profile {profile}.{task}")
    for task, model_id in overrides.items():
        resolved[task] = spec_for(model_id, f"override {task}")
    return resolved


def activate(profile: str | None = None, overrides: dict[str, str] | None = None) -> None:
    """Switch the active profile and optional per-task overrides.

    Call this once at process start (run_pipeline does so from CLI
    flags). Subsequent for_task() calls reflect the new resolution.
    Passing profile=None re-applies the params.yaml default."""
    global _active_profile, _active_overrides, _resolved
    with _state_lock:
        profile_name = profile or _DEFAULT_PROFILE
        overrides_map = dict(overrides or {})
        _resolved = _resolve(profile_name, overrides_map)
        _active_profile = profile_name
        _active_overrides = overrides_map


def active_profile_name() -> str:
    return _active_profile


def active_overrides() -> dict[str, str]:
    """Per-task overrides currently layered on top of the active profile.
    Returned as a copy; mutating it has no effect on the active map."""
    return dict(_active_overrides)


def resolved_providers() -> dict[str, ModelSpec]:
    """Snapshot of the fully-resolved task → ModelSpec mapping. Write
    this into a run's config.json `providers.resolved_per_task` block
    for self-describing provenance."""
    return dict(_resolved)


def for_task(task: str) -> ModelSpec:
    """Return the ModelSpec configured for the given task in the active
    resolution. Raises KeyError for unknown tasks — explicit failure is
    better than silently routing to a wrong model."""
    try:
        return _resolved[task]
    except KeyError as exc:
        raise KeyError(
            f"no ModelSpec configured for task {task!r}; "
            f"known tasks: {sorted(_resolved)}"
        ) from exc


def register_task(task: str, spec: ModelSpec) -> None:
    """Register or override a task's ModelSpec in the active resolution.

    Mostly for tests / experimental code that wants an ad-hoc swap
    without touching params.yaml. The change applies until the next
    activate() call (which rebuilds from profile + overrides)."""
    with _state_lock:
        _resolved[task] = spec


def known_tasks() -> tuple[str, ...]:
    """Currently-registered task names in the active resolution."""
    return tuple(sorted(_resolved))


# ---------------------------------------------------------------------------
# Initialise from params.yaml at import time, applying the default profile.
# ---------------------------------------------------------------------------

_TASK_MODELS, _PROFILES, _DEFAULT_PROFILE = _load_from_params()
_active_profile = _DEFAULT_PROFILE
_active_overrides = {}
_resolved = _resolve(_DEFAULT_PROFILE, {})
