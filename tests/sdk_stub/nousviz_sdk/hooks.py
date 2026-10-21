from dataclasses import dataclass, field
@dataclass
class HookContext:
    plugin_id: str
    hook_name: str
    run_id: int | None = None
    payload: dict = field(default_factory=dict)
@dataclass
class HookResult:
    ok: bool
    message: str | None = None
    data: dict | None = None
