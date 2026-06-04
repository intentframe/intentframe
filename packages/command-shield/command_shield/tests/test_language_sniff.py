"""Tests for language_sniff — extension / shebang / content sniffing."""

from __future__ import annotations

import pytest

from command_shield.language_sniff import (
    detect_binary,
    language_from_content,
    language_from_extension,
    language_from_shebang,
    sniff_language,
)


class TestLanguageFromExtension:
    @pytest.mark.parametrize("path, lang", [
        ("foo.py", "python"),
        ("/abs/foo.pyw", "python"),
        ("script.sh", "shell"),
        ("script.bash", "shell"),
        ("app.js", "javascript"),
        ("app.mjs", "javascript"),
        ("app.ts", "typescript"),
        ("Foo.rb", "ruby"),
        ("x.pl", "perl"),
        ("app.scpt", "applescript"),
    ])
    def test_known_extensions(self, path: str, lang: str) -> None:
        assert language_from_extension(path) == lang

    def test_none_for_unknown(self) -> None:
        assert language_from_extension("foo.xyz") is None

    def test_none_for_empty(self) -> None:
        assert language_from_extension(None) is None
        assert language_from_extension("") is None


class TestLanguageFromShebang:
    @pytest.mark.parametrize("src, lang", [
        ("#!/usr/bin/python3\nprint(1)", "python"),
        ("#!/usr/bin/env python\nprint(1)", "python"),
        ("#!/bin/bash\necho hi", "shell"),
        ("#!/bin/sh\necho hi", "shell"),
        ("#!/usr/bin/env node\nconsole.log(1)", "javascript"),
        ("#!/usr/bin/env ruby\nputs 1", "ruby"),
        ("#!/usr/bin/env perl\nprint 1", "perl"),
    ])
    def test_known_shebangs(self, src: str, lang: str) -> None:
        assert language_from_shebang(src) == lang

    def test_no_shebang(self) -> None:
        assert language_from_shebang("print(1)") is None
        assert language_from_shebang("") is None


class TestLanguageFromContent:
    def test_python_multi_signal(self) -> None:
        src = (
            "import os\n"
            "from sys import argv\n"
            "def main():\n"
            "    print(argv)\n"
        )
        assert language_from_content(src) == "python"

    def test_shell_multi_signal(self) -> None:
        src = (
            "set -euo pipefail\n"
            "for f in *.log; do\n"
            "  echo $f\n"
            "done\n"
        )
        assert language_from_content(src) == "shell"

    def test_javascript_multi_signal(self) -> None:
        src = (
            'const foo = require("fs");\n'
            "function bar() { return 1; }\n"
            "console.log(bar());\n"
        )
        assert language_from_content(src) == "javascript"

    def test_unknown_too_few_signals(self) -> None:
        assert language_from_content("x = 1") is None

    def test_unknown_empty(self) -> None:
        assert language_from_content("") is None


class TestSniffLanguage:
    def test_extension_wins(self) -> None:
        assert sniff_language("echo hi", path="foo.py") == "python"

    def test_falls_back_to_shebang(self) -> None:
        assert sniff_language("#!/bin/bash\nX=1") == "shell"

    def test_falls_back_to_content(self) -> None:
        src = "import os\ndef main():\n    print(1)\n"
        assert sniff_language(src) == "python"

    def test_unknown_when_all_ambiguous(self) -> None:
        assert sniff_language("x = 1") == "unknown"

    def test_content_sniff_disabled(self) -> None:
        src = "import os\ndef main():\n    print(1)\n"
        assert sniff_language(src, use_content=False) == "unknown"


class TestDetectBinary:
    @pytest.mark.parametrize("prefix", [
        b"\x7fELF\x02\x01\x01",
        b"\xcf\xfa\xed\xfe\x07\x00\x00\x01",
        b"MZ\x90\x00",
        b"PK\x03\x04\x14\x00",
        b"\x1f\x8b\x08\x00",
        b"%PDF-1.7\n",
        b"\x89PNG\r\n\x1a\n",
    ])
    def test_magic_bytes(self, prefix: bytes) -> None:
        assert detect_binary(prefix + b"\x00" * 100) is True

    def test_null_byte_heuristic(self) -> None:
        assert detect_binary(b"plain text\x00more") is True

    def test_plain_text_false(self) -> None:
        assert detect_binary(b"hello world\n") is False

    def test_empty_false(self) -> None:
        assert detect_binary(b"") is False
