import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SECTION_PATTERN = re.compile(r"(?m)^\[([A-Z0-9-]+)\].*$")


def load_corpus() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Load the existing fictional manuals and the fixed evaluation questions."""
    sections: list[dict[str, str]] = []
    for path in sorted((ROOT / "data" / "demo").glob("manual-*.txt")):
        content = path.read_text(encoding="utf-8")
        headings = list(SECTION_PATTERN.finditer(content))
        for index, heading in enumerate(headings):
            end = (
                headings[index + 1].start()
                if index + 1 < len(headings)
                else len(content)
            )
            sections.append(
                {
                    "model": (
                        "Orion B20"
                        if heading.group(1).startswith("ORION")
                        else "Atlas T30"
                    ),
                    "section": heading.group(1),
                    "content": content[heading.start() : end].strip(),
                    "filename": path.name,
                }
            )
    questions = json.loads(
        (ROOT / "data" / "demo" / "questions.json").read_text(encoding="utf-8")
    )
    if len(questions) != 30 or sum(
        bool(item["answerable"]) for item in questions
    ) != 25:
        raise ValueError(
            "The benchmark corpus must contain 25 answerable and 5 unanswerable questions."
        )
    return sections, questions
