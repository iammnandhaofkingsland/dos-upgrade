"""Compare two copies of the DOS project file by file, so you know nothing is missing or different.

Usage (from any folder):
    python tools/compare_tree.py <reference folder> <your project folder>
Example:
    python C:\\dos-work\\complete\\dos\\tools\\compare_tree.py C:\\dos-work\\complete\\dos C:\\Users\\User\\Desktop\\DOS_Buildathon\\dos

It ignores what is personal or generated: .git, .venv, __pycache__, .pytest_cache, server/.env, docs/screenshots.
Line endings are ignored too (Windows CRLF and Linux LF count as the same), so only real content differences show.
It prints MISSING (in the reference, not in your project), DIFFERENT (content differs) and EXTRA (only in yours),
then a one-line verdict. It changes nothing."""
import hashlib
import pathlib
import sys

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".adk", "node_modules"}
SKIP_FILES = {"server/.env", "PACKAGE_README.txt"}
SKIP_PREFIXES = ("docs/screenshots/",)


def files(root: pathlib.Path) -> dict[str, str]:
    out = {}
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        rel = p.relative_to(root).as_posix()
        if rel in SKIP_FILES or rel.startswith(SKIP_PREFIXES) or rel.endswith(".pyc"):
            continue
        data = p.read_bytes().replace(b"\r\n", b"\n")
        out[rel] = hashlib.sha256(data).hexdigest()
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    ref, mine = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
    a, b = files(ref), files(mine)
    missing = sorted(set(a) - set(b))
    different = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    extra = sorted(set(b) - set(a))
    for k in missing:
        print("MISSING    ", k)
    for k in different:
        print("DIFFERENT  ", k)
    for k in extra:
        print("EXTRA      ", k)
    print(f"\n{len(a)} files in the reference: {len(a) - len(missing) - len(different)} identical, {len(missing)} missing, "
          f"{len(different)} different; {len(extra)} extra in your project.")
    print("VERDICT: your project matches the complete package." if not missing and not different
          else "VERDICT: fix the MISSING and DIFFERENT files above (Procedure U2 or U3), then run this again.")
    return 0 if not missing and not different else 1


if __name__ == "__main__":
    sys.exit(main())
