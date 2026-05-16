"""MkDocs hook: treat .txt files in docs_dir as documentation pages.

QubitOS documentation is authored as .txt (Linux-kernel-style plain text)
but MkDocs hard-codes .md as the documentation-page extension. This hook
bridges the gap with three handlers:

  on_config       Rewrites any nav entry ending in .txt to .md so the
                  config matches the file names mkdocs sees during build.

  on_pre_build    Creates transient *.md copies of every *.txt page and
                  rewrites internal markdown links from .txt to .md so
                  MkDocs link validation sees the generated page names.

  on_post_build   Deletes the transient *.md files.

  on_build_error  Also cleans up, so a failed build does not leave the
                  working tree in a half-generated state.

The .txt files in the source tree are unchanged on disk after a
successful build. CI and contributors only ever see .txt extensions.
"""

from __future__ import annotations

from pathlib import Path
import re

_generated: list[Path] = []
_MARKDOWN_LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)]+)(\))")


def on_config(config, **kwargs):
    """Swap .txt extensions in the nav for .md so mkdocs resolves them
    correctly after on_pre_build renames the files."""

    def rewrite(node):
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if isinstance(node, dict):
            return {key: rewrite(value) for key, value in node.items()}
        if isinstance(node, str) and node.endswith(".txt"):
            return node[:-4] + ".md"
        return node

    nav = config.get("nav")
    if nav:
        config["nav"] = rewrite(nav)
    return config


def _rewrite_internal_txt_links(text: str, source: Path, docs_dir: Path) -> str:
    """Point internal markdown links at the transient .md copies."""

    def replace(match: re.Match[str]) -> str:
        prefix, target, suffix = match.groups()
        if target.startswith(("#", "http://", "https://", "mailto:")):
            return match.group(0)

        target_path, hash_sep, fragment = target.partition("#")
        target_path, query_sep, query = target_path.partition("?")
        resolved = (source.parent / target_path).resolve()

        try:
            resolved.relative_to(docs_dir.resolve())
        except ValueError:
            return match.group(0)

        if resolved.suffix != ".txt" or not resolved.exists():
            return match.group(0)

        rewritten = target_path[:-4] + ".md"
        if query_sep:
            rewritten = f"{rewritten}?{query}"
        if hash_sep:
            rewritten = f"{rewritten}#{fragment}"
        return f"{prefix}{rewritten}{suffix}"

    return _MARKDOWN_LINK_RE.sub(replace, text)


def on_pre_build(config, **kwargs):
    """Create transient *.md copies for every *.txt page."""
    global _generated
    _generated = []
    docs_dir = Path(config["docs_dir"])
    for txt in docs_dir.rglob("*.txt"):
        md = txt.with_suffix(".md")
        if md.exists():
            # Both extensions coexist: bail loudly rather than risk losing
            # content. The hook is meant to operate on a docs tree that is
            # exclusively .txt.
            raise RuntimeError(
                f"txt_support hook: both {txt} and {md} exist; "
                "remove one before building."
            )
        content = txt.read_text(encoding="utf-8")
        md.write_text(
            _rewrite_internal_txt_links(content, txt, docs_dir),
            encoding="utf-8",
        )
        _generated.append(md)


def _restore() -> None:
    global _generated
    for md in _generated:
        if md.exists():
            md.unlink()
    _generated = []


def on_post_build(config, **kwargs):
    _restore()


def on_build_error(error, **kwargs):
    _restore()
