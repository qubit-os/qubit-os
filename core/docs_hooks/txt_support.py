"""MkDocs hook: treat .txt files in docs_dir as documentation pages.

QubitOS documentation is authored as .txt (Linux-kernel-style plain text)
but MkDocs hard-codes .md as the documentation-page extension. This hook
bridges the gap with three handlers:

  on_config       Rewrites any nav entry ending in .txt to .md so the
                  config matches the file names mkdocs sees during build.

  on_pre_build    Renames every *.txt under docs_dir to *.md in place,
                  recording the renames for restoration.

  on_post_build   Restores the .md files back to .txt.

  on_build_error  Also restores, so a failed build does not leave the
                  working tree in a half-renamed state.

The .txt files in the source tree are unchanged on disk after a
successful build. CI and contributors only ever see .txt extensions.
"""

from __future__ import annotations

from pathlib import Path

_renamed: list[tuple[Path, Path]] = []


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


def on_pre_build(config, **kwargs):
    """Rename every *.txt under docs_dir to *.md."""
    global _renamed
    _renamed = []
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
        txt.rename(md)
        _renamed.append((md, txt))


def _restore() -> None:
    global _renamed
    for md, txt in _renamed:
        if md.exists() and not txt.exists():
            md.rename(txt)
    _renamed = []


def on_post_build(config, **kwargs):
    _restore()


def on_build_error(error, **kwargs):
    _restore()
