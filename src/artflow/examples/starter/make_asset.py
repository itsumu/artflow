"""A tiny, deterministic production tool. No Artflow dependency."""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

operation = sys.argv[1]
if operation == "build":
    spec = json.loads(Path(sys.argv[2]).read_text())
    color = spec["color"]
    if not isinstance(color, str) or len(color) != 7 or color[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
        raise ValueError("Expected hex color")
    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", viewBox="0 0 128 128")
    ET.SubElement(svg, "circle", cx="64", cy="64", r="38", fill=color)
    if spec["shape"] == "moon":
        ET.SubElement(svg, "circle", cx="83", cy="45", r="32", fill="#ffffff")
    else:
        for rotation in range(0, 360, 45):
            ET.SubElement(svg, "rect", x="60", y="4", width="8", height="16", rx="4", fill=color, transform=f"rotate({rotation} 64 64)")
    output = Path(sys.argv[3])
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(svg).write(output, encoding="unicode")
    print(f"Created {output.name}", flush=True)
elif operation == "verify":
    svg = ET.parse(sys.argv[2]).getroot()
    if not svg.tag.endswith("svg") or svg.attrib.get("viewBox") != "0 0 128 128":
        raise ValueError("Invalid SVG")
    print("SVG structure and viewBox passed.", flush=True)
else:
    raise ValueError("Unknown operation")
