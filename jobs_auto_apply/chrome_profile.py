from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from .config import AppConfig


def default_chrome_user_data_root() -> Path:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library/Application Support/Google/Chrome"
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        return Path(local) / "Google" / "Chrome" / "User Data"
    return home / ".config" / "google-chrome"


def _is_profile_directory(path: Path) -> bool:
    return path.is_dir() and (path / "Preferences").exists()


def _is_dedicated_profile_dir(path: Path) -> bool:
    """True when ``path`` is a Playwright-only user-data dir, not the real Chrome root.

    Anything under the system Chrome "User Data" folder is the user's own browser;
    anything else is a dedicated automation profile that we own and may create.
    """
    try:
        path = path.resolve()
        return default_chrome_user_data_root().resolve() not in path.parents
    except OSError:
        return True


def resolve_chrome_profile_dir(config: AppConfig) -> Path:
    """Resolve the user-data directory to pass to launch_persistent_context.

    Two supported shapes for ``browser.chrome_user_data_dir``:
      * a dedicated automation profile (default) — created on first run and reused;
      * the real Chrome "User Data" root (has ``Local State``) — then
        ``chrome_profile_name`` picks the profile folder inside it.
    """
    custom = config.browser.chrome_user_data_dir.strip()
    profile_name = config.browser.chrome_profile_name.strip() or "Default"

    if custom:
        base = Path(custom).expanduser()
        if not base.is_absolute():
            base = (config.base_dir / base).resolve()
        else:
            base = base.resolve()

        # Pointed straight at a profile folder (contains Preferences).
        if _is_profile_directory(base):
            return base

        # Pointed at the *system* Chrome "User Data" root — pick the named profile.
        # Path equality (not a "Local State" probe) is deliberate: a dedicated
        # profile dir also grows a "Local State" + "Default" once Chrome populates
        # it, so probing would resolve one level too deep and silently fork the
        # profile, losing every saved login.
        try:
            is_system_root = base == default_chrome_user_data_root().resolve()
        except OSError:
            is_system_root = False
        if is_system_root:
            candidate = base / profile_name
            if _is_profile_directory(candidate):
                return candidate
            raise FileNotFoundError(
                f"Chrome profile not found at {candidate}. "
                "Set browser.chrome_profile_name (Default, 'Profile 1', ...) "
                "or point browser.chrome_user_data_dir at a dedicated folder."
            )

        # Dedicated automation profile — create it and let Chrome populate it.
        base.mkdir(parents=True, exist_ok=True)
        return base

    root = default_chrome_user_data_root()
    candidate = root / profile_name
    if not _is_profile_directory(candidate):
        raise FileNotFoundError(
            f"Chrome profile not found: {candidate}\n"
            f"Set browser.chrome_profile_name (e.g. Default, 'Profile 1') or "
            f"browser.chrome_user_data_dir in config.yaml."
        )
    return candidate


class ChromeProfileLockedError(RuntimeError):
    """Raised when Chrome is still running and has the profile locked.

    A subclass of ``RuntimeError`` so existing ``except Exception`` handlers keep
    working, while callers (e.g. the scheduler) can detect this specific case and
    retry quickly once Chrome is closed instead of waiting a full interval.
    """


# Module-level flag so the scheduler can tell whether a just-finished apply cycle
# was wasted purely because Chrome's profile was locked. Reset at the start of a
# run, set whenever ``assert_chrome_profile_available`` raises.
_chrome_lock_detected = False


def reset_chrome_lock_flag() -> None:
    global _chrome_lock_detected
    _chrome_lock_detected = False


def chrome_lock_was_detected() -> bool:
    return _chrome_lock_detected


def chrome_profile_lock_path(profile_dir: Path) -> Path:
    """SingletonLock sits inside a user-data dir, or beside a profile folder."""
    inside = profile_dir / "SingletonLock"
    if inside.exists() or inside.is_symlink():
        return inside
    return profile_dir.parent / "SingletonLock"


def is_chrome_profile_locked(profile_dir: Path) -> bool:
    lock = chrome_profile_lock_path(profile_dir)
    return lock.exists() or lock.is_symlink()


def is_chrome_process_running() -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(
                ["pgrep", "-x", "Google Chrome"],
                capture_output=True,
                check=False,
            )
            return result.returncode == 0
        if system == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                capture_output=True,
                text=True,
                check=False,
            )
            return "chrome.exe" in result.stdout.lower()
        result = subprocess.run(
            ["pgrep", "-x", "chrome"],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def uses_dedicated_profile(config: AppConfig) -> bool:
    """True when the browser uses an automation-owned profile dir."""
    return _is_dedicated_profile_dir(resolve_chrome_profile_dir(config))


def assert_chrome_profile_available(profile_dir: Path) -> None:
    global _chrome_lock_detected

    if not profile_dir.exists():
        raise FileNotFoundError(f"Chrome profile directory does not exist: {profile_dir}")

    # A dedicated automation profile is independent of the user's own Chrome, so
    # an open Chrome window is irrelevant — only its own lock file matters.
    if _is_dedicated_profile_dir(profile_dir):
        if is_chrome_profile_locked(profile_dir):
            _chrome_lock_detected = True
            raise ChromeProfileLockedError(
                f"The automation profile is already in use: {profile_dir}\n"
                "Close the other automation browser window and retry."
            )
        return

    if is_chrome_process_running() or is_chrome_profile_locked(profile_dir):
        _chrome_lock_detected = True
        raise ChromeProfileLockedError(
            "Google Chrome is still running. Quit Chrome completely before running the script "
            "(Chrome locks its profile while open).\n"
            "  macOS: Cmd+Q Chrome, or run: osascript -e 'quit app \"Google Chrome\"'"
        )


def list_chrome_profiles() -> list[tuple[str, Path]]:
    root = default_chrome_user_data_root()
    if not root.exists():
        return []
    profiles: list[tuple[str, Path]] = []
    local_state = root / "Local State"
    if local_state.exists():
        import json

        try:
            data = json.loads(local_state.read_text(encoding="utf-8"))
            info_cache = data.get("profile", {}).get("info_cache", {})
            for folder, meta in info_cache.items():
                path = root / folder
                if _is_profile_directory(path):
                    name = str(meta.get("name", folder))
                    profiles.append((f"{name} ({folder})", path))
        except Exception:
            pass
    if not profiles:
        for path in sorted(root.iterdir()):
            if _is_profile_directory(path):
                profiles.append((path.name, path))
    return profiles
