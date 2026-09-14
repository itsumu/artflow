from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


REPOSITORY = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class DocumentationTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        markdown_files = [
            REPOSITORY / "README.md",
            REPOSITORY / "CONTRIBUTING.md",
            REPOSITORY / "SECURITY.md",
            *sorted((REPOSITORY / "docs").glob("*.md")),
            *sorted((REPOSITORY / "examples").glob("*.md")),
            REPOSITORY / "src/artflow/examples/starter/README.md",
        ]
        failures = []
        for markdown in markdown_files:
            text = markdown.read_text(encoding="utf-8")
            for match in MARKDOWN_LINK.finditer(text):
                target = match.group(1).strip().strip("<>")
                if (not target or target.startswith(("#", "http://", "https://", "mailto:"))):
                    continue
                path = unquote(target.split("#", 1)[0])
                resolved = (markdown.parent / path).resolve()
                if not resolved.exists():
                    failures.append(
                        f"{markdown.relative_to(REPOSITORY)} -> {target}"
                    )
        self.assertEqual(failures, [], "Broken local documentation links:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
