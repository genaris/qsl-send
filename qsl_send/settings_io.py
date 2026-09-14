"""Write individual settings back to the YAML file without disturbing it.

A YAML load/dump round-trip discards every comment, and this project's config
is heavily commented — Gmail setup instructions, the placeholder reference, the
field-box notes. Those comments are the documentation a colleague reads when
something goes wrong, so losing them is not acceptable.

Instead, only the lines whose values actually changed are rewritten. Every
other byte of the file, comments and blank-line spacing included, is left
exactly as it was.

Paths are given in dotted form, matching the YAML nesting:

    my_callsign            -> top-level key
    smtp.from_address      -> key `from_address` under `smtp:`
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# A `key: value` line, capturing indent, key and any trailing comment.
_KEY_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:(?P<rest>.*)$"
)
_ENV_REF = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


class SettingsWriteError(Exception):
    """The file could not be updated safely."""


def _split_comment(rest: str) -> tuple[str, str]:
    """Separate a value from its trailing ` # comment`, respecting quotes."""
    in_single = in_double = False
    for i, ch in enumerate(rest):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            # Only a comment when preceded by whitespace (or at the start).
            if i == 0 or rest[i - 1].isspace():
                return rest[:i].rstrip(), rest[i:]
    return rest.rstrip(), ""


def _format(value: Any) -> str:
    """Render a Python value as YAML scalar text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    # Quote when the value could otherwise be misread as another YAML type,
    # or contains characters with meaning in YAML.
    risky = text[0] in "#&*!|>%@`[]{},'\"" or text[-1] in " \t"
    looks_typed = text.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~")
    has_special = ":" in text or "#" in text
    if risky or looks_typed or has_special:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


_BLOCK_MARKER = re.compile(r"^[|>][-+0-9]*$")


def is_block_scalar(raw: str | None) -> bool:
    """True when a value is a ``|`` / ``>`` block marker rather than a scalar.

    The text lives on the following indented lines, so such a key must be
    rewritten with :func:`update_block_scalar`, never by replacing its line.
    """
    return bool(raw and _BLOCK_MARKER.fullmatch(raw.strip()))


def read_block_scalar(path: str | Path, dotted: str) -> str | None:
    """The text of a ``key: |`` block, dedented. None if not such a block."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    idx = _find_line(lines, dotted)
    if idx is None:
        return None
    m = _KEY_LINE.match(lines[idx])
    if not m:
        return None
    value, _ = _split_comment(m.group("rest"))
    if not is_block_scalar(value):
        return None

    key_indent = len(m.group("indent"))
    body: list[str] = []
    block_indent = None
    for line in lines[idx + 1 :]:
        if not line.strip():
            body.append("")
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= key_indent:
            break
        if block_indent is None:
            block_indent = indent
        body.append(line[block_indent:])
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


def update_block_scalar(path: str | Path, dotted: str, text: str) -> bool:
    """Replace the body of a ``key: |`` block, leaving the rest of the file.

    Returns True when the file changed. The block marker line keeps whatever
    style and trailing comment it already had.
    """
    p = Path(path)
    original = p.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()

    idx = _find_line(lines, dotted)
    if idx is None:
        raise SettingsWriteError(f"{dotted} is not present in {p}")
    m = _KEY_LINE.match(lines[idx])
    if not m:
        raise SettingsWriteError(f"{dotted} is not a normal key in {p}")
    value, _comment = _split_comment(m.group("rest"))
    if not is_block_scalar(value):
        raise SettingsWriteError(f"{dotted} is not a block scalar in {p}")

    key_indent = len(m.group("indent"))
    end = idx + 1
    block_indent = None
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            end += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= key_indent:
            break
        if block_indent is None:
            block_indent = indent
        end += 1
    while end - 1 > idx and not lines[end - 1].strip():
        end -= 1

    body_indent = " " * (block_indent if block_indent is not None else key_indent + 2)
    replacement = [
        (body_indent + ln) if ln.strip() else "" for ln in text.rstrip("\n").split("\n")
    ]
    updated = lines[: idx + 1] + replacement + lines[end:]
    if updated == lines:
        return False

    out = newline.join(updated)
    if original.endswith(("\n", "\r\n")):
        out += newline
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(out, encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SettingsWriteError(f"Could not save {p}: {exc}") from exc
    return True


def read_raw_value(path: str | Path, dotted: str) -> str | None:
    """The value exactly as written in the file, before ${VAR} expansion.

    Returns None when the key is absent. Used to tell a real value apart from
    an environment placeholder.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    idx = _find_line(lines, dotted)
    if idx is None:
        return None
    m = _KEY_LINE.match(lines[idx])
    if not m:
        return None
    value, _ = _split_comment(m.group("rest"))
    return value.strip()


def is_env_placeholder(raw: str | None) -> bool:
    """True when a raw value is a ${VAR} reference rather than a literal."""
    return bool(raw and _ENV_REF.fullmatch(raw.strip()))


def _find_line(lines: list[str], dotted: str) -> int | None:
    """Index of the line defining `dotted`, or None."""
    parts = dotted.split(".")
    depth = 0
    start = 0
    end = len(lines)
    parent_indent = -1

    for part in parts:
        found = None
        for i in range(start, end):
            line = lines[i]
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            m = _KEY_LINE.match(line)
            if not m:
                continue
            indent = len(m.group("indent"))
            # A key at or above the parent's level ends this section.
            if depth > 0 and indent <= parent_indent:
                break
            if m.group("key") != part:
                continue
            if depth == 0 and indent != 0:
                continue
            found = i
            break
        if found is None:
            return None
        if part is parts[-1] or part == parts[-1]:
            return found
        # Descend: the block belonging to this key runs until a line at the
        # same or shallower indent.
        parent_indent = len(_KEY_LINE.match(lines[found]).group("indent"))
        start = found + 1
        depth += 1
        end = len(lines)
        for j in range(start, len(lines)):
            line = lines[j]
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            m2 = _KEY_LINE.match(line)
            if m2 and len(m2.group("indent")) <= parent_indent:
                end = j
                break
    return None


def _comment_hint(lines: list[str], dotted: str) -> int:
    """Where to insert a new top-level key.

    Right after a commented-out example of it when one exists, so the value
    lands beside the comment explaining it. Otherwise before the first nested
    block, which keeps top-level keys together.
    """
    commented = re.compile(rf"^\s*#\s*{re.escape(dotted)}\s*:")
    for i, line in enumerate(lines):
        if commented.match(line):
            # Replace the commented example rather than sitting beside it:
            # two lines for one key reads as a mistake.
            lines.pop(i)
            return i
    for i, line in enumerate(lines):
        m = _KEY_LINE.match(line)
        if m and len(m.group("indent")) == 0:
            rest, _ = _split_comment(m.group("rest"))
            if not rest.strip():          # a block header such as `smtp:`
                return i
    return len(lines)


def update_settings(
    path: str | Path,
    changes: dict[str, Any],
    *,
    preserve_env_placeholders: bool = True,
    allow_replacing_placeholders: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Apply `changes` to the YAML file, touching only the affected lines.

    Returns the dotted keys that were actually written.

    A key whose current value is a ``${VAR}`` placeholder is skipped by
    default, so an indirection is never silently replaced by its expanded
    value — that would turn a shared template into a credential file by
    accident. Pass the key in `allow_replacing_placeholders` to overwrite it
    deliberately, which is what the settings window does when someone types a
    new password into the box.
    """
    p = Path(path)
    if not p.is_file():
        raise SettingsWriteError(f"Settings file not found: {p}")

    original = p.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    written: list[str] = []

    for dotted, value in changes.items():
        idx = _find_line(lines, dotted)
        if idx is None:
            # The key is absent, or present only as a comment (an example file
            # ships `# language: es`). Silently dropping the write is worse
            # than adding the key: the settings window appeared to save and
            # then forgot the choice. Only top-level keys are added, since
            # inventing a nested block would be guesswork.
            if "." in dotted:
                continue
            insert_at = _comment_hint(lines, dotted)
            lines.insert(insert_at, f"{dotted}: {_format(value)}")
            written.append(dotted)
            continue
        m = _KEY_LINE.match(lines[idx])
        if not m:
            continue
        current, comment = _split_comment(m.group("rest"))
        # A `key: |` block keeps its text on following lines. Replacing this
        # line would orphan that text and corrupt the file, so refuse it here;
        # update_block_scalar() is the correct tool.
        if is_block_scalar(current):
            continue
        if (
            preserve_env_placeholders
            and is_env_placeholder(current)
            and dotted not in allow_replacing_placeholders
        ):
            continue
        rendered = _format(value)
        if current.strip() == rendered:
            continue  # unchanged; do not rewrite the line
        spacer = " " if comment else ""
        lines[idx] = f"{m.group('indent')}{m.group('key')}: {rendered}{spacer}{comment}"
        written.append(dotted)

    if not written:
        return []

    text = newline.join(lines)
    if original.endswith(("\n", "\r\n")):
        text += newline

    # Write via a temporary file in the same directory, then replace, so an
    # interrupted save cannot leave a half-written config.
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SettingsWriteError(f"Could not save {p}: {exc}") from exc
    return written


def update_env_file(path: str | Path, changes: dict[str, str]) -> list[str]:
    """Set `KEY=value` entries in a .env file, creating it if absent."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    written: list[str] = []

    for key, value in changes.items():
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            if stripped.split("=", 1)[0].strip() == key:
                if stripped.split("=", 1)[1].strip().strip("'\"") != value:
                    lines[i] = f"{key}={value}"
                    written.append(key)
                break
        else:
            lines.append(f"{key}={value}")
            written.append(key)

    if not written:
        return []
    try:
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise SettingsWriteError(f"Could not save {p}: {exc}") from exc
    return written
