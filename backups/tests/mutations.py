"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

S = "backups/services.py"
BC = "backups/management/commands/backup.py"
RC = "backups/management/commands/restore.py"
CV = "core/views.py"

MUTATIONS = [
    # --- tools / connection ---
    ("PG_BIN_DIR ignored", S, "    if settings.PG_BIN_DIR:", "    if False:"),
    ("Linux tool name without .exe not found", S,
     "        for candidate in (Path(settings.PG_BIN_DIR) / name, Path(settings.PG_BIN_DIR) / f\"{name}.exe\"):",
     "        for candidate in (Path(settings.PG_BIN_DIR) / f\"{name}.exe\",):"),
    ("Missing tool not reported", S, "        if found:\n            return found", "        return found"),
    ("Blank settings passed as empty args", S, "        if db.get(key):\n            args +=", "        if True:\n            args +="),
    ("Password not passed", S, '        env["PGPASSWORD"] = _db()["PASSWORD"]', "        pass"),
    ("Failures ignored", S, "    if result.returncode != 0:", "    if False:"),
    ("Error text lost", S, '        raise BackupError(f"{program} failed: {(result.stderr or result.stdout).strip()}")',
     '        raise BackupError(f"{program} failed")'),
    # --- create ---
    ("Plain SQL dump instead of custom format", S, '"--format=custom", "--no-owner",\n              "--file"',
     '"--no-owner",\n              "--file"'),
    ("Dump not verified", S, '        _run([pg_tool("pg_restore"), "--list", str(partial)])', "        pass"),
    ("Partial file left after failure", S, "        partial.unlink(missing_ok=True)\n        raise", "        raise"),
    ("UTC timestamp", S, "    stamp = timezone.localtime(now or timezone.now()).strftime(STAMP_FORMAT)",
     "    stamp = (now or timezone.now()).strftime(STAMP_FORMAT)"),
    ("Media never included", S,
     '        media = _zip_media(folder / f"{PREFIX}{stamp}-media.zip") if include_media else None',
     "        media = None"),
    ("Media always included", S,
     '        media = _zip_media(folder / f"{PREFIX}{stamp}-media.zip") if include_media else None',
     '        media = _zip_media(folder / f"{PREFIX}{stamp}-media.zip")'),
    ("Absolute paths in media zip", S, "            archive.write(path, path.relative_to(media).as_posix())",
     "            archive.write(path)"),
    ("Empty media zip written", S, "    if not files:\n        return None", "    if False:\n        return None"),
    # --- list / prune ---
    ("Oldest backups listed first", S, "    return sorted(found, key=lambda b: b.stamp, reverse=True)",
     "    return sorted(found, key=lambda b: b.stamp)"),
    ("Prune keeps one too many", S, "    removed = list_backups()[keep:]", "    removed = list_backups()[keep + 1:]"),
    ("Prune can delete everything", S, "    if keep < 1:\n        raise BackupError", "    if False:\n        raise BackupError"),
    ("Pruned media zips left behind", S, "        if backup.media:\n            backup.media.unlink()",
     "        if False:\n            backup.media.unlink()"),
    ("Never overdue", S, "    if latest is None:\n        return True", "    if latest is None:\n        return False"),
    ("Warning window ignored", S,
     "    return (now or timezone.now()) - latest.created > dt.timedelta(hours=settings.BACKUP_WARN_HOURS)",
     "    return False"),
    # --- restore ---
    ("Restore without --clean", S, '"--clean", "--if-exists", "--no-owner",\n          "--single-transaction"',
     '"--if-exists", "--no-owner",\n          "--single-transaction"'),
    ("Restore not in one transaction", S, '"--no-owner",\n          "--single-transaction", "--dbname"',
     '"--no-owner",\n          "--dbname"'),
    ("Media not restored", S, "    if include_media and backup.media:\n        _extract_media",
     "    if False:\n        _extract_media"),
    ("Zip slip allowed", S, "            if not target.is_relative_to(media):", "            if False:"),
    ("Backup outside folder not found", S, "    if match and path.is_file():", "    if False:"),
    # --- commands ---
    ("Failure not logged", BC, '            self._log(f"FAILED {exc}")\n', ""),
    ("Old backups never pruned", BC, "            removed = prune(keep)", "            removed = []"),
    ("--list makes a backup", BC, "                self.stdout.write(f\"{b.stamp}  {_size(b.size):>10}  {b.dump.name}{media}\")\n            return",
     "                self.stdout.write(f\"{b.stamp}  {_size(b.size):>10}  {b.dump.name}{media}\")"),
    ("Restore without --yes", RC, "            if not yes:", "            if False:"),
    ("No safety backup before restore", RC, "            if not no_safety_backup:", "            if False:"),
    ("Restore errors crash", RC, "        except BackupError as exc:", "        except KeyError as exc:"),
    # --- dashboard ---
    ("Backup warning hidden", CV, "    if user.is_staff and backup_overdue():", "    if False:"),
    ("Backup warning for everyone", CV, "    if user.is_staff and backup_overdue():", "    if backup_overdue():"),
]
