"""Prove the isolated fixture leaves the prior main.c text intact when OFF."""
import re
from pathlib import Path


def remove_fixture(text):
    lines = text.splitlines(keepends=True)
    result = []
    index = 0
    guards = 0
    while index < len(lines):
        if lines[index].strip() != "#if defined(FOC_ISOLATED_CONCURRENCY)":
            result.append(lines[index])
            index += 1
            continue
        guards += 1
        depth, split, end = 1, None, index + 1
        while end < len(lines):
            directive = lines[end].strip()
            if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
                depth += 1
            elif re.match(r"#\s*endif\b", directive):
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1 and directive == "#else":
                if split is not None:
                    raise ValueError("Repeated else")
                split = end
            elif depth == 1 and directive.startswith("#elif"):
                raise ValueError("Unexpected isolated elif")
            end += 1
        if depth != 0:
            raise ValueError("Unbalanced fixture")
        if split is not None:
            result.extend(lines[split + 1:end])
        index = end + 1
    if guards != 17:
        raise ValueError(f"Expected 17 fixture guards, found {guards}")
    return "".join(result)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    for slot in ("a", "b"):
        relative = Path(f"foc2_app_{slot}/Core/Src/main.c")
        old = (root / "refactor_backups/20261006_isolated_concurrency_before" / relative).read_text()
        current = (root / relative).read_text()
        assert remove_fixture(current) == old, f"Unrelated change: {relative}"
        print(f"PASS {relative}: all changes opt-in; exact OFF source preserved")
