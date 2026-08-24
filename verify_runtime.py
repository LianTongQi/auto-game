import argparse
import hashlib
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MANIFEST_FILE = BASE_DIR / "runtime_manifest.json"
REQUIREMENTS_FILE = BASE_DIR / "requirements.txt"
RUNTIME_DIR = BASE_DIR / "runtime" / "python"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_requirements(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise RuntimeError(f"Dependency is not pinned: {line}")
        name, wanted = line.split("==", 1)
        expected[name.strip()] = wanted.strip()
    return expected


def verify() -> list[str]:
    errors: list[str] = []
    if not MANIFEST_FILE.is_file():
        return [f"Missing manifest: {MANIFEST_FILE}"]
    if not REQUIREMENTS_FILE.is_file():
        return [f"Missing requirements: {REQUIREMENTS_FILE}"]

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8-sig"))
    expected_python = manifest["python"]["version"]
    actual_python = ".".join(str(item) for item in sys.version_info[:3])
    if actual_python != expected_python:
        errors.append(f"Python version mismatch: expected {expected_python}, got {actual_python}")
    if sys.maxsize <= 2**32:
        errors.append("The bundled Python runtime is not 64-bit")

    actual_executable_dir = Path(sys.executable).resolve().parent
    if actual_executable_dir != RUNTIME_DIR.resolve():
        errors.append(f"TimedLauncher is not using its bundled Python: {sys.executable}")

    expected_requirements_hash = manifest["requirements_sha256"].lower()
    actual_requirements_hash = sha256(REQUIREMENTS_FILE)
    if actual_requirements_hash != expected_requirements_hash:
        errors.append("requirements.txt does not match runtime_manifest.json")

    try:
        expected_packages = load_requirements(REQUIREMENTS_FILE)
    except Exception as exc:
        errors.append(str(exc))
        expected_packages = {}

    for name, wanted in expected_packages.items():
        try:
            installed = version(name)
        except PackageNotFoundError:
            errors.append(f"Missing dependency: {name}=={wanted}")
            continue
        if installed != wanted:
            errors.append(f"Dependency mismatch: {name} expected {wanted}, got {installed}")

    try:
        import psutil  # noqa: F401
        import pyautogui  # noqa: F401
        import pygetwindow  # noqa: F401
        import tkinter

        interpreter = tkinter.Tcl()
        interpreter.eval("info patchlevel")
    except Exception as exc:
        errors.append(f"Runtime import test failed: {exc}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the bundled TimedLauncher runtime")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    errors = verify()
    if errors:
        for error in errors:
            print(f"RUNTIME_ERROR: {error}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"RUNTIME_OK Python {sys.version.split()[0]} at {sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
