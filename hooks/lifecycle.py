"""
hooks/lifecycle.py — Lifecycle hooks for airtable-backup.

on_credentials_saved verifies the token (whoami + list bases) so the operator
gets immediate feedback. Read-only; never writes to Airtable.

Reference: docs/06-sync-and-jobs.md "Lifecycle hooks"
"""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from nousviz_sdk.hooks import HookContext, HookResult

import airtable_backup_sync as sync_mod  # noqa: E402
from airtable_backup_client import AirtableClient, AirtableError  # noqa: E402


def on_credentials_saved(ctx: HookContext) -> HookResult:
    try:
        cfg = sync_mod.load_config()
        client = AirtableClient(cfg["token"])
        who = client.whoami()
        bases = client.list_bases()
        included = [b for b in bases if sync_mod.base_included(b, cfg["base_filter"])]
        msg = f"Connected as {who.get('id', '?')} — {len(included)} of {len(bases)} base(s) will be backed up."
        if not bases:
            msg += " The token can't see any bases: add bases or workspaces to it at airtable.com/create/tokens."
        return HookResult(ok=True, message=msg,
                          data={"bases_visible": len(bases), "bases_included": len(included)})
    except AirtableError as e:
        return HookResult(ok=False, message=f"Token saved but Airtable rejected it: {e}")
    except Exception as e:  # noqa: BLE001
        return HookResult(ok=False, message=f"Token saved but probe failed: {e.__class__.__name__}: {e}")


def on_first_run_success(ctx: HookContext) -> HookResult:
    return HookResult(ok=True, message="First Airtable backup complete — browse it on the Overview tab.")
