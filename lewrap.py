#!/usr/bin/env -S uv run --script
################################################################
# Copyright (c) 2026 Witalis Domitrz <witekdomitrz@gmail.com>
# AGPL License
################################################################
#
# /// script
# dependencies = [
#     "pygls",
#     "typing-extensions",
# ]
# ///

from __future__ import annotations

import argparse
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, cast

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from typing_extensions import Self

LanguageMode = Literal["comments", "plain-text"]


@dataclass(frozen=True, kw_only=True)
class Args:
    column: int

    @classmethod
    def from_args(cls, argv: list[str] | None = None) -> Self:
        parser = argparse.ArgumentParser()
        _ = parser.add_argument(
            "--column",
            type=int,
            default=80,
            help="wrapping column to use for diagnostics and code actions",
        )
        args = parser.parse_args(argv)
        return cls(column=cast(int, args.column))

    def run(self) -> int:
        server = LspServer.create(column=self.column)
        server.start_io()
        return 0


@dataclass(frozen=True, kw_only=True)
class BlockCommentFormat:
    starts: tuple[str, ...]
    middle: str
    end: str
    closing: str
    reject_nested: bool = False


@dataclass(frozen=True, kw_only=True)
class LanguageFormat:
    language_ids: tuple[str, ...]
    suffixes: tuple[str, ...]
    mode: LanguageMode = "comments"
    line_markers: tuple[str, ...] = ()
    block_markers: tuple[BlockCommentFormat, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CommentLine:
    line: int
    indent: str
    marker: str
    content: str

    @property
    def prefix(self) -> str:
        return f"{self.indent}{self.marker} "


@dataclass(frozen=True, kw_only=True)
class BlockComment:
    start_line: int
    end_line: int
    indent: str
    start_marker: str
    after_start: str
    comment_format: BlockCommentFormat

    def with_end_line(self, end_line: int) -> BlockComment:
        return BlockComment(
            start_line=self.start_line,
            end_line=end_line,
            indent=self.indent,
            start_marker=self.start_marker,
            after_start=self.after_start,
            comment_format=self.comment_format,
        )


@dataclass(frozen=True, kw_only=True)
class WrapEdit:
    start_line: int
    end_line: int
    old_lines: tuple[str, ...]
    new_lines: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.old_lines != self.new_lines

    @property
    def diagnostic_range(self) -> types.Range:
        return types.Range(
            start=types.Position(line=self.start_line, character=0),
            end=types.Position(
                line=self.end_line,
                character=len(self.old_lines[-1]) if self.old_lines else 0,
            ),
        )

    @property
    def lsp_text_edit(self) -> types.TextEdit:
        return types.TextEdit(
            range=self.diagnostic_range,
            new_text="\n".join(self.new_lines),
        )

    def intersects(self, selected: types.Range) -> bool:
        return (
            self.start_line <= selected.end.line
            and selected.start.line <= self.end_line
        )


class Languages:
    C_BLOCK: ClassVar[BlockCommentFormat] = BlockCommentFormat(
        starts=("/**", "/*!", "/*"),
        middle=" * ",
        end="*/",
        closing=" */",
    )
    OCAML_BLOCK: ClassVar[BlockCommentFormat] = BlockCommentFormat(
        starts=("(**", "(*"),
        middle=" * ",
        end="*)",
        closing=" *)",
        reject_nested=True,
    )
    REGISTRY: ClassVar[tuple[LanguageFormat, ...]] = (
        LanguageFormat(
            language_ids=("plaintext", "text"),
            suffixes=(".txt",),
            mode="plain-text",
        ),
        LanguageFormat(
            language_ids=("python",),
            suffixes=(".py", ".pyw"),
            line_markers=("#",),
        ),
        LanguageFormat(
            language_ids=("shellscript", "shell", "bash", "sh", "zsh", "fish"),
            suffixes=(".sh", ".bash", ".zsh", ".fish"),
            line_markers=("#",),
        ),
        LanguageFormat(
            language_ids=("rust",),
            suffixes=(".rs",),
            line_markers=("///", "//!", "//"),
            block_markers=(C_BLOCK,),
        ),
        LanguageFormat(
            language_ids=("go",),
            suffixes=(".go",),
            line_markers=("//",),
            block_markers=(C_BLOCK,),
        ),
        LanguageFormat(
            language_ids=("c", "cpp", "cuda-cpp"),
            suffixes=(".c", ".h", ".cpp", ".cxx", ".cc", ".hpp", ".hh", ".hxx"),
            line_markers=("///", "//!", "//"),
            block_markers=(C_BLOCK,),
        ),
        LanguageFormat(
            language_ids=("ocaml",),
            suffixes=(".ml", ".mli", ".mll", ".mly"),
            block_markers=(OCAML_BLOCK,),
        ),
        LanguageFormat(
            language_ids=(
                "javascript",
                "typescript",
                "javascriptreact",
                "typescriptreact",
            ),
            suffixes=(".js", ".jsx", ".ts", ".tsx"),
            line_markers=("///", "//!", "//"),
            block_markers=(C_BLOCK,),
        ),
    )

    @classmethod
    def for_document(cls, *, uri: str, language_id: str | None) -> LanguageFormat:
        if language_id:
            for item in cls.REGISTRY:
                if language_id in item.language_ids:
                    return item

        suffix = Path(uri).suffix.lower()
        for item in cls.REGISTRY:
            if suffix in item.suffixes:
                return item

        return LanguageFormat(language_ids=(), suffixes=())


class Text:
    @staticmethod
    def visual_len(value: str, *, tab_width: int = 4) -> int:
        column = 0
        for char in value:
            if char == "\t":
                column += tab_width - column % tab_width
            else:
                column += 1
        return column

    @staticmethod
    def split_source(source: str) -> tuple[str, ...]:
        return tuple(source.splitlines())


class Paragraphs:
    @staticmethod
    def wrap(
        *,
        contents: tuple[str, ...],
        prefix: str,
        column: int,
    ) -> tuple[str, ...]:
        """Wrap paragraph content and add the prefix to every output line.

        >>> Paragraphs.wrap(contents=("one two three four five",), prefix="# ", column=14)
        ('# one two', '# three four', '# five')
        >>> Paragraphs.wrap(contents=("one two", "", "three four"), prefix="// ", column=80)
        ('// one two', '//', '// three four')
        """
        body_width = max(1, column - Text.visual_len(prefix))
        wrapper = textwrap.TextWrapper(
            width=body_width,
            break_long_words=False,
            break_on_hyphens=False,
            drop_whitespace=True,
        )

        wrapped: list[str] = []
        paragraph: list[str] = []
        for content in contents:
            if content.strip():
                paragraph.append(content.strip())
                continue

            Paragraphs._flush_paragraph(
                paragraph=paragraph, wrapped=wrapped, wrapper=wrapper, prefix=prefix
            )
            wrapped.append(prefix.rstrip())

        Paragraphs._flush_paragraph(
            paragraph=paragraph, wrapped=wrapped, wrapper=wrapper, prefix=prefix
        )
        return tuple(wrapped)

    @staticmethod
    def _flush_paragraph(
        *,
        paragraph: list[str],
        wrapped: list[str],
        wrapper: textwrap.TextWrapper,
        prefix: str,
    ) -> None:
        if not paragraph:
            return

        text = " ".join(paragraph)
        wrapped.extend(f"{prefix}{line}" for line in wrapper.wrap(text))
        paragraph.clear()


class LineComments:
    LINE_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?P<indent>\s*)(?P<marker>\S+)(?P<rest>.*)$"
    )
    DECORATIVE_CHARS: ClassVar[frozenset[str]] = frozenset("#/%;-=*_~`'\".,:! ")

    @classmethod
    def edits(
        cls, *, lines: tuple[str, ...], markers: tuple[str, ...], column: int
    ) -> tuple[WrapEdit, ...]:
        edits: list[WrapEdit] = []
        index = 0
        ordered_markers = tuple(sorted(markers, key=len, reverse=True))
        while index < len(lines):
            comment = cls._parse_line(
                line_number=index, text=lines[index], markers=ordered_markers
            )
            if comment is None:
                index += 1
                continue

            block = [comment]
            index += 1
            while index < len(lines):
                next_comment = cls._parse_line(
                    line_number=index, text=lines[index], markers=ordered_markers
                )
                if next_comment is None:
                    break
                if (
                    next_comment.indent != comment.indent
                    or next_comment.marker != comment.marker
                ):
                    break
                block.append(next_comment)
                index += 1

            if edit := cls._edit_for_block(
                lines=lines, block=tuple(block), column=column
            ):
                edits.append(edit)

        return tuple(edits)

    @classmethod
    def _parse_line(
        cls,
        *,
        line_number: int,
        text: str,
        markers: tuple[str, ...],
    ) -> CommentLine | None:
        """Parse full-line comments while preferring the longest marker.

        >>> LineComments._parse_line(line_number=0, text="  /// docs", markers=("///", "//"))
        CommentLine(line=0, indent='  ', marker='///', content='docs')
        >>> LineComments._parse_line(line_number=0, text="let x = 1 // no", markers=("//",)) is None
        True
        >>> LineComments._parse_line(line_number=0, text="///////", markers=("///", "//")) is None
        True
        """
        match = cls.LINE_RE.match(text)
        if match is None:
            return None

        candidate = match.group("marker")
        marker = next((item for item in markers if candidate.startswith(item)), None)
        if marker is None:
            return None
        if candidate != marker:
            rest = f"{candidate[len(marker) :]}{match.group('rest')}"
        else:
            rest = match.group("rest")
        if cls._is_decorative(marker=marker, rest=rest):
            return None

        return CommentLine(
            line=line_number,
            indent=match.group("indent"),
            marker=marker,
            content=rest.lstrip(),
        )

    @classmethod
    def _is_decorative(cls, *, marker: str, rest: str) -> bool:
        content = rest.strip()
        if not content:
            return False

        decorative_chars = cls.DECORATIVE_CHARS | frozenset(marker)
        return all(char in decorative_chars for char in content)

    @staticmethod
    def _edit_for_block(
        *, lines: tuple[str, ...], block: tuple[CommentLine, ...], column: int
    ) -> WrapEdit | None:
        if not any(line.content.strip() for line in block):
            return None

        first = block[0]
        old_lines = tuple(lines[item.line] for item in block)
        contents = tuple(item.content for item in block)
        new_lines = Paragraphs.wrap(
            contents=contents, prefix=first.prefix, column=column
        )
        edit = WrapEdit(
            start_line=first.line,
            end_line=block[-1].line,
            old_lines=old_lines,
            new_lines=new_lines,
        )
        return edit if edit.changed else None


class BlockComments:
    @classmethod
    def edits(
        cls,
        *,
        lines: tuple[str, ...],
        formats: tuple[BlockCommentFormat, ...],
        column: int,
    ) -> tuple[WrapEdit, ...]:
        """Find block comments that can be rewrapped.

        >>> edits = BlockComments.edits(
        ...     lines=("/* one two three four five */",),
        ...     formats=(Languages.C_BLOCK,),
        ...     column=14,
        ... )
        >>> edits[0].new_lines
        ('/*', ' * one two', ' * three four', ' * five', ' */')
        >>> BlockComments.edits(
        ...     lines=("/* one two three */ int x;",),
        ...     formats=(Languages.C_BLOCK,),
        ...     column=14,
        ... )
        ()
        >>> BlockComments.edits(
        ...     lines=("/** one two three four five */",),
        ...     formats=(Languages.C_BLOCK,),
        ...     column=14,
        ... )[0].new_lines[0]
        '/**'
        >>> BlockComments.edits(
        ...     lines=("(* outer", "   (* inner *)", "   outer *)"),
        ...     formats=(Languages.OCAML_BLOCK,),
        ...     column=14,
        ... )
        ()
        """
        edits: list[WrapEdit] = []
        index = 0
        while index < len(lines):
            found = cls._find_start(
                line_number=index,
                line=lines[index],
                formats=formats,
            )
            if found is None:
                index += 1
                continue

            end_line = cls._find_end_line(
                lines=lines,
                start_line=index,
                comment=found,
            )
            if end_line is None:
                index = cls._skip_rejected_block(
                    lines=lines,
                    start_line=index,
                    comment=found,
                )
                continue

            if edit := cls._edit_for_block(
                lines=lines,
                comment=found.with_end_line(end_line),
                column=column,
            ):
                edits.append(edit)
            index = end_line + 1

        return tuple(edits)

    @classmethod
    def _skip_rejected_block(
        cls,
        *,
        lines: tuple[str, ...],
        start_line: int,
        comment: BlockComment,
    ) -> int:
        if not comment.comment_format.reject_nested:
            return start_line + 1

        for line_number in range(start_line + 1, len(lines)):
            if cls._line_has_clean_end(
                lines[line_number],
                comment_format=comment.comment_format,
            ):
                return line_number + 1
        return start_line + 1

    @classmethod
    def _find_start(
        cls,
        *,
        line_number: int,
        line: str,
        formats: tuple[BlockCommentFormat, ...],
    ) -> BlockComment | None:
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        for comment_format in formats:
            start_marker = cls._matching_start(stripped, comment_format=comment_format)
            if start_marker is not None:
                return BlockComment(
                    start_line=line_number,
                    end_line=0,
                    indent=indent,
                    start_marker=start_marker,
                    after_start=stripped[len(start_marker) :].strip(),
                    comment_format=comment_format,
                )
        return None

    @staticmethod
    def _matching_start(line: str, *, comment_format: BlockCommentFormat) -> str | None:
        for start in sorted(comment_format.starts, key=len, reverse=True):
            if line.startswith(start):
                return start
        return None

    @classmethod
    def _find_end_line(
        cls,
        *,
        lines: tuple[str, ...],
        start_line: int,
        comment: BlockComment,
    ) -> int | None:
        if cls._has_nested_start(
            comment.after_start,
            comment_format=comment.comment_format,
        ):
            return None
        if cls._line_has_clean_end(
            comment.after_start, comment_format=comment.comment_format
        ):
            return start_line

        for line_number in range(start_line + 1, len(lines)):
            if cls._has_nested_start(
                lines[line_number],
                comment_format=comment.comment_format,
            ):
                return None
            if cls._line_has_clean_end(
                lines[line_number],
                comment_format=comment.comment_format,
            ):
                return line_number
        return None

    @staticmethod
    def _has_nested_start(line: str, *, comment_format: BlockCommentFormat) -> bool:
        return comment_format.reject_nested and any(
            start in line for start in comment_format.starts
        )

    @staticmethod
    def _line_has_clean_end(line: str, *, comment_format: BlockCommentFormat) -> bool:
        before_end, separator, after_end = line.partition(comment_format.end)
        _ = before_end
        return bool(separator) and not after_end.strip()

    @classmethod
    def _edit_for_block(
        cls,
        *,
        lines: tuple[str, ...],
        comment: BlockComment,
        column: int,
    ) -> WrapEdit | None:
        contents = cls._contents(
            lines=lines,
            comment=comment,
        )
        if not any(line.strip() for line in contents):
            return None

        prefix = f"{comment.indent}{comment.comment_format.middle}"
        wrapped = Paragraphs.wrap(contents=contents, prefix=prefix, column=column)
        new_lines = (
            f"{comment.indent}{comment.start_marker}",
            *wrapped,
            f"{comment.indent}{comment.comment_format.closing}",
        )
        edit = WrapEdit(
            start_line=comment.start_line,
            end_line=comment.end_line,
            old_lines=tuple(lines[comment.start_line : comment.end_line + 1]),
            new_lines=new_lines,
        )
        return edit if edit.changed else None

    @classmethod
    def _contents(
        cls,
        *,
        lines: tuple[str, ...],
        comment: BlockComment,
    ) -> tuple[str, ...]:
        if comment.start_line == comment.end_line:
            content = comment.after_start.split(
                comment.comment_format.end,
                maxsplit=1,
            )[0].strip()
            return (content,) if content else ()

        contents: list[str] = []
        if comment.after_start:
            contents.append(comment.after_start)

        contents.extend(
            cls._middle_content(
                lines[line_number],
                comment_format=comment.comment_format,
            )
            for line_number in range(comment.start_line + 1, comment.end_line)
        )

        before_end = (
            lines[comment.end_line]
            .split(
                comment.comment_format.end,
                maxsplit=1,
            )[0]
            .strip()
        )
        if before_end:
            contents.append(
                cls._middle_content(
                    before_end,
                    comment_format=comment.comment_format,
                )
            )
        return tuple(contents)

    @staticmethod
    def _middle_content(line: str, *, comment_format: BlockCommentFormat) -> str:
        stripped = line.strip()
        marker = comment_format.middle.strip()
        if marker and stripped.startswith(marker):
            return stripped[len(marker) :].lstrip()
        return stripped


class PlainText:
    @classmethod
    def edits(cls, *, lines: tuple[str, ...], column: int) -> tuple[WrapEdit, ...]:
        edits: list[WrapEdit] = []
        index = 0
        while index < len(lines):
            if not cls._is_plain_line(lines[index]):
                index += 1
                continue

            start = index
            block: list[str] = []
            while index < len(lines) and cls._is_plain_line(lines[index]):
                block.append(lines[index])
                index += 1

            new_lines = Paragraphs.wrap(contents=tuple(block), prefix="", column=column)
            edit = WrapEdit(
                start_line=start,
                end_line=index - 1,
                old_lines=tuple(block),
                new_lines=new_lines,
            )
            if edit.changed:
                edits.append(edit)

        return tuple(edits)

    @staticmethod
    def _is_plain_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        return not stripped.startswith(("#", "-", "*", ">", "```"))


class Rewrapper:
    @classmethod
    def edits(
        cls,
        *,
        source: str,
        uri: str,
        language_id: str | None,
        column: int,
    ) -> tuple[WrapEdit, ...]:
        """Return edits that would rewrap supported comments or text.

        >>> edits = Rewrapper.edits(
        ...     source="# one two three four five\\n",
        ...     uri="file:///x.py",
        ...     language_id="python",
        ...     column=14,
        ... )
        >>> edits[0].new_lines
        ('# one two', '# three four', '# five')
        >>> edits[0].diagnostic_range.end.character
        25
        >>> Rewrapper.edits(
        ...     source="let value = this should not be plain text\\n",
        ...     uri="file:///x.unknown",
        ...     language_id="unknown",
        ...     column=20,
        ... )
        ()
        """
        if column < 1:
            return ()

        lines = Text.split_source(source)
        language_format = Languages.for_document(uri=uri, language_id=language_id)
        edits: list[WrapEdit] = []
        match language_format.mode:
            case "comments":
                edits.extend(
                    LineComments.edits(
                        lines=lines,
                        markers=language_format.line_markers,
                        column=column,
                    ),
                )
                edits.extend(
                    BlockComments.edits(
                        lines=lines,
                        formats=language_format.block_markers,
                        column=column,
                    ),
                )
            case "plain-text":
                edits.extend(PlainText.edits(lines=lines, column=column))

        return tuple(sorted(edits, key=lambda edit: edit.start_line))


class LspDiagnostics:
    MESSAGE: ClassVar[str] = "Text can be rewrapped"
    SOURCE: ClassVar[str] = "lewrap"

    @classmethod
    def from_edit(cls, edit: WrapEdit) -> types.Diagnostic:
        return types.Diagnostic(
            range=edit.diagnostic_range,
            message=cls.MESSAGE,
            severity=types.DiagnosticSeverity.Information,
            source=cls.SOURCE,
        )


class LspServer:
    NAME: ClassVar[str] = "lewrap"
    VERSION: ClassVar[str] = "0.1.0"

    @classmethod
    def create(cls, *, column: int) -> LanguageServer:
        server = LanguageServer(cls.NAME, cls.VERSION)

        def did_open(
            ls: LanguageServer, params: types.DidOpenTextDocumentParams
        ) -> None:
            LspServer.publish(ls=ls, uri=params.text_document.uri, column=column)

        def did_change(
            ls: LanguageServer, params: types.DidChangeTextDocumentParams
        ) -> None:
            LspServer.publish(ls=ls, uri=params.text_document.uri, column=column)

        def did_save(
            ls: LanguageServer, params: types.DidSaveTextDocumentParams
        ) -> None:
            LspServer.publish(ls=ls, uri=params.text_document.uri, column=column)

        def did_close(
            ls: LanguageServer, params: types.DidCloseTextDocumentParams
        ) -> None:
            LspServer.clear(ls=ls, uri=params.text_document.uri)

        def code_action(
            ls: LanguageServer, params: types.CodeActionParams
        ) -> list[types.CodeAction]:
            document = ls.workspace.get_text_document(params.text_document.uri)
            edits = Rewrapper.edits(
                source=document.source,
                uri=document.uri,
                language_id=document.language_id,
                column=column,
            )
            selected_edits = tuple(
                edit for edit in edits if edit.intersects(params.range)
            )
            return [
                types.CodeAction(
                    title="Rewrap comment/text",
                    kind=types.CodeActionKind.QuickFix,
                    diagnostics=[LspDiagnostics.from_edit(edit)],
                    edit=types.WorkspaceEdit(
                        changes={document.uri: [edit.lsp_text_edit]}
                    ),
                    is_preferred=True,
                )
                for edit in selected_edits
            ]

        _ = server.feature(types.TEXT_DOCUMENT_DID_OPEN)(did_open)
        _ = server.feature(types.TEXT_DOCUMENT_DID_CHANGE)(did_change)
        _ = server.feature(types.TEXT_DOCUMENT_DID_SAVE)(did_save)
        _ = server.feature(types.TEXT_DOCUMENT_DID_CLOSE)(did_close)
        _ = server.feature(
            types.TEXT_DOCUMENT_CODE_ACTION,
            types.CodeActionOptions(code_action_kinds=[types.CodeActionKind.QuickFix]),
        )(code_action)
        return server

    @staticmethod
    def publish(*, ls: LanguageServer, uri: str, column: int) -> None:
        document = ls.workspace.get_text_document(uri)
        edits = Rewrapper.edits(
            source=document.source,
            uri=document.uri,
            language_id=document.language_id,
            column=column,
        )
        diagnostics = [LspDiagnostics.from_edit(edit) for edit in edits]
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics),
        )

    @staticmethod
    def clear(*, ls: LanguageServer, uri: str) -> None:
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=[]),
        )


if __name__ == "__main__":
    raise SystemExit(Args.from_args().run())
