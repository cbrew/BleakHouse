"""Derive the webapp blog templates from the canonical system_flow doc.

Source:  docs/system_flow.html
Targets: webapp/templates/blog_system_flow.html
         webapp_v2/templates/blog_system_flow.html

Both webapps render the same blog post; the templates are byte-identical
copies of each other. Rather than commit two derived files and risk
drift, this script regenerates both from the single source doc.

Transformation:
  1. Strip <!doctype>, <html>, <head>, <body> wrappers.
  2. Lift the <style> block into a Jinja `extra_head` block.
  3. Wrap the body content in <div class="sf-content"> and a Jinja
     `content` block extending base.html.
  4. Prefix every class name defined in the source <style> block with
     `sf-` to avoid clashes with the host site's CSS — applied both to
     CSS rules and to HTML class attributes.

Run before deploying the webapps:
    uv run python scripts/build_blog_system_flow.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "system_flow.html"
TARGETS = [
    ROOT / "webapp" / "templates" / "blog_system_flow.html",
    ROOT / "webapp_v2" / "templates" / "blog_system_flow.html",
]
PREFIX = "sf-"

# Pseudo-classes / pseudo-elements ruff-prefixed in CSS selectors. We
# don't touch these; they're not class names. (The CSS in the source
# doc doesn't use any of them, but list here so the regex stays sane.)
_PSEUDO = {"hover", "active", "focus", "before", "after", "first-child",
           "last-child", "nth-child"}


def _collect_class_names(css: str) -> set[str]:
    """Find every class name referenced in CSS class selectors."""
    # Match `.<name>` where <name> is one or more dash/word characters
    # not followed by another dash-word character that would extend it.
    # We deliberately re-match inside compound selectors like
    # `.foo.bar:hover` and `.foo .bar` — each `.name` is captured once.
    names: set[str] = set()
    for m in re.finditer(r"\.([A-Za-z_][\w-]*)", css):
        n = m.group(1)
        if n in _PSEUDO:
            continue
        names.add(n)
    return names


def _prefix_css(css: str, names: set[str]) -> str:
    """Rewrite class selectors in CSS rules to use the sf- prefix."""
    # Match `.name` only when `name` is a known class (not e.g. `.5em`
    # in a value, which won't match the class-name regex anyway because
    # CSS values like `0.5em` have a digit after the dot).
    def repl(m: re.Match[str]) -> str:
        n = m.group(1)
        if n in names:
            return f".{PREFIX}{n}"
        return m.group(0)
    return re.sub(r"\.([A-Za-z_][\w-]*)", repl, css)


def _prefix_html_classes(html: str, names: set[str]) -> str:
    """Rewrite class attributes in the HTML body so every class token
    that was defined in the local <style> block carries the sf- prefix.
    Tokens not in the local CSS (e.g. Jinja control flow) pass through
    unchanged.

    Only matches `class="…"` attributes. The source doc uses double
    quotes uniformly; if that ever changes, extend this regex."""
    def rewrite(m: re.Match[str]) -> str:
        tokens = m.group(1).split()
        rewritten = [PREFIX + t if t in names else t for t in tokens]
        return f'class="{" ".join(rewritten)}"'
    return re.sub(r'class="([^"]+)"', rewrite, html)


def build_template(source_html: str) -> str:
    """Apply the four-step transformation. Returns the Jinja template."""
    # 1. Extract <style> block.
    style_match = re.search(r"<style[^>]*>(.*?)</style>", source_html, re.DOTALL)
    if not style_match:
        raise RuntimeError("Source doc has no <style> block to lift.")
    style_css = style_match.group(1)
    style_full = style_match.group(0)

    # 2. Extract <body>…</body> content.
    body_match = re.search(r"<body[^>]*>(.*?)</body>", source_html, re.DOTALL)
    if not body_match:
        raise RuntimeError("Source doc has no <body> tags.")
    body_html = body_match.group(1).strip()

    # 3. Collect class names from the source CSS, prefix both CSS + HTML.
    names = _collect_class_names(style_css)
    prefixed_css = _prefix_css(style_css, names)
    prefixed_body = _prefix_html_classes(body_html, names)

    # 4. Strip the global resets that aren't safe inside the host site
    #    (body/html level styling). We keep all the doc's bespoke
    #    classes; we drop element-level rules for `body`, `h1`, `h2`,
    #    `h3`, `p`, `code`, `pre`, `:root` so the host's typography
    #    isn't overridden. Element rules are matched by the absence of
    #    a leading `.` on the selector.
    #
    #    `:root` block (custom-property declarations) stays — those are
    #    safe to define globally because they're scoped by name, not by
    #    selector. We keep the :root rule by NOT stripping it.
    stripped_css = _strip_element_rules(prefixed_css)

    return _ASSEMBLE.format(css=stripped_css.strip(), body=prefixed_body)


def _strip_element_rules(css: str) -> str:
    """Remove top-level rules that target HTML elements (body, h1, p, …)
    rather than classes. Keeps `:root { … }` (variable declarations) and
    every class-based rule (`.sf-…`)."""
    out: list[str] = []
    i = 0
    n = len(css)
    while i < n:
        # Skip whitespace
        while i < n and css[i].isspace():
            out.append(css[i]); i += 1
        if i >= n:
            break
        # Find the next `{`
        brace = css.find("{", i)
        if brace < 0:
            out.append(css[i:]); break
        selector = css[i:brace]
        # Find the matching `}`. CSS doesn't nest at this level (we
        # don't use @media-inside-@media), so a simple scan works.
        depth = 0
        j = brace
        while j < n:
            if css[j] == "{": depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0: break
            j += 1
        block = css[i:j+1]
        # Decide: keep or drop. Keep if the selector contains a `.` or
        # `:root`, or is an @media query (we keep media blocks intact —
        # they wrap class-based rules elsewhere in the source).
        sel_stripped = selector.strip()
        keep = (
            "." in selector
            or sel_stripped.startswith(":root")
            or sel_stripped.startswith("@")
        )
        if keep:
            out.append(block)
        i = j + 1
    return "".join(out)


_ASSEMBLE = """{{% extends "base.html" %}}
{{% block title %}}Not In Our Time — System flow, novel to audio{{% endblock %}}

{{% block extra_head %}}
<style>
/* Generated from docs/system_flow.html by scripts/build_blog_system_flow.py.
   Do not edit directly — re-run the build script after changing the source. */
{css}
</style>
{{% endblock %}}

{{% block content %}}
<div class="sf-content">
{body}
</div>
{{% endblock %}}
"""


def main() -> None:
    source = SOURCE.read_text()
    template = build_template(source)
    for target in TARGETS:
        target.write_text(template)
        print(f"wrote {target.relative_to(ROOT)} ({len(template)} bytes)")


if __name__ == "__main__":
    main()
