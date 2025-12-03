#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, Any, Tuple, List, Set

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "folder-janitor"
STATE_FILE = STATE_DIR / "state.json"


def eprint(*a):
    print(*a, file=sys.stderr)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def normalize_config(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Config must be a non-empty JSON object mapping names -> settings objects.")

    out: Dict[str, Dict[str, Any]] = {}
    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            raise ValueError(f'Config entry "{name}" must be an object.')

        path = cfg.get("path")
        days = cfg.get("days")
        exclusions = cfg.get("Exceptions", [])

        if not isinstance(path, str) or not path.strip():
            raise ValueError(f'Config entry "{name}": "path" must be a non-empty string.')
        if not isinstance(days, int) or days < 0:
            raise ValueError(f'Config entry "{name}": "days" must be a non-negative integer.')
        if exclusions is None:
            exclusions = []
        if not isinstance(exclusions, list) or not all(isinstance(x, str) for x in exclusions):
            raise ValueError(f'Config entry "{name}": "Exceptions" must be a list of strings.')

        out[name] = {
            "path": path,
            "days": days,
            "exceptions": set(exclusions),
        }
    return out


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {"files": {}}
    try:
        st = load_json(STATE_FILE)
        if not isinstance(st, dict) or "files" not in st or not isinstance(st["files"], dict):
            return {"files": {}}
        return st
    except (OSError, ValueError, TypeError):
        return {"files": {}}


def prune_missing_entries(state_files: Dict[str, float]) -> None:
    missing = [k for k in list(state_files.keys()) if not Path(k).exists()]
    for k in missing:
        del state_files[k]


def iter_files(root: Path, exclusions: Set[str]):
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in exclusions]

        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if p.is_symlink():
                    continue
                if not p.is_file():
                    continue
            except OSError:
                continue
            yield p


def delete_path(p: Path) -> Tuple[bool, str]:
    try:
        p.unlink()
        return True, "deleted"
    except IsADirectoryError:
        try:
            shutil.rmtree(p)
            return True, "deleted_dir"
        except OSError as ex:
            return False, f"failed: {ex}"
    except OSError as ex:
        return False, f"failed: {ex}"


def collect_dirs_excluding_exceptions(root: Path, exclusions: Set[str]) -> List[Path]:
    """
    Collect directories under root, excluding traversal into directories whose *name* is in exclusions.
    Returns a list excluding root itself.
    """
    dirs: List[Path] = []
    for dirpath, dirnames, _filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in exclusions]

        d = Path(dirpath)
        if d != root:
            dirs.append(d)
    return dirs


def remove_empty_dirs(root: Path, exclusions: Set[str], dry_run: bool, verbose: bool) -> int:
    """
    Remove truly empty directories under root (bottom-up), excluding any directory named in exclusions
    (and excluding traversal into those directories).
    """
    removed = 0

    dirs = collect_dirs_excluding_exceptions(root, exclusions)
    dirs.sort(key=lambda p: len(str(p)), reverse=True)

    for d in dirs:
        try:
            if d.is_symlink():
                continue
            if not d.is_dir():
                continue
            if any(d.iterdir()):
                continue

            if dry_run:
                print(f"[DRY] rmdir: {d}")
            else:
                d.rmdir()
                if verbose:
                    print(f"rmdir: {d}")
            removed += 1
        except OSError:
            continue

    return removed


def main():
    ap = argparse.ArgumentParser(description="Daily folder janitor: track first-seen time and delete after N days.")
    ap.add_argument("--config", required=True, help="Path to config.json")
    ap.add_argument("--dry-run", action="store_true", help="Do not delete; only report what would be deleted.")
    ap.add_argument("--verbose", action="store_true", help="More output.")
    args = ap.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        eprint(f"Config file not found: {config_path}")
        return 2

    raw = load_json(config_path)
    cfg = normalize_config(raw)

    now = time.time()
    state = load_state()
    state_files: Dict[str, float] = state.get("files", {})
    if not isinstance(state_files, dict):
        state_files = {}

    prune_missing_entries(state_files)

    total_seen = 0
    total_deleted = 0
    total_failed = 0
    total_rmdir = 0

    for name, entry in cfg.items():
        root = Path(entry["path"]).expanduser()
        days = entry["days"]
        exclusions = entry["exceptions"]
        cutoff = now - (days * 86400)

        if not root.exists():
            eprint(f'[{name}] skip (path not found): {root}')
            continue
        if not root.is_dir():
            eprint(f'[{name}] skip (not a directory): {root}')
            continue

        if args.verbose:
            print(f'[{name}] scanning: {root} (days={days}, exceptions={sorted(exclusions)})')

        for fpath in iter_files(root, exclusions):
            total_seen += 1
            spath = str(fpath)

            first_seen = state_files.get(spath)
            if first_seen is None:
                state_files[spath] = now
                continue

            if first_seen <= cutoff:
                age_days = (now - first_seen) / 86400.0
                if args.dry_run:
                    print(f"[DRY] delete: {fpath}  (first_seen_age={age_days:.2f} days > {days})")
                    total_deleted += 1
                else:
                    ok, msg = delete_path(fpath)
                    if ok:
                        print(f"delete: {fpath}")
                        total_deleted += 1
                        state_files.pop(spath, None)
                    else:
                        eprint(f"FAILED: {fpath} ({msg})")
                        total_failed += 1

        removed_dirs = remove_empty_dirs(root, exclusions, args.dry_run, args.verbose)
        total_rmdir += removed_dirs
        if args.verbose and removed_dirs:
            print(f"[{name}] removed empty dirs: {removed_dirs}")

    state["files"] = state_files
    atomic_write_json(STATE_FILE, state)

    if args.verbose or args.dry_run:
        print(
            f"done: seen={total_seen}, delete={total_deleted}, rmdir={total_rmdir}, failed={total_failed}, "
            f"state={STATE_FILE}"
        )

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
