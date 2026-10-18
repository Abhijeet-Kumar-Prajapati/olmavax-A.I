"""
Olmavax Agent - System tools
==========================
Control of the Windows machine: apps, volume, power, screen, files,
clipboard, notifications and processes.

Every capability here is declared honestly.  Anything destructive carries a
high ``risk`` value so the security engine asks the owner first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import PATHS, ensure_dirs, get_config
from ..logger import log_warn
from ..security import get_security
from ..utils import (
    human_size,
    normalize_text,
    run_command,
    stamp,
    system_summary,
)
from . import tool

IS_WINDOWS = sys.platform.startswith("win")

# Roots the agent may freely read from and write to.
WORKSPACE = Path.home()


def _roots() -> List[Path]:
    """Directories the agent is allowed to touch."""
    roots = [Path.home(), Path.cwd()]
    try:
        roots.append(PATHS["home"].resolve())
    except OSError:
        pass
    for extra in (Path.home() / "Desktop", Path.home() / "Documents",
                  Path.home() / "Downloads", Path.home() / "Pictures"):
        if extra.exists():
            roots.append(extra)
    return roots


def _guard(path: str) -> Optional[Path]:
    return get_security().safe_target(path, _roots())


def _powershell(script: str, timeout: int = 25) -> tuple:
    """Run a PowerShell snippet invisibly. Returns (code, output)."""
    if not IS_WINDOWS:
        return -1, "PowerShell is only available on Windows"
    cmd = [
        "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", script,
    ]
    code, out, err = run_command(cmd, timeout=timeout)
    return code, (out or err).strip()


# --------------------------------------------------------------------------
# System information
# --------------------------------------------------------------------------


@tool("system.info", "Operating system, CPU, memory and disk summary",
      capabilities=["chat"], risk=0.02, tags=["system", "info"])
def system_info() -> Dict[str, Any]:
    summary = system_summary()
    try:
        code, out = _powershell(
            "(Get-CimInstance Win32_OperatingSystem).Caption + ' | ' + "
            "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1) + ' GB RAM'"
        )
        if code == 0 and out:
            summary["windows"] = out
    except Exception:
        pass
    return summary


@tool("system.which", "Check whether a program is installed and where",
      capabilities=["code.run"], risk=0.10, tags=["system", "probe"])
def which(program: str) -> Dict[str, Any]:
    found = shutil.which(program)
    if found:
        return {"program": program, "installed": True, "path": found}
    return {"program": program, "installed": False, "path": None}


@tool("system.processes", "List running processes, optionally filtered",
      capabilities=["system.control"], risk=0.20, tags=["system", "process"])
def processes(filter_text: str = "", limit: int = 25) -> List[Dict[str, Any]]:
    if IS_WINDOWS:
        code, out = _powershell(
            "Get-Process | Select-Object -First 200 Name,Id,@{n='MB';e={[math]::Round($_.WorkingSet64/1MB,1)}} "
            "| ConvertTo-Json -Compress"
        )
    else:
        code, out = run_command(["ps", "-eo", "pid,comm,rss"], timeout=10)
        out = out.replace("\n", ",")

    rows: List[Dict[str, Any]] = []
    if code == 0 and out:
        import json

        try:
            data = json.loads(out) if out.strip().startswith(("{", "[")) else []
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = str(item.get("Name") or item.get("comm") or "")
                if filter_text and filter_text.lower() not in name.lower():
                    continue
                rows.append(
                    {
                        "name": name,
                        "pid": item.get("Id") or item.get("pid"),
                        "memory_mb": item.get("MB")
                        or round(int(item.get("rss", 0) or 0) / 1024, 1),
                    }
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return rows[: max(1, min(limit, 200))]


@tool("process.kill", "Terminate a running process by name or pid",
      capabilities=["system.control"], risk=0.85, tags=["system", "process"],
      confirm=True)
def kill_process(target: str) -> Dict[str, Any]:
    if not IS_WINDOWS:
        code, out, err = run_command(["pkill", "-f", target], timeout=10)
        return {"ok": code == 0, "detail": out or err}

    if target.isdigit():
        script = f"Stop-Process -Id {int(target)} -Force -ErrorAction Stop; 'killed'"
    else:
        safe = target.replace("'", "''")
        script = (
            f"Get-Process -Name '{safe}' -ErrorAction Stop | "
            f"Stop-Process -Force; 'killed {safe}'"
        )
    code, out = _powershell(script)
    return {"ok": code == 0, "detail": out or "no matching process"}


# --------------------------------------------------------------------------
# Applications and windows
# --------------------------------------------------------------------------


@tool("app.open", "Open a URL, a file or a named application",
      capabilities=["system.control", "net.fetch"], risk=0.30, tags=["system", "apps"])
def open_target(target: str) -> Dict[str, Any]:
    """Launch anything the owner named - a site, a document, a game."""
    if not target:
        return {"ok": False, "error": "nothing to open"}

    if target.startswith(("http://", "https://")):
        import webbrowser

        webbrowser.open(target)
        return {"ok": True, "opened": target, "kind": "url"}

    guarded = _guard(target)
    if guarded and Path(guarded).exists():
        if IS_WINDOWS:
            os.startfile(str(guarded))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(guarded)])
        return {"ok": True, "opened": str(guarded), "kind": "file"}

    from ..utils import fuzzy_match

    known = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "paint": "mspaint.exe",
        "explorer": "explorer.exe",
        "file explorer": "explorer.exe",
        "cmd": "cmd.exe",
        "terminal": "wt.exe",
        "powershell": "powershell.exe",
        "task manager": "taskmgr.exe",
        "settings": "ms-settings:",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "firefox": "firefox.exe",
        "wordpad": "write.exe",
    }
    command = known.get(normalize_text(target)) or fuzzy_match(normalize_text(target), list(known))
    if not command:
        return {"ok": False, "error": f"I do not know how to open '{target}'"}

    if IS_WINDOWS:
        try:
            os.startfile(command)  # type: ignore[attr-defined]
            return {"ok": True, "opened": command, "kind": "app"}
        except OSError:
            pass
    code, _, err = run_command([command], timeout=10)
    return {"ok": code >= 0, "opened": command, "detail": err}


@tool("app.list", "List known applications the agent can launch",
      capabilities=["chat"], risk=0.02, tags=["system", "apps"])
def list_apps() -> List[str]:
    return [
        "notepad", "calculator", "paint", "file explorer", "cmd", "powershell",
        "terminal", "task manager", "settings", "chrome", "edge", "firefox", "wordpad",
    ]


# --------------------------------------------------------------------------
# Volume and sound
# --------------------------------------------------------------------------


def _volume_via_keys(percent: Optional[int] = None, step: Optional[int] = None) -> str:
    """
    Change volume with the multimedia keys.  Works with zero dependencies,
    which is why it is preferred over pycaw when pycaw is not installed.
    """
    import ctypes

    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF
    KEYEVENTF_KEYUP = 0x0002

    def tap(vk: int, times: int = 1) -> None:
        for _ in range(times):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.005)

    if step:
        tap(VK_VOLUME_UP if step > 0 else VK_VOLUME_DOWN, abs(int(step)))
        return f"volume {'up' if step > 0 else 'down'} by {abs(int(step))} steps"
    if percent is not None:
        target = max(0, min(100, int(percent)))
        current = get_volume()
        delta = target - int(current or 0)
        if delta:
            tap(VK_VOLUME_UP if delta > 0 else VK_VOLUME_DOWN, min(100, abs(delta)))
        return f"volume set to {target}%"
    return "no volume change requested"


def get_volume() -> Optional[int]:
    """Current system volume as a percentage, or None if unavailable."""
    try:
        import ctypes
        from ctypes import POINTER, Structure, byref, c_int

        class GUID(Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_byte * 8),
            ]

        class PROPERTYKEY(Structure):
            _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

        interface = ctypes.windll.user32
        try:
            IMMDevice = ctypes.windll.imm32.ImmGetDefaultAudioDevice
            IAudioEndpointVolume = ctypes.windll.volumelle.IAudioEndpointVolume
        except AttributeError:
            return None
        device = IMMDevice(0, 1, None)
        endpoint = device.Activate(POINTER(IAudioEndpointVolume), 0, None, None)
        value = c_int()
        endpoint.GetMasterVolumeLevelScalar(byref(value))
        return int(round(value.value * 100))
    except Exception:
        return None


@tool("volume.set", "Set system volume to a percentage (0-100)",
      capabilities=["system.control"], risk=0.15, tags=["system", "audio"])
def volume_set(percent: int = 50) -> Dict[str, Any]:
    if not IS_WINDOWS:
        return {"ok": False, "error": "volume control is implemented for Windows"}
    detail = _volume_via_keys(percent=int(percent))
    return {"ok": True, "detail": detail, "volume": get_volume()}


@tool("volume.up", "Turn volume up by a number of steps (default 5)",
      capabilities=["system.control"], risk=0.10, tags=["system", "audio"])
def volume_up(steps: int = 5) -> Dict[str, Any]:
    if not IS_WINDOWS:
        return {"ok": False, "error": "volume control is implemented for Windows"}
    return {"ok": True, "detail": _volume_via_keys(step=steps), "volume": get_volume()}


@tool("volume.down", "Turn volume down by a number of steps (default 5)",
      capabilities=["system.control"], risk=0.10, tags=["system", "audio"])
def volume_down(steps: int = 5) -> Dict[str, Any]:
    if not IS_WINDOWS:
        return {"ok": False, "error": "volume control is implemented for Windows"}
    return {"ok": True, "detail": _volume_via_keys(step=-abs(steps)), "volume": get_volume()}


@tool("volume.mute", "Toggle mute", capabilities=["system.control"],
      risk=0.10, tags=["system", "audio"])
def volume_mute() -> Dict[str, Any]:
    if not IS_WINDOWS:
        return {"ok": False, "error": "volume control is implemented for Windows"}
    import ctypes

    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xAD, 0, 0x0002, 0)
    return {"ok": True, "detail": "mute toggled"}


# --------------------------------------------------------------------------
# Power
# --------------------------------------------------------------------------


@tool("power.lock", "Lock the computer screen", capabilities=["system.control"],
      risk=0.25, tags=["system", "power"])
def power_lock() -> Dict[str, Any]:
    code, out = _powershell("rundll32.exe user32.dll,LockWorkStation; 'locked'")
    return {"ok": code == 0, "detail": out}


@tool("power.sleep", "Put the computer to sleep",
      capabilities=["system.control"], risk=0.60, tags=["system", "power"], confirm=True)
def power_sleep() -> Dict[str, Any]:
    code, out = _powershell("rundll32.exe powrprof.dll,SetSuspendState 0,1,0; 'sleeping'")
    return {"ok": code == 0, "detail": out}


@tool("power.shutdown", "Shut the computer down",
      capabilities=["system.control"], risk=0.92, tags=["system", "power"], confirm=True)
def power_shutdown(delay: int = 20) -> Dict[str, Any]:
    code, out = _powershell(f"shutdown /s /t {int(delay)}; 'shutdown in {delay}s - abort with shutdown /a'")
    return {"ok": code == 0, "detail": out}


@tool("power.restart", "Restart the computer",
      capabilities=["system.control"], risk=0.88, tags=["system", "power"], confirm=True)
def power_restart(delay: int = 20) -> Dict[str, Any]:
    code, out = _powershell(f"shutdown /r /t {int(delay)}; 'restarting in {delay}s'")
    return {"ok": code == 0, "detail": out}


# --------------------------------------------------------------------------
# Screen
# --------------------------------------------------------------------------


@tool("screen.screenshot", "Capture the screen to an image file",
      capabilities=["screen.read", "files.write"], risk=0.65, tags=["screen", "media"])
def screenshot(name: str = "screen") -> Dict[str, Any]:
    ensure_dirs()
    target = PATHS["exports"] / f"{name}-{int(time.time())}.png"
    target.parent.mkdir(parents=True, exist_ok=True)

    try:  # Pillow gives the best result when available
        from PIL import ImageGrab

        ImageGrab.grab().save(str(target))
        return {"ok": True, "path": str(target), "method": "pillow"}
    except ImportError:
        pass

    code, out = _powershell(
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
        "$g=[System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
        f"$bmp.Save('{target}'); 'saved'"
    )
    return {"ok": code == 0, "path": str(target), "method": "powershell", "detail": out}


@tool("screen.brightness", "Set screen brightness 0-100",
      capabilities=["system.control"], risk=0.20, tags=["screen"])
def brightness(percent: int = 60) -> Dict[str, Any]:
    code, out = _powershell(
        "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,"
        f"{max(0, min(100, int(percent)))})"
    )
    return {"ok": code == 0, "detail": out}


# --------------------------------------------------------------------------
# Clipboard and notifications
# --------------------------------------------------------------------------


@tool("clipboard.read", "Read the text currently on the clipboard",
      capabilities=["screen.read"], risk=0.55, tags=["system", "clipboard"])
def clipboard_read() -> str:
    code, out = _powershell("Get-Clipboard -Raw")
    return out if code == 0 else ""


@tool("clipboard.write", "Put text on the clipboard",
      capabilities=["screen.read", "files.write"], risk=0.45, tags=["system", "clipboard"])
def clipboard_write(text: str) -> Dict[str, Any]:
    escaped = text.replace("'", "''")
    code, out = _powershell(f"Set-Clipboard -Value '{escaped}'; 'copied'")
    return {"ok": code == 0, "detail": out, "chars": len(text)}


@tool("notify.send", "Show a Windows notification",
      capabilities=["system.control"], risk=0.10, tags=["system", "notify"])
def notify(title: str = "Olmavax Agent", message: str = "", sound: bool = True) -> Dict[str, Any]:
    safe_title = title.replace('"', "'")[:60]
    safe_msg = message.replace('"', "'")[:240]
    code, out = _powershell(
        "[reflection.assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
        "$n=New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; "
        f"$n.ShowBalloonTip(6000,'{safe_title}','{safe_msg}',"
        + ("[System.Windows.Forms.ToolTipIcon]::Info" if sound else
           "[System.Windows.Forms.ToolTipIcon]::None")
        + "); 'shown'"
    )
    if code != 0 or not out:
        log_warn("toast failed, falling back to console message", "notify")
        print(f"[NOTIFY] {title}: {message}")
    return {"ok": code == 0, "detail": out}


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


@tool("files.list", "List the contents of a folder",
      capabilities=["files.read"], risk=0.15, tags=["files"])
def files_list(path: str = ".", limit: int = 100) -> Dict[str, Any]:
    guarded = _guard(path)
    if not guarded:
        return {"ok": False, "error": f"path is outside the allowed areas: {path}"}
    if not Path(guarded).is_dir():
        return {"ok": False, "error": "not a folder"}
    entries = []
    try:
        for item in sorted(Path(guarded).iterdir(), key=lambda p: p.name.lower())[: max(1, limit)]:
            try:
                size = item.stat().st_size if item.is_file() else 0
            except OSError:
                size = 0
            entries.append(
                {
                    "name": item.name,
                    "type": "folder" if item.is_dir() else "file",
                    "size": human_size(size) if size else "",
                    "modified": stamp(time.time() - item.stat().st_mtime) if item.exists() else "",
                }
            )
    except PermissionError:
        return {"ok": False, "error": "permission denied"}
    return {"ok": True, "path": str(guarded), "count": len(entries), "entries": entries}


@tool("files.read", "Read a text file",
      capabilities=["files.read"], risk=0.20, tags=["files"])
def files_read(path: str, max_chars: int = 40000) -> Dict[str, Any]:
    guarded = _guard(path)
    if not guarded:
        return {"ok": False, "error": f"path is outside the allowed areas: {path}"}
    target = Path(guarded)
    if not target.is_file():
        return {"ok": False, "error": "file not found"}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return {"ok": False, "error": "permission denied"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "path": str(target),
        "chars": len(text),
        "truncated": len(text) > max_chars,
        "content": text[:max_chars],
    }


@tool("files.write", "Create or overwrite a text file",
      capabilities=["files.write"], risk=0.45, tags=["files"])
def files_write(path: str, content: str, append: bool = False) -> Dict[str, Any]:
    guarded = _guard(path)
    if not guarded:
        return {"ok": False, "error": f"path is outside the allowed areas: {path}"}
    target = Path(guarded)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(target), "bytes_written": len(content.encode("utf-8"))}


@tool("files.search", "Find files by name pattern across your folders",
      capabilities=["files.read"], risk=0.25, tags=["files"])
def files_search(pattern: str, root: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    import fnmatch

    roots = _roots()
    if root:
        guarded = _guard(root)
        roots = [Path(guarded)] if guarded else []
    results: List[Dict[str, Any]] = []
    needle = pattern.lower().strip("*")
    for base in roots:
        for dirpath, dirnames, filenames in os.walk(str(base)):
            dirnames[:] = [
                d for d in dirnames
                if d not in {"node_modules", ".git", ".venv", "venv", "AppData",
                             "__pycache__", "WindowsApps", "$Recycle.Bin"}
            ]
            for filename in filenames:
                if needle in filename.lower() or fnmatch.fnmatch(filename.lower(), pattern.lower()):
                    results.append({"name": filename, "path": os.path.join(dirpath, filename)})
                    if len(results) >= limit:
                        return results
    return results


@tool("files.delete", "Move a file to the recycle bin (never hard-deletes)",
      capabilities=["files.delete"], risk=0.85, tags=["files"], confirm=True)
def files_delete(path: str) -> Dict[str, Any]:
    """
    Deletion always goes to the Recycle Bin so it can be undone.

    A true permanent delete is deliberately not implemented as a tool.
    """
    guarded = _guard(path)
    if not guarded:
        return {"ok": False, "error": f"path is outside the allowed areas: {path}"}
    target = Path(guarded)
    if not target.exists():
        return {"ok": False, "error": "file not found"}

    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 0x0003
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_NOERRORUI = 0x0400
        FOF_SILENT = 0x0004
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = str(target) + "\x00\x00"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return {"ok": code == 0, "method": "recycle bin", "path": str(target)}

    trash = Path.home() / ".local" / "share" / "Trash" / "files"
    trash.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(trash / target.name))
    return {"ok": True, "method": "trash", "path": str(target)}