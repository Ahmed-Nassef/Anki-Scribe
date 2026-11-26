"""Static contract tests for the no-build browser client.

Nothing here executes JavaScript. These tests guard the two failures this
architecture actually has: an element id that exists in one place and not the
other, and a function that the event wiring calls but nobody defined.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
INDEX = STATIC / "index.html"
JS_FILES = sorted((STATIC / "js").glob("*.js"))

# Browser and language globals used from the client.
BUILTINS = {
    "api",
    "Array",
    "Boolean",
    "Date",
    "Error",
    "Map",
    "Math",
    "Number",
    "Object",
    "Promise",
    "Set",
    "String",
    "URLSearchParams",
    "alert",
    "confirm",
    "console",
    "crypto",
    "decodeURIComponent",
    "document",
    "encodeURIComponent",
    "fetch",
    "isNaN",
    "navigator",
    "parseInt",
    "performance",
    "prompt",
    "requestAnimationFrame",
    "setInterval",
    "setTimeout",
    "clearTimeout",
    "localStorage",
    "window",
}


def index_ids() -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', INDEX.read_text(encoding="utf-8")))


def registered_ids() -> list[str]:
    """Ids listed in app.js's hand-maintained registry."""
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    match = re.search(r"\[\s*((?:\s*\"[^\"]+\",?)+)\s*\]\.forEach", source)
    assert match, "app.js registry block not found"
    return re.findall(r'"([^"]+)"', match.group(1))


def all_js() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in JS_FILES)


def test_every_registered_id_exists_in_the_document():
    missing = sorted(set(registered_ids()) - index_ids())
    assert not missing, f"app.js references ids that index.html does not define: {missing}"


def test_every_element_used_is_registered():
    used = set(re.findall(r"\bels\.([A-Za-z0-9_]+)", all_js()))
    missing = sorted(used - set(registered_ids()))
    assert not missing, f"els.* used but not in the app.js registry: {missing}"


def test_no_duplicate_ids_in_the_document():
    ids = re.findall(r'\bid="([^"]+)"', INDEX.read_text(encoding="utf-8"))
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    assert not duplicates, f"duplicate ids in index.html: {duplicates}"


KEYWORDS = {
    "async",
    "await",
    "catch",
    "delete",
    "do",
    "else",
    "for",
    "function",
    "if",
    "in",
    "instanceof",
    "new",
    "of",
    "return",
    "switch",
    "throw",
    "try",
    "typeof",
    "void",
    "while",
    "yield",
}


def test_every_function_called_from_event_wiring_is_defined():
    defined = set(re.findall(r"\bfunction\s+([A-Za-z0-9_]+)\s*\(", all_js()))
    defined |= set(re.findall(r"\b(?:const|let)\s+([A-Za-z0-9_]+)\s*=", all_js()))
    events = (STATIC / "js" / "events.js").read_text(encoding="utf-8")
    called = set(re.findall(r"(?<![\w.$])([a-z][A-Za-z0-9_]*)\s*\(", events))
    unknown = sorted(called - defined - BUILTINS - KEYWORDS)
    assert not unknown, f"events.js calls functions that do not exist: {unknown}"


def test_scripts_load_in_a_declared_order_without_gaps():
    html = INDEX.read_text(encoding="utf-8")
    loaded = re.findall(r'<script src="/static/js/([^"]+)"', html)
    on_disk = [path.name for path in JS_FILES]
    assert sorted(loaded) == on_disk, (
        f"script tags {sorted(loaded)} do not match files on disk {on_disk}"
    )
    assert loaded[-1] == "app.js", "app.js must load last: it calls into every other file"


def test_no_model_text_is_written_as_html():
    """The client must never assign a data string to innerHTML."""
    risky = []
    for path in JS_FILES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "innerHTML" not in line and "insertAdjacentHTML" not in line:
                continue
            if "${" in line:
                risky.append(f"{path.name}:{number}: {line.strip()}")
    assert not risky, "innerHTML with interpolation found:\n" + "\n".join(risky)
