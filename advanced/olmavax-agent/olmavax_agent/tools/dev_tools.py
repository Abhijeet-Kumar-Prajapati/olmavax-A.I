"""
Olmavax Agent - Developer tools
=============================
Write, run, test and explain code in several languages.

Execution rules, applied to every language:

* a fresh process per run, so one crash cannot take the agent with it
* a wall clock timeout
* output capped in size
* a deliberately minimal environment - no inherited secrets
* the resolved script path must sit inside an allowed workspace

Supported out of the box: Python, JavaScript (Node), and - if the compiler
happens to be installed - C, Java and TypeScript.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import PATHS, ensure_dirs, get_config
from ..logger import log_warn
from ..security import get_security
from ..utils import run_command, truncate
from . import tool

SEC = get_security()

# Languages the agent knows how to run, and how to invoke them.
LANGUAGES: Dict[str, Dict[str, Any]] = {
    "python": {
        "ext": ".py",
        "runtime": ["py", "-3"],
        "alt": ["python", "-3"],
        "comment": "#",
        "available": True,
    },
    "javascript": {
        "ext": ".js",
        "runtime": ["node"],
        "alt": ["nodejs"],
        "comment": "//",
        "available": shutil.which("node") is not None,
    },
    "typescript": {
        "ext": ".ts",
        "runtime": ["npx", "-y", "tsx"],
        "comment": "//",
        "available": shutil.which("npx") is not None,
    },
    "c": {
        "ext": ".c",
        "runtime": ["gcc"],
        "comment": "//",
        "compile": True,
        "available": shutil.which("gcc") is not None
        or shutil.which("clang") is not None,
    },
    "java": {
        "ext": ".java",
        "runtime": ["java"],
        "comment": "//",
        "compile": True,
        "available": shutil.which("javac") is not None,
    },
    "batch": {
        "ext": ".bat",
        "runtime": ["cmd", "/c"],
        "comment": "::",
        "available": sys.platform.startswith("win"),
    },
    "powershell": {
        "ext": ".ps1",
        "runtime": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"],
        "comment": "#",
        "available": sys.platform.startswith("win"),
    },
}

ALIASES = {
    "py": "python", "python3": "python", "js": "javascript", "node": "javascript",
    "ts": "typescript", "c++": "c", "cpp": "c", "cplusplus": "c",
    "ps1": "powershell", "ps": "powershell", "sh": "batch", "cmd": "batch",
    "bat": "batch", "shell": "batch",
}


def resolve_language(name: str) -> str:
    key = (name or "python").strip().lower()
    return ALIASES.get(key, key)


def _workspace() -> Path:
    ensure_dirs()
    folder = PATHS["exports"] / "code"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _sandbox_env() -> Dict[str, str]:
    """Environment handed to every child process."""
    from ..security import _sandbox_environment

    cfg = get_config()
    return _sandbox_environment(cfg.security)


def _pick_runtime(spec: Dict[str, Any]) -> Optional[List[str]]:
    for candidate in (spec.get("runtime", []), spec.get("alt", [])):
        if candidate and shutil.which(candidate[0]):
            return candidate
    return None


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


@tool("dev.languages", "List programming languages the machine can run",
      capabilities=["chat"], risk=0.02, tags=["dev"])
def dev_languages() -> List[Dict[str, Any]]:
    out = []
    for name, spec in LANGUAGES.items():
        runtime = _pick_runtime(spec)
        out.append(
            {
                "language": name,
                "extension": spec["ext"],
                "ready": runtime is not None,
                "runtime": " ".join(runtime) if runtime else "not installed",
            }
        )
    return out


# --------------------------------------------------------------------------
# Running code
# --------------------------------------------------------------------------


@tool("dev.run", "Write and run a program in any supported language",
      capabilities=["code.run", "files.write"], risk=0.30, tags=["dev", "code", "run"],
      confirm=True)
def dev_run(
    code: str,
    language: str = "python",
    stdin: str = "",
    save_as: str = "",
    timeout: int = 0,
) -> Dict[str, Any]:
    """
    Execute a snippet and return stdout, stderr, exit code and timing.

    The code is written into the agent's own exports folder first, so every
    run is inspectable afterwards and nothing touches your real projects.
    """
    lang = resolve_language(language)
    spec = LANGUAGES.get(lang)
    if not spec:
        return {"ok": False, "error": f"language '{language}' is not supported",
                "supported": list(LANGUAGES)}

    runtime = _pick_runtime(spec)
    if runtime is None:
        return {"ok": False, "error": f"{lang} runtime is not installed on this machine"}

    cfg = get_config()
    limit = int(timeout) or cfg.security.process_timeout_seconds
    limit = max(3, min(limit, 300))
    capped_code = code[: cfg.security.max_output_chars]
    capped_input = (stdin or "")[: cfg.security.max_input_chars]

    folder = _workspace()
    stem = save_as or f"run-{int(time.time() * 1000)}"
    stem = "".join(ch for ch in stem if ch.isalnum() or ch in "-_")[:60] or "run"
    source = folder / f"{stem}{spec['ext']}"
    try:
        source.write_text(capped_code, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"could not write the source file: {exc}"}

    command = list(runtime)
    try:
        if lang == "python":
            command = [sys.executable, str(source)]
        elif lang == "typescript":
            command = command + [str(source)]
        else:
            command = command + [str(source)]

        if spec.get("compile"):
            binary = folder / f"{stem}.bin"
            compile_cmd = (
                ([runtime[0], str(source), "-o", str(binary)])
                if lang == "c"
                else ([runtime[0], str(source), "-d", str(folder)])
            )
            ccode, cout, cerr = run_command(
                compile_cmd, timeout=limit, cwd=str(folder), input_text=capped_input
            )
            if ccode != 0:
                return {
                    "ok": False,
                    "stage": "compile",
                    "error": truncate(cerr or cout, 3000),
                    "exit_code": ccode,
                }
            command = [str(binary)] if lang == "c" else ["java", "-cp", str(folder), stem]

        started = time.perf_counter()
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            input=capped_input or None,
            timeout=limit,
            cwd=str(folder),
            env=_sandbox_env(),
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform.startswith("win")
            else 0,
        )
        duration = time.perf_counter() - started
        stdout = (completed.stdout or "")[: cfg.security.max_output_chars]
        stderr = (completed.stderr or "")[: cfg.security.max_output_chars]
        return {
            "ok": completed.returncode == 0,
            "language": lang,
            "file": str(source),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_s": round(duration, 3),
            "lines": len(stdout.splitlines()),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {limit}s", "language": lang,
                "file": str(source)}
    except FileNotFoundError as exc:
        return {"ok": False, "error": f"runtime missing: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@tool("dev.run_file", "Run a code file that already exists on disk",
      capabilities=["code.run"], risk=0.42, tags=["dev", "code", "run"], confirm=True)
def dev_run_file(path: str, language: str = "", timeout: int = 0) -> Dict[str, Any]:
    guarded = SEC.safe_target(path, [Path.home(), PATHS["home"], Path.cwd()])
    if not guarded:
        return {"ok": False, "error": "path is outside the allowed workspace"}
    target = Path(guarded)
    if not target.is_file():
        return {"ok": False, "error": "file not found"}
    lang = resolve_language(language or target.suffix.lstrip(".") or "python")
    try:
        code = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return dev_run(code=code, language=lang, save_as=target.stem)


# --------------------------------------------------------------------------
# Checking code
# --------------------------------------------------------------------------


@tool("dev.lint", "Syntax check code without running it",
      capabilities=["code.run"], risk=0.25, tags=["dev", "code", "check"])
def dev_lint(code: str, language: str = "python") -> Dict[str, Any]:
    lang = resolve_language(language)
    if lang == "python":
        try:
            compile(code, "<snippet>", "exec")
            return {"ok": True, "language": "python", "verdict": "syntax is valid",
                    "lines": len(code.splitlines())}
        except SyntaxError as exc:
            return {
                "ok": False,
                "language": "python",
                "verdict": "syntax error",
                "line": exc.lineno,
                "message": exc.msg,
                "offset": exc.offset,
            }
    if lang == "javascript":
        folder = _workspace()
        probe = folder / "lint-probe.js"
        probe.write_text(code, encoding="utf-8")
        code_rc, out, err = run_command(["node", "--check", str(probe)], timeout=20)
        return {
            "ok": code_rc == 0,
            "language": "javascript",
            "verdict": "syntax is valid" if code_rc == 0 else "syntax error",
            "detail": truncate(err or out, 1500),
        }
    return {"ok": False, "error": f"no linter available for {lang}"}


@tool("dev.inspect", "Explain the structure of a program",
      capabilities=["chat"], risk=0.10, tags=["dev", "code", "explain"])
def dev_inspect(code: str, language: str = "python") -> Dict[str, Any]:
    """
    Static analysis with the standard library only: what is defined, what is
    imported, and where the riskiest lines are.
    """
    lang = resolve_language(language)
    if lang != "python":
        return {
            "ok": True,
            "language": lang,
            "functions": len(re.findall(r"function\s+\w+", code)),
            "lines": len(code.splitlines()),
            "note": "structural inspection is deepest for Python",
        }

    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"ok": False, "error": f"line {exc.lineno}: {exc.msg}"}

    functions = [
        {
            "name": node.name,
            "line": node.lineno,
            "args": [a.arg for a in node.args.args],
            "async": isinstance(node, ast.AsyncFunctionDef),
        }
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    classes = [
        {"name": node.name, "line": node.lineno, "methods": [
            n.name for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]}
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    imports: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    risky = []
    for number, line in enumerate(code.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for marker, label in (
            ("eval(", "dynamic eval"),
            ("exec(", "dynamic exec"),
            ("subprocess", "spawns a process"),
            ("os.system", "shell command"),
            ("pickle.loads", "unsafe deserialisation"),
            ("shell=True", "shell injection risk"),
            ("__import__", "dynamic import"),
        ):
            if marker in line:
                risky.append({"line": number, "issue": label, "code": truncate(stripped, 80)})

    complexity = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try,
                             ast.BoolOp, ast.IfExp, ast.comprehension))
    )
    return {
        "ok": True,
        "language": "python",
        "lines": len(code.splitlines()),
        "functions": functions,
        "classes": classes,
        "imports": sorted(set(imports)),
        "risk_points": risky,
        "branching_complexity": complexity,
        "verdict": "clean" if not risky else f"{len(risky)} point(s) worth reviewing",
    }


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


@tool("dev.test", "Run a test suite file and report pass/fail",
      capabilities=["code.run"], risk=0.30, tags=["dev", "test"], confirm=True)
def dev_test(path: str = "", language: str = "python") -> Dict[str, Any]:
    """
    Run tests.  With no path, the agent's own suite is executed, which is
    how ``olmavax_agent test`` stays honest.
    """
    if not path:
        root = Path(__file__).resolve().parent.parent.parent
        candidate = root / "tests" / "test_core.py"
        if candidate.exists():
            path = str(candidate)
        else:
            return {"ok": False, "error": "no test path given and no default suite found"}

    guarded = SEC.safe_target(path, [Path.home(), PATHS["home"], Path.cwd()])
    if not guarded:
        return {"ok": False, "error": "test path is outside the allowed workspace"}
    target = Path(guarded)
    if not target.is_file():
        return {"ok": False, "error": "test file not found"}

    lang = resolve_language(language or target.suffix.lstrip(".") or "python")
    if lang == "python":
        code_rc, out, err = run_command(
            [sys.executable, "-m", "unittest", "-v", target.name],
            timeout=180,
            cwd=str(target.parent),
        )
    else:
        code_rc, out, err = run_command(["node", str(target)], timeout=120,
                                       cwd=str(target.parent))
    combined = (out or "") + (("\n" + err) if err else "")
    return {
        "ok": code_rc == 0,
        "file": str(target),
        "exit_code": code_rc,
        "passed": "OK" in combined,
        "summary": _test_summary(combined),
        "output": truncate(combined, 6000),
    }


def _test_summary(output: str) -> str:
    import re

    match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
    if not match:
        return truncate(output.strip().splitlines()[-1] if output.strip() else "", 200)
    failures = re.search(r"failures=(\d+)", output)
    errors = re.search(r"errors=(\d+)", output)
    return (
        f"{match.group(1)} tests in {match.group(2)}s, "
        f"{failures.group(1) if failures else 0} failures, "
        f"{errors.group(1) if errors else 0} errors"
    )


# --------------------------------------------------------------------------
# Project scaffolding
# --------------------------------------------------------------------------


@tool("dev.scaffold", "Create a new project folder with sensible starter files",
      capabilities=["files.write"], risk=0.35, tags=["dev", "project"])
def dev_scaffold(name: str, language: str = "python") -> Dict[str, Any]:
    lang = resolve_language(language)
    spec = LANGUAGES.get(lang)
    if not spec:
        return {"ok": False, "error": f"unsupported language '{language}'"}

    root = SEC.safe_target(str(Path.home() / "Projects" / name), [Path.home()])
    if not root:
        return {"ok": False, "error": "project name did not resolve to a safe path"}
    project = Path(root)
    if project.exists() and any(project.iterdir()):
        return {"ok": False, "error": "that folder already has files in it"}

    (project / "src").mkdir(parents=True, exist_ok=True)
    created = []

    readme = project / "README.md"
    readme.write_text(
        f"# {name}\n\nCreated by Olmavax Agent on "
        f"{time.strftime('%Y-%m-%d %H:%M')}\n\nLanguage: {lang}\n",
        encoding="utf-8",
    )
    created.append("README.md")

    if lang == "python":
        (project / "src" / "main.py").write_text(
            'def main() -> None:\n    print("hello from %s")\n\n\n'
            'if __name__ == "__main__":\n    main()\n' % name,
            encoding="utf-8",
        )
        (project / "tests").mkdir(exist_ok=True)
        (project / "tests" / "test_main.py").write_text(
            "import unittest\n\n\nclass TestMain(unittest.TestCase):\n"
            "    def test_import(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (project / "requirements.txt").write_text("", encoding="utf-8")
        created += ["src/main.py", "tests/test_main.py", "requirements.txt"]
    elif lang in {"javascript", "typescript"}:
        (project / "src" / "index.js").write_text(
            'console.log("hello from %s");\n' % name, encoding="utf-8"
        )
        (project / "package.json").write_text(
            '{\n  "name": "%s",\n  "version": "1.0.0",\n  "type": "module",\n'
            '  "scripts": { "start": "node src/index.js" }\n}\n' % name.lower(),
            encoding="utf-8",
        )
        created += ["src/index.js", "package.json"]
    else:
        (project / "src" / f"main{spec['ext']}").write_text(
            f"// {name}\nint main() {{ return 0; }}\n", encoding="utf-8"
        )
        created.append(f"src/main{spec['ext']}")

    return {"ok": True, "path": str(project), "language": lang, "created": created}