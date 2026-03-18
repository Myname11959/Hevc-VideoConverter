# mkv_tools/mkv_suite/core/auto_sync_controller.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from hevc_gui.mkv_suite.core.auto_sync_manager import probe_suggested_ms, should_apply

try:
    from PyQt5.QtCore import QSettings
except Exception:  # pragma: no cover
    from PySide6.QtCore import QSettings  # type: ignore

_GROUP = "AutoSync"
_K_ENABLED = "enabled"
_K_OVERRIDES = "overrides_json"   # { "path": { "tid": ms, ... }, ... }
_K_RECENT = "recent_paths_json"

@dataclass
class State:
    enabled: bool = False
    current_path: str = ""
    overrides: Dict[int, int] = None  # tid->ms
    suggested: Dict[int, int] = None  # tid->ms

class AutoSyncController:
    def __init__(self, mkvmerge_bin: str = "mkvmerge", settings: Optional[QSettings] = None) -> None:
        self.mkvmerge_bin = mkvmerge_bin
        self.s = settings or QSettings()
        self.state = State(enabled=self._load_enabled(), current_path="", overrides={}, suggested={})

    # ---------- settings
    def _load_enabled(self) -> bool:
        self.s.beginGroup(_GROUP)
        try:
            return bool(self.s.value(_K_ENABLED, False, type=bool))
        finally:
            self.s.endGroup()

    def save_enabled(self, enabled: bool) -> None:
        self.state.enabled = bool(enabled)
        self.s.beginGroup(_GROUP)
        try:
            self.s.setValue(_K_ENABLED, bool(enabled))
        finally:
            self.s.endGroup()

    def _load_json(self, key: str, default):
        v = self.s.value(key, "")
        if not v:
            return default
        try:
            return json.loads(str(v))
        except Exception:
            return default

    def _save_json(self, key: str, obj) -> None:
        self.s.setValue(key, json.dumps(obj, ensure_ascii=False))

    def _load_overrides_for(self, path: str) -> Dict[int, int]:
        self.s.beginGroup(_GROUP)
        try:
            all_map = self._load_json(_K_OVERRIDES, {})
            per = all_map.get(path, {}) if isinstance(all_map, dict) else {}
            out: Dict[int, int] = {}
            if isinstance(per, dict):
                for k, v in per.items():
                    try:
                        out[int(k)] = int(v)
                    except Exception:
                        pass
            return out
        finally:
            self.s.endGroup()

    def _save_overrides_for(self, path: str, overrides: Dict[int, int], keep_max_files: int = 30) -> None:
        self.s.beginGroup(_GROUP)
        try:
            all_map = self._load_json(_K_OVERRIDES, {})
            recent = self._load_json(_K_RECENT, [])
            if not isinstance(all_map, dict):
                all_map = {}
            if not isinstance(recent, list):
                recent = []

            cleaned = {str(int(tid)): int(ms) for tid, ms in overrides.items() if int(ms) != 0}

            if cleaned:
                all_map[path] = cleaned
            else:
                all_map.pop(path, None)

            if path in recent:
                recent.remove(path)
            recent.insert(0, path)
            recent = recent[:keep_max_files]

            # prune
            for k in list(all_map.keys()):
                if k not in recent:
                    all_map.pop(k, None)

            self._save_json(_K_OVERRIDES, all_map)
            self._save_json(_K_RECENT, recent)
        finally:
            self.s.endGroup()

    # ---------- core
    def set_source(self, path: str) -> None:
        p = str(Path(path))
        if p == self.state.current_path:
            return
        self.state.current_path = p
        self.state.overrides = self._load_overrides_for(p)
        self.state.suggested = {}

    def ensure_suggested(self) -> None:
        if not self.state.current_path or self.state.suggested:
            return
        res = probe_suggested_ms(self.state.current_path, mkvmerge_bin=self.mkvmerge_bin)
        self.state.suggested = dict(res.suggested_ms)

    def get_override(self, tid: int) -> int:
        return int(self.state.overrides.get(int(tid), 0))

    def set_override(self, tid: int, ms: int) -> None:
        tid = int(tid)
        ms = int(ms)
        if ms == 0:
            self.state.overrides.pop(tid, None)
        else:
            self.state.overrides[tid] = ms
        if self.state.current_path:
            self._save_overrides_for(self.state.current_path, self.state.overrides)

    def effective_ms(self, tid: int, enabled: bool) -> int:
        tid = int(tid)
        if tid in self.state.overrides:
            return int(self.state.overrides[tid])
        if enabled:
            self.ensure_suggested()
            ms = int(self.state.suggested.get(tid, 0))
            return ms if should_apply(ms) else 0
        return 0

    def build_sync_args(self, audio_ids: List[int], enabled: bool) -> List[str]:
        args: List[str] = []
        for tid in audio_ids:
            ms = self.effective_ms(tid, enabled)
            if ms != 0:
                args += ["--sync", f"{int(tid)}:{int(ms)}"]
        return args
