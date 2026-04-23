from __future__ import annotations

from . import provider as _provider


def _fallback_collect_opencode_available_models(config: dict) -> list[str]:
    """Compatibility fallback when older provider modules lack the helper."""
    available_models: list[str] = []
    providers = config.get("provider", {}) or {}

    for provider_id, provider_cfg in providers.items():
        raw_models = (provider_cfg or {}).get("models") or {}
        if isinstance(raw_models, dict):
            items = raw_models.items()
        elif isinstance(raw_models, list):
            items = [
                (str(model.get("id") or "").strip(), model)
                for model in raw_models
                if isinstance(model, dict)
            ]
        else:
            items = []

        for model_id, _model_cfg in items:
            model_id = str(model_id or "").strip()
            if not model_id:
                continue
            available_models.append(f"{provider_id}/{model_id}")

    deduped_models: list[str] = []
    seen: set[str] = set()
    for model_ref in available_models:
        if model_ref in seen:
            continue
        seen.add(model_ref)
        deduped_models.append(model_ref)
    return deduped_models


def _fallback_resolve_opencode_default_model(config: dict) -> str | None:
    explicit_model = str(config.get("model") or "").strip()
    if explicit_model:
        return explicit_model

    available_models = _fallback_collect_opencode_available_models(config)
    return available_models[0] if available_models else None


def _fallback_collect_openclaw_available_models(config: dict) -> list[str]:
    available_models: list[str] = []
    providers = (config.get("models") or {}).get("providers") or {}

    for provider_id, provider_cfg in providers.items():
        raw_models = (provider_cfg or {}).get("models") or {}
        if isinstance(raw_models, dict):
            items = raw_models.items()
        elif isinstance(raw_models, list):
            items = [
                (str(model.get("id") or "").strip(), model)
                for model in raw_models
                if isinstance(model, dict)
            ]
        else:
            items = []

        for model_id, _model_cfg in items:
            model_id = str(model_id or "").strip()
            if not model_id:
                continue
            available_models.append(f"{provider_id}/{model_id}")

    deduped_models: list[str] = []
    seen: set[str] = set()
    for model_ref in available_models:
        if model_ref in seen:
            continue
        seen.add(model_ref)
        deduped_models.append(model_ref)
    return deduped_models


def _fallback_resolve_openclaw_default_model(config: dict) -> str | None:
    primary_model = (
        (((config.get("agents") or {}).get("defaults") or {}).get("model") or {}).get("primary")
    )
    if isinstance(primary_model, str) and primary_model.strip():
        return primary_model.strip()

    available_models = _fallback_collect_openclaw_available_models(config)
    return available_models[0] if available_models else None


AgentProviderConfig = _provider.AgentProviderConfig
IAgentProvider = _provider.IAgentProvider
create_agent_provider = _provider.create_agent_provider
collect_opencode_available_models = getattr(
    _provider,
    "collect_opencode_available_models",
    _fallback_collect_opencode_available_models,
)
collect_openclaw_available_models = getattr(
    _provider,
    "collect_openclaw_available_models",
    _fallback_collect_openclaw_available_models,
)
resolve_opencode_default_model = getattr(
    _provider,
    "resolve_opencode_default_model",
    _fallback_resolve_opencode_default_model,
)
resolve_openclaw_default_model = getattr(
    _provider,
    "resolve_openclaw_default_model",
    _fallback_resolve_openclaw_default_model,
)

__all__ = [
    "AgentProviderConfig",
    "IAgentProvider",
    "collect_openclaw_available_models",
    "collect_opencode_available_models",
    "create_agent_provider",
    "resolve_openclaw_default_model",
    "resolve_opencode_default_model",
]
