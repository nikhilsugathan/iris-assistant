from __future__ import annotations


def test_javascript_context_infers_js_not_python():
    from core.autocorrect import AutoCorrector

    corrector = AutoCorrector()
    filename, _note, needs_clarification, options = corrector.correct_extension(
        "app",
        context="create a javascript file named app",
    )

    assert filename == "app.js"
    assert needs_clarification is False
    assert options == []


def test_typescript_context_infers_ts():
    from core.autocorrect import AutoCorrector

    corrector = AutoCorrector()
    filename, *_rest = corrector.correct_extension(
        "service",
        context="make a typescript file called service",
    )

    assert filename == "service.ts"


def test_generic_code_does_not_silently_assume_python():
    from core.autocorrect import AutoCorrector

    corrector = AutoCorrector()
    filename, *_rest = corrector.correct_extension(
        "example",
        context="create a code file named example",
    )

    assert filename == "example.txt"


def test_ambiguous_pf_only_resolves_to_python_on_explicit_python_cue():
    from core.autocorrect import AutoCorrector

    corrector = AutoCorrector()
    python_name, _note, needs_clarification, _options = corrector.correct_extension(
        "tool.pf",
        context="create a python script tool",
    )
    assert python_name == "tool.py"
    assert needs_clarification is False

    ambiguous_name, _note, needs_clarification, options = corrector.correct_extension(
        "tool.pf",
        context="create a javascript file tool",
    )
    assert ambiguous_name == "tool.pf"
    assert needs_clarification is True
    assert options == [".pdf", ".py"]


def test_common_explicit_contexts_map_to_expected_extensions():
    from core.autocorrect import AutoCorrector

    corrector = AutoCorrector()
    cases = {
        "markdown readme": ".md",
        "powershell script": ".ps1",
        "shell script": ".sh",
        "web page": ".html",
        "style sheet": ".css",
        "yaml config": ".yaml",
        "excel spreadsheet": ".xlsx",
    }

    for context, expected in cases.items():
        filename, *_rest = corrector.correct_extension("sample", context=context)
        assert filename.endswith(expected), (context, filename)
