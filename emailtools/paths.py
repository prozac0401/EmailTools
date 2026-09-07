from pathlib import Path
import re

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str | None, fallback: str = "attachment") -> str:
    if not name:
        name = fallback
    # Attachment names are untrusted.  Drop both POSIX and Windows path
    # components before applying the Windows filename character rules.
    # Path(name).name alone is not sufficient when this code is tested or run
    # on a platform whose native separator differs from the supplied name.
    name = re.split(r"[\\/]+", name)[-1] or fallback
    name = INVALID_FILENAME_CHARS.sub("_", name)
    name = name.strip().rstrip(".")
    if name in {"", ".", ".."}:
        name = fallback
    # Avoid Windows reserved device names.
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    stem = name.split(".", 1)[0].rstrip(" .").upper()
    if stem in reserved:
        name = "_" + name
    return name[:240]


def safe_attachment_path(directory: Path, name: str | None, fallback: str) -> Path:
    """Return a unique direct child of *directory* for an untrusted name."""
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_path(directory / safe_name(name, fallback))
    if target.resolve().parent != directory.resolve():
        raise ValueError("첨부파일 저장 경로가 출력 폴더를 벗어났습니다.")
    return target


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10000):
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"동일 이름 파일이 너무 많습니다: {path}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig", errors="replace")
