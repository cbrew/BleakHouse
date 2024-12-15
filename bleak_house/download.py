from pathlib import Path
from typing import Dict,Any
import io

import requests
import zipfile
import lxml.etree as etree
from hamilton.function_modifiers import cache

URL = "https://gutenberg.org/cache/epub/1023/pg1023.txt"

HTML_ZIP_URL="https://www.gutenberg.org/cache/epub/1023/pg1023-h.zip"


def text(url: str = URL) -> Dict[str,Any]:
    response = requests.get(url)
    return {"source": "gutenberg",
            "text":   response.text}

def html_paths (url: str = HTML_ZIP_URL) -> Dict[str,Path]:
    response = requests.get(url)
    r = requests.get(url)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    z.extractall("data")
    return {f: Path(f"data/{f}") for f in z.namelist()}


def html_data(html_paths: Dict[str,Path]) -> Dict[str,str]:
    data = {}
    for name,path in html_paths.items():
        if name.endswith(".html"):
            html_content = path.read_text()
            tree = etree.HTML(html_content)
            # Find all <a> elements with an id, embedded in <p>
            anchors = tree.xpath('//p[a[@id]]')
            result = []
            for i, anchor in enumerate(anchors):
                title = ""
                text = ""

                # Get the title (assume it's the first <h3> or <h2> after the <a>)
                following_elements = anchor.xpath('./following-sibling::*')
                for element in following_elements:
                    if element.tag in ['h3', 'h2']:
                        title = ''.join(element.itertext()).strip()
                    elif element.tag == 'p':
                        text += '\n'.join(element.itertext()).strip() + '\n'

                    # Stop when reaching the next <a> with an id
                    if element.xpath('./a[@id]'):
                        break
                if title or text:
                    result.append({"id": anchors[i][0].attrib['id'], "title": title, "text": text.strip()})
            data[name] = result
    return data





