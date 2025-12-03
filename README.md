# Folder Janitor — Installation
(AI coded) Script to keep Downloads folder clean

This sets up a daily scan of configured folders, deletes files after they have been present longer than the folder’s `days` threshold, and removes empty directories (so no “loose” empty dirs remain).

---

## 1) Create the config (JSON)

Create:

- `~/.config/folder-janitor/config.json`

Example:

```json
{
  "Downloads": {
    "path": "/home/user/Downloads",       // Path to check
    "days": 7,                            // Days to keep file 
    "Exceptions": ["-Hold", "-Torrents"]  // Don't check these subdirectories
  }
}
````

Notes:

* Exception entries are **directory names** (not paths). Any directory with a matching name is not descended into.

---

## 2) Install the script

Place the script at:

* `~/.local/bin/folder-janitor.py`

Make it executable:

```bash
chmod +x ~/.local/bin/folder-janitor.py
```

Sanity check the shebang (must be exactly this on line 1):

```bash
head -n 1 ~/.local/bin/folder-janitor.py | cat -A
# must show: #!/usr/bin/env python3$
```

Dry-run test:

```bash
~/.local/bin/folder-janitor.py --config ~/.config/folder-janitor/config.json --dry-run --verbose
```

If you ever see X11 “import: unable to grab mouse …” errors, the script is being executed by the shell (often due to a broken shebang). Run with:

```bash
python3 ~/.local/bin/folder-janitor.py --config ~/.config/folder-janitor/config.json --dry-run --verbose
```

---

## 3) State file (automatic)

The script creates/updates:

* `~/.local/state/folder-janitor/state.json`

This records per-file `first_seen` timestamps so retention is based on **how long the file has been present**, not on file mtime/ctime.

Inspect it:

```bash
cat ~/.local/state/folder-janitor/state.json
```

---

## 4) systemd user service + timer (daily)

Create:

* `~/.config/systemd/user/folder-janitor.service`

```ini
[Unit]
Description=Folder Janitor (delete files older than configured days)

[Service]
Type=oneshot
ExecStart=%h/.local/bin/folder-janitor.py --config %h/.config/folder-janitor/config.json
```

Create:

* `~/.config/systemd/user/folder-janitor.timer`

```ini
[Unit]
Description=Run Folder Janitor daily

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
```

Enable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now folder-janitor.timer
```

Verify:

```bash
systemctl --user list-timers --all | grep folder-janitor
```

Check the last/next run times
```bash
systemctl --user list-timers --all | grep folder-janitor
```

Logs:

```bash
journalctl --user -u folder-janitor.service -n 200 --no-pager
```

---

## 5) Behavior summary

* Scans each configured `path` daily.
* Skips exception directories by name (the script does not descend into them).
* Tracks `first_seen` per file in `~/.local/state/folder-janitor/state.json`.
* Deletes files once `first_seen` age exceeds `days`.
* Removes directories that become truly empty (excluding exception trees).
