"""Typed helpers that narrow scrapling lookups to a ``Selector``.

``Selector.find`` returns ``Selector | None``; these wrappers narrow to
``Selector`` so call sites stay clean and a missing required element raises a
clear error instead of a cryptic ``AttributeError`` on ``None``.
"""

from typing import Any

from scrapling.parser import Selector


def get_text(node: Selector) -> str:
    """Recursively extract all text content from *node*.

    Scrapling's ``Selector.text`` only returns the element's *direct* text
    (the first text node), which is empty for elements whose content lives
    inside child tags like ``<b>`` or ``<span>``.  This helper uses lxml's
    ``text_content()`` to collect text from all descendant nodes — matching
    the behaviour callers expect from BeautifulSoup's ``.text``.
    """
    return node._root.text_content()


class ElementNotFound(Exception):
    pass


def find_tag_opt(
    node: Selector,
    *args: Any,
    attrs: dict[str, str] | None = None,
    **kwargs: Any,
) -> Selector | None:
    """Find the first matching element, transparently handling ``attrs={}``.

    Scrapling's ``find()`` treats every keyword argument as an
    ``attr="value"`` filter, so ``attrs={"class": "foo"}`` must be
    unpacked first.  The ``class`` key is mapped to ``class_`` because
    ``class`` is a reserved word in Python.
    """
    if attrs:
        for key, value in attrs.items():
            kwargs["class_" if key == "class" else key] = value
    return node.find(*args, **kwargs)


def find_tag(node: Selector, *args: Any, **kwargs: Any) -> Selector:
    found = find_tag_opt(node, *args, **kwargs)
    if found is None:
        raise ElementNotFound(f"no Selector matched find({args}, {kwargs})")
    return found
