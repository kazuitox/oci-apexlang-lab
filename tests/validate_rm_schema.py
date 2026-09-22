#!/usr/bin/env python3
"""Validate schema.yaml using the meta schema published in Oracle's Resource Manager documentation."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import urllib.request

import jsonschema
import yaml

URL = "https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Concepts/terraformconfigresourcemanager_topic-schema.htm"


class CodeBlocks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.collecting = False
        self.parts = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.collecting = True
            self.parts = []

    def handle_endtag(self, tag):
        if tag == "pre" and self.collecting:
            self.blocks.append("".join(self.parts))
            self.collecting = False

    def handle_data(self, data):
        if self.collecting:
            self.parts.append(data)


if __name__ == "__main__":
    # A previously downloaded official HTML file can be supplied for offline use.
    if len(sys.argv) > 1:
        html = Path(sys.argv[1]).read_text()
    else:
        with urllib.request.urlopen(URL, timeout=60) as response:
            html = response.read().decode("utf-8")
    parser = CodeBlocks()
    parser.feed(html)
    matches = [block for block in parser.blocks if "# Meta JSON Schema." in block]
    if len(matches) != 1:
        raise SystemExit("Official meta schema was not uniquely found; inspect the documentation.")
    meta = yaml.safe_load(matches[0])
    schema = yaml.safe_load((Path(__file__).resolve().parents[1] / "schema.yaml").read_text())
    jsonschema.Draft4Validator(meta).validate(schema)
    print("Resource Manager schema: PASS (Oracle published meta schema)")
