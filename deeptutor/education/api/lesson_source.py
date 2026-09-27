"""Export the verified, bundled lesson through the existing KB upload flow."""

from html.parser import HTMLParser
import re


class _LessonText(HTMLParser):
    """Keep teaching text, tables and SVG descriptions; discard page chrome."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.link = None
        self.header_row = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.skip:
            if tag in {"head", "nav", "script", "style"}:
                self.skip += 1
            return
        if tag in {"head", "nav", "script", "style"}:
            self.skip = 1
        elif tag in {"h1", "h2", "h3"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "tr":
            self.parts.append("\n| ")
        elif tag == "thead":
            self.header_row = True
        elif tag == "a":
            self.link = attrs.get("href")
        elif tag == "br":
            self.parts.append(" ")
        elif tag in {"p", "section", "figure", "figcaption", "caption", "summary", "title", "desc"}:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if self.skip:
            if tag in {"head", "nav", "script", "style"}:
                self.skip -= 1
            return
        if tag in {"td", "th"}:
            self.parts.append(" | ")
        elif tag == "tr" and self.header_row:
            # The bundled table has four columns; derive the separator count.
            row = "".join(self.parts).splitlines()[-1]
            self.parts.append("\n|" + " --- |" * (row.count("|") - 1))
        elif tag == "thead":
            self.header_row = False
        elif tag == "a":
            if self.link and self.link.startswith("https://"):
                self.parts.append(f" ({self.link})")
            self.link = None
        elif tag in {"p", "h1", "h2", "h3", "section", "table", "figure", "summary", "title", "desc"}:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self):
        return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(self.parts)).strip()


def export_lesson_source(lesson_id: str, meta: dict, html: str) -> str:
    parser = _LessonText()
    parser.feed(html)
    parser.close()
    standards = "\n".join(meta["standards"])
    return (
        f"**[DeepTutor trial lesson {lesson_id}: {meta['unit_title']}]**\n\n"
        "CCSS Standards\n\nAddressing\n\n"
        f"{standards}\n\n"
        "Trial teaching material — pending human review. Importing this document "
        "does not activate a course or certify mastery. Practice is optional.\n\n"
        f"Original lesson: /api/edu/lessons/{lesson_id}\n"
        f"Source SHA-256: {meta['sha256']}\n\n"
        f"{parser.text()}\n"
    )
