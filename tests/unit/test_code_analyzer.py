"""
Tests for the Code Analyzer subsystem.
Run: pytest tests/unit/test_code_analyzer.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.code_analyzer import (
    _infer_language,
    _is_hook,
    _is_react_component,
    extract_symbols_from_content,
)

# ─── Sample file content from PR #6857 ────────────────────────────────

DROPDOWN_ROW_CONTENT = """
import { useState, useMemo } from "react";

export const DropdownRow = ({ attribute, attributeValues }) => {
  const intl = useIntl();
  const fieldId = `attribute:${attribute.label}`;
  return <div />;
};

export const toOptions = (values) => values.map(v => ({ value: v.slug }));
export const mergeOptions = (seed, remote) => [...seed, ...remote];
export const filterOptions = (options, query) => options.filter(o => o.label.includes(query));
"""

ATTRIBUTES_CONTENT = """
import React from "react";

export type AttributeValueChoices = AttributeValueFragment[] | ((id: string) => AttributeValueFragment[]);
export type AttributeValueFetchMore = FetchMoreProps | ((id: string) => FetchMoreProps);

export const Attributes = ({ attributes, attributeValues }) => {
  return <div>{attributes.map(a => <span key={a.id} />)}</div>;
};
"""

USE_ATTRIBUTE_DROPDOWN_CONTENT = """
import { useCallback, useMemo } from "react";

export const useAttributeDropdown = ({ fetchOptions, fetchMore }) => {
  const handleFocus = () => {
    fetchOptions("");
  };
  return { handleFocus };
};
"""


# ─── Tests ────────────────────────────────────────────────────────────


def test_extract_react_component():
    """Should detect DropdownRow as a React component."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/DropdownRow.tsx", DROPDOWN_ROW_CONTENT
    )
    names = [s.name for s in symbols]
    assert "DropdownRow" in names, f"DropdownRow not found in: {names}"


def test_extract_hook():
    """Should detect useAttributeDropdown as a hook."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/useAttributeDropdown.tsx", USE_ATTRIBUTE_DROPDOWN_CONTENT
    )
    hooks = [s for s in symbols if s.is_hook]
    hook_names = [s.name for s in hooks]
    assert "useAttributeDropdown" in hook_names, f"Hook not found in: {hook_names}"


def test_extract_utility_functions():
    """Should detect utility functions like toOptions, mergeOptions, filterOptions."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/DropdownRow.tsx", DROPDOWN_ROW_CONTENT
    )
    names = {s.name for s in symbols}
    assert "toOptions" in names or "mergeOptions" in names or "filterOptions" in names, (
        f"Expected utility functions in: {names}"
    )


def test_exported_flag():
    """All detected symbols should be marked as exported."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/DropdownRow.tsx", DROPDOWN_ROW_CONTENT
    )
    for sym in symbols:
        assert sym.exported, f"Symbol {sym.name} not marked as exported"


def test_fqn_format():
    """FQNs should be in 'FileName.SymbolName' format."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/DropdownRow.tsx", DROPDOWN_ROW_CONTENT
    )
    for sym in symbols:
        assert "." in sym.fqn, f"FQN has no dot: {sym.fqn}"
        assert sym.fqn.startswith("DropdownRow."), f"FQN wrong prefix: {sym.fqn}"


def test_component_detection():
    """Attributes component should be detected as a React component."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/Attributes.tsx", ATTRIBUTES_CONTENT
    )
    components = [s for s in symbols if s.is_component]
    component_names = [s.name for s in components]
    assert "Attributes" in component_names, f"Attributes not in components: {component_names}"


def test_infer_language_typescript():
    assert _infer_language("src/components/Foo.tsx") == "typescript-react"
    assert _infer_language("src/utils/bar.ts") == "typescript"


def test_infer_language_javascript():
    assert _infer_language("src/legacy/foo.jsx") == "javascript-react"


def test_is_react_component():
    assert _is_react_component("DropdownRow") is True
    assert _is_react_component("handleClick") is False
    assert _is_react_component("") is False


def test_is_hook():
    assert _is_hook("useAttributeDropdown") is True
    assert _is_hook("DropdownRow") is False
    assert _is_hook("use") is False  # too short


def test_no_duplicates():
    """Same symbol name should not appear twice in output."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/DropdownRow.tsx", DROPDOWN_ROW_CONTENT
    )
    names = [s.name for s in symbols]
    assert len(names) == len(set(names)), f"Duplicate symbols: {names}"


def test_start_line_positive():
    """All symbols should have positive start line numbers."""
    symbols = extract_symbols_from_content(
        "src/components/Attributes/DropdownRow.tsx", DROPDOWN_ROW_CONTENT
    )
    for sym in symbols:
        assert sym.start_line >= 1, f"Non-positive start line for {sym.name}: {sym.start_line}"
