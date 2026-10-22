"""Conservative mechanical evidence that a PR changes executable behavior.

This check is intentionally not a correctness proof. The independent exact-head
reviewer still has to verify each linked-issue requirement and its tests.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
import shlex
from collections.abc import Callable, Iterable
from urllib.parse import quote

DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
BEHAVIORAL_FILENAMES = frozenset({"dockerfile", "containerfile", "makefile", "gnumakefile"})
SOURCE_SUFFIXES = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".sh", ".sql", ".html", ".css", ".scss", ".vue", ".svelte",
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg",
)
TYPE_LINE = re.compile(
    r"(?im)^\s*(?:\*\*)?(?:issue\s+type|deliverable\s+type|"
    r"work\s+type)\s*:(?:\*\*)?\s*(?:\*\*)?"
    r"(docs-only|documentation-only|documentation|investigation|"
    r"planning|prd|acceptance-only|test-only)(?:\*\*)?\s*$"
)
PATCH_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


def is_implementation_issue(issue_body: str | None) -> bool:
    """Classify using a structured declaration, not arbitrary issue prose.

    Args:
        issue_body: Authoritative linked issue description.

    Returns:
        True by default, or False for an explicitly typed non-code ticket.
    """
    body = issue_body or ""
    match = TYPE_LINE.search(body)
    return match is None


def _is_docs_path(path: str) -> bool:
    """Whether the file can only serve as documentation."""
    normalized = path.lower().strip()
    return normalized.startswith("docs/") or normalized.endswith(DOC_SUFFIXES)


def _is_test_path(path: str) -> bool:
    """Whether a file contains tests rather than deliverable production code."""
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith(("tests/", "frontend/src/test/", "frontend/src/unit/"))
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def substantive_changed_files(changed_files: Iterable[str]) -> list[str]:
    """Find candidate behavioral source files, excluding docs and tests.

    Args:
        changed_files: Paths reported by the reviewed PR diff.

    Returns:
        Source file paths that could contain the requested implementation.
    """
    return [
        path for path in changed_files
        if path.strip()
        and (path.lower().endswith(SOURCE_SUFFIXES)
             or path.lower().rsplit("/", 1)[-1] in BEHAVIORAL_FILENAMES
             or path.lower().endswith((".dockerfile", ".containerfile")))
        and not _is_docs_path(path)
        and not _is_test_path(path)
    ]


class _WithoutDocstrings(ast.NodeTransformer):
    """Remove only actual Python documentation expression nodes."""

    def visit(self, node: ast.AST) -> ast.AST:
        """Strip leading docstrings while preserving behavioral string literals.

        Args:
            node: Python syntax node being traversed.

        Returns:
            Node with only documentation expressions removed.
        """
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
        return super().visit(node)



def _shell_continuations(source: str) -> str:
    """Remove Bash continuations outside literal single quotes only."""
    result: list[str] = []
    quote = ""
    index = 0
    while index < len(source):
        char = source[index]
        if not quote and source.startswith("$'", index):
            result.append("$'")
            quote = "ansi"
            index += 2
            continue
        if quote == "ansi":
            if char == "\\" and index + 1 < len(source):
                result.extend((char, source[index + 1]))
                index += 2
                continue
            if char == "'":
                quote = ""
            result.append(char)
            index += 1
            continue
        if char == "\\" and quote != "'" and index + 1 < len(source):
            following = source[index + 1]
            if following != "\n":
                result.extend((char, following))
            index += 2
            continue
        if char in {"'", '\"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
        result.append(char)
        index += 1
    return "".join(result)


def _skip_group(values: list[str], position: int, opening: str, closing: str) -> int:
    """Return the token after a balanced group, or -1 for incomplete syntax."""
    depth = 0
    for index in range(position, len(values)):
        depth += (values[index] == opening) - (values[index] == closing)
        if depth == 0:
            return index + 1
    return -1


def _async_production(values: list[str], position: int) -> bool:
    """Recognize JavaScript/TypeScript async functions and typed/generic arrows."""
    token = values[position]
    if token == "function":
        return True
    if token == "<":
        position = _skip_group(values, position, "<", ">")
        if position < 0 or position >= len(values):
            return False
        token = values[position]
    if token != "(":
        return position + 1 < len(values) and values[position + 1] == "=>"
    after = _skip_group(values, position, "(", ")")
    if after < 0 or after >= len(values):
        return False
    if values[after] == "=>":
        return True
    if values[after] != ":":
        return False
    # A TypeScript return annotation may contain generics, object types,
    # tuples and nested function types. Only its outer arrow ends the type.
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    for value in values[after + 1:]:
        if value == "=>" and not stack:
            return True
        if value in pairs:
            stack.append(pairs[value])
        elif stack and value == stack[-1]:
            stack.pop()
        elif not stack and value in {";", "=", ")", "}"}:
            return False
    return False



SHELL_DYNAMIC = re.compile(
    r"\$\{(?:[^{}]|\{[^{}]*\})*\}|`(?:\\.|[^`\\])*`"
    r"|\$\((?:[^()]|\([^()]*\))*\)", re.DOTALL,
)
ARITHMETIC_TOKEN = re.compile(
    r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""
    r"|[\w$]+|\+\+|--|<<|>>|&&|\|\||==|!=|<=|>=|[^\s]", re.DOTALL,
)


def _shell_parts(value: str, path: str) -> str:
    """Normalize embedded executable substitutions without erasing literal spaces."""
    def normalize(match: re.Match[str]) -> str:
        """Leave escaped dollar signs/backticks literal."""
        prefix = value[:match.start()]
        backslashes = len(prefix) - len(prefix.rstrip("\\"))
        if backslashes % 2:
            return match.group()
        return _shell_value(match.group(), path)

    return SHELL_DYNAMIC.sub(normalize, value)


def _shell_value(value: str, path: str) -> str:
    """Distinguish literal data from arithmetic and command substitution syntax."""
    if value.startswith("${"):
        substring = re.fullmatch(
            r"\$\{(!?(?:[A-Za-z_]\w*|[0-9]+|[@*])(?:\[[^]]*\])?):(?![-+=?])(.*)\}",
            value, re.DOTALL
        )
        if substring:
            return repr(("substring", substring[1], ARITHMETIC_TOKEN.findall(substring[2])))
        return repr(("parameter", _shell_parts(value[2:-1], path)))
    if value.startswith("$((") and value.endswith("))"):
        return repr(("arithmetic", ARITHMETIC_TOKEN.findall(value[3:-2])))
    if value.startswith("$("):
        return repr(("command", _code_tokens(value[2:-1], path)))
    if value.startswith("`"):
        return repr(("command", _code_tokens(value[1:-1], path)))
    if value.startswith('\"'):
        return repr(("double-quoted", _shell_parts(value[1:-1], path)))
    return value


HEREDOC_START = re.compile(
    r"(?<!<)<<(?!<)(?P<strip>-)?[ \t]*"
    r"(?P<word>(?:'[^']*'|\"(?:\\.|[^\"\\])*\"|\\.|[^\s;|&()<>'\"\\])+)",
)


def _heredoc_data(value: str, quoted: bool, path: str) -> str:
    """Preserve input bytes, normalizing substitutions only in unquoted heredocs."""
    if quoted:
        return value
    # Quotes in a heredoc body are data, not shell quoting. Only an
    # unescaped backslash-newline is a continuation before substitution.
    parts: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            if value[index + 1] != "\n":
                parts.extend((value[index], value[index + 1]))
            index += 2
        else:
            parts.append(value[index])
            index += 1
    return _shell_parts("".join(parts), path)


def _shell_heredocs(source: str, path: str) -> tuple[str, list[tuple[bool, str]]]:
    """Extract heredoc input before command/comment lexing, including inside $()."""
    lines = source.splitlines(keepends=True)
    output: list[str] = []
    bodies: list[tuple[bool, str]] = []
    marker = "\ue002"
    while marker in source:
        marker += "\ue002"
    quote = ""
    contexts: list[tuple[str, int, str]] = []
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        pending: list[tuple[str, bool, bool]] = []
        rebuilt: list[str] = []
        index = 0
        while index < len(line):
            char = line[index]
            if char == "\\" and quote != "'" and index + 1 < len(line):
                rebuilt.append(line[index:index + 2])
                index += 2
                continue
            arithmetic = (quote not in {"'", "ansi"} and line.startswith("$((", index))
            arithmetic |= not quote and line.startswith("((", index)
            if arithmetic:
                opening = "$((" if line.startswith("$((", index) else "(("
                contexts.append((quote, 2, "arith)"))
                quote = ""
                rebuilt.append(opening)
                index += len(opening)
                continue
            if quote not in {"'", "ansi"} and line.startswith("$(", index):
                contexts.append((quote, 1, ")"))
                quote = ""
                rebuilt.append("$(")
                index += 2
                continue
            if char == "`" and quote not in {"'", "ansi"}:
                if contexts and contexts[-1][2] == "`" and not quote:
                    quote, _depth, _closing = contexts.pop()
                else:
                    contexts.append((quote, 1, "`"))
                    quote = ""
                rebuilt.append(char)
                index += 1
                continue
            if (not quote and contexts and contexts[-1][2] in {")", "arith)"}
                    and char in {"(", ")"}):
                outer, depth, closing = contexts[-1]
                depth += 1 if char == "(" else -1
                if depth:
                    contexts[-1] = (outer, depth, closing)
                else:
                    contexts.pop()
                    quote = outer
            if not quote and line.startswith("$'", index):
                quote = "ansi"
                rebuilt.append("$'")
                index += 2
                continue
            comment_boundary = (index == 0 or line[index - 1].isspace()
                                or line[index - 1] in ";|&()")
            if not quote and char == "#" and comment_boundary:
                rebuilt.append(line[index:])
                break
            redirect_allowed = not quote and (not contexts or contexts[-1][2] != "arith)")
            match = HEREDOC_START.match(line, index) if redirect_allowed else None
            if match:
                word = match["word"]
                delimiter = "".join(shlex.split(word, posix=True))
                quoted = any(char in word for char in ("'", '\"', "\\"))
                pending.append((delimiter, quoted, bool(match["strip"])))
                rebuilt.append(f" {marker}{len(bodies) + len(pending) - 1}")
                index = match.end()
                continue
            if char in {"'", '\"'}:
                if not quote:
                    quote = char
                elif quote == char or quote == "ansi" and char == "'":
                    quote = ""
            rebuilt.append(char)
            index += 1
        output.append("".join(rebuilt))
        line_index += 1
        for delimiter, quoted, strip_tabs in pending:
            data: list[str] = []
            while line_index < len(lines):
                body_line = lines[line_index]
                line_index += 1
                if strip_tabs:
                    body_line = body_line.lstrip("\t")
                if body_line.rstrip("\n") == delimiter:
                    break
                data.append(body_line)
            else:
                raise ValueError("incomplete shell heredoc")
            bodies.append((quoted, _heredoc_data("".join(data), quoted, path)))
    return "".join(output), bodies

def _code_tokens(source: str, path: str) -> str:
    """Compare complete source, preserving literals and ignoring comments."""
    if path.lower().endswith(".py"):
        tree = _WithoutDocstrings().visit(ast.parse(source))
        return ast.dump(tree, include_attributes=False)
    heredocs: list[tuple[bool, str]] = []
    if path.lower().endswith(".sh"):
        source, heredocs = _shell_heredocs(source, path)
    name = path.lower().rsplit("/", 1)[-1]
    hash_comments = path.lower().endswith((".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg"))
    hash_comments = hash_comments or name in BEHAVIORAL_FILENAMES
    # Match literals before comment delimiters so URLs, SQL strings, and
    # whitespace within values remain behavioral. Full source provides the
    # lexical context even when a changed line is deep inside a block comment.
    comments = r"\#[^\n]*" if hash_comments else r"/\*.*?\*/|//[^\n]*"
    if path.lower().endswith(".sh"):
        # Bash starts comments at word boundaries, not inside ${#array[@]},
        # ${value#prefix}, $# or unquoted words containing a literal #.
        comments = r"(?<![^\s;|&()])\#[^\n]*"
    if path.lower().endswith(".sql"):
        comments = r"/\*.*?\*/|--[^\n]*"
    if path.lower().endswith((".html", ".vue", ".svelte")):
        comments += r"|<!--.*?-->"
    expansion = r"(?P<expansion>\$\{(?:[^{}]|\{[^{}]*\})*\})|" if path.endswith(".sh") else ""
    pattern = re.compile(
        expansion +
        r"(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`)"
        + r"|(?P<comment>" + comments + r")|(?P<space>\s+)"
        + r"|(?P<code>[\w$]+|\+\+|--|=>|===|!==|==|!=|&&|\|\||.)",
        re.DOTALL,
    )
    if path.lower().endswith((".yml", ".yaml")) or name in {"makefile", "gnumakefile"}:
        # Indentation/newlines carry executable structure in these formats.
        code = "".join(match.group() for match in pattern.finditer(source)
                       if match.lastgroup != "comment")
        return repr([line.rstrip() for line in code.splitlines() if line.strip()])
    matches = [match for match in pattern.finditer(source) if match.lastgroup != "comment"]
    if path.lower().endswith(".sh"):
        code = _shell_continuations("".join(match.group() for match in matches))
        # shlex does not understand Bash $'...' quoting. Mask complete
        # literals/expansions so their spaces and escapes remain atomic, even
        # when quoted/unquoted word segments are concatenated.
        marker = "\ue000"
        while marker in code:
            marker += "\ue000"
        literals: dict[str, str] = {}

        def protect(match: re.Match[str]) -> str:
            """Keep language literals out of shlex's word splitting."""
            if match.lastgroup not in {"string", "expansion"}:
                return match.group()
            key = f"{marker}{len(literals)}{marker}"
            literals[key] = _shell_value(match.group(), path)
            return key

        masked = pattern.sub(protect, code)
        lexer = shlex.shlex(masked, posix=False, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        commands: list[str] = []
        for token in lexer:
            if token.strip(";\n") == "":
                if commands and commands[-1] != ";":
                    commands.append(";")
            else:
                for key, value in literals.items():
                    token = token.replace(key, value)
                commands.append(token)
        if commands and commands[-1] == ";":
            commands.pop()
        return repr((commands, heredocs))
    tokens: list[str] = []
    significant = [index for index, match in enumerate(matches) if match.lastgroup != "space"]
    values = [matches[index].group() for index in significant]
    previous = ""
    previous_end = 0
    braces = 0
    statement: list[str] = []
    css = path.lower().endswith((".css", ".scss"))
    javascript = path.lower().endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))
    for position, index in enumerate(significant):
        match = matches[index]
        token = match.group()
        gap = "".join(part.group() for part in matches[previous_end:index])
        # CSS descendant selectors differ from adjoining simple selectors.
        property_value = (braces > 0 and len(statement) > 1 and statement[1] == ":"
                          and bool(re.fullmatch(r"[\w-]+", statement[0])))
        if css and gap and previous and not property_value and token in {".", "#", "[", ":", "*"}:
            property_colon = (token == ":" and braces > 0 and len(statement) == 1
                              and bool(re.fullmatch(r"[\w-]+", statement[0])))
            if not property_colon and previous not in {"{", "}", ";", ":", ",", ">", "+", "~"}:
                tokens.append("DESCENDANT")
        # JavaScript's restricted productions and postfix operators give
        # line terminators meaning; ordinary indentation/reflow remains ignored.
        operand_end = bool(re.fullmatch(r"[\w$]+", previous)) or previous in {
            ")", "]", "}",
        } or previous.startswith(("'", '\"', "`"))
        operand_end = operand_end and previous not in {
            "await", "new", "typeof", "void", "delete", "instanceof", "in", "of",
            "throw", "return", "yield", "case", "else", "do",
        }
        restricted_newline = previous in {"return", "throw", "break", "continue", "yield"}
        restricted_newline |= previous == "async" and _async_production(values, position)
        restricted_newline |= token in {"++", "--"} and operand_end
        if javascript and "\n" in gap and restricted_newline:
            tokens.append("LINE_TERMINATOR")
        tokens.append(token)
        if token in {"{", "}", ";"}:
            statement = []
            braces += (token == "{") - (token == "}")
        else:
            statement.append(token)
        previous = token
        previous_end = index + 1
    return repr(tokens)


def _has_code_delta(patch: str, path: str) -> bool:
    """Compare old/new complete sources, failing closed on incomplete Python."""
    old: list[str] = []
    new: list[str] = []
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("@@"):
            # Production callers provide complete-file context. A partial
            # hunk cannot establish whether its first line is inside a comment.
            if in_hunk or not re.match(r"@@ -[01](?:,\d+)? \+[01](?:,\d+)? @@", line):
                return False
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            new.append(line[1:])
        elif in_hunk and line.startswith("-"):
            old.append(line[1:])
        elif in_hunk and line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
    if not in_hunk:
        return False
    try:
        return _code_tokens("\n".join(old), path) != _code_tokens("\n".join(new), path)
    except (SyntaxError, ValueError):
        return False


def _file_patches(diff_text: str) -> dict[str, str]:
    """Split a unified Git diff into authoritative per-file patches."""
    patches: dict[str, str] = {}
    current = ""
    lines: list[str] = []
    for line in diff_text.splitlines():
        header = PATCH_HEADER.match(line)
        if header:
            if current:
                patches[current] = "\n".join(lines)
            current = header.group(2)
            lines = [line]
        elif current:
            lines.append(line)
    if current:
        patches[current] = "\n".join(lines)
    return patches


def pr_delivers_implementation(
    issue_body: str | None,
    changed_files: Iterable[str],
    diff_text: str | None = None,
) -> tuple[bool, str]:
    """Reject non-delivering implementations without judging feature correctness.

    Args:
        issue_body: Exact linked-issue body.
        changed_files: File paths of the current PR head.
        diff_text: Full unified patch for that same PR head, if available.

    Returns:
        Whether the mechanical behavioral-diff prerequisite is satisfied,
        plus an actionable reason. Missing diff never counts as evidence.
    """
    if not is_implementation_issue(issue_body):
        return True, "explicit non-implementation issue type; documentation allowed"
    candidates = substantive_changed_files(changed_files)
    if not candidates:
        return False, "implementation issue has no changed production source files"
    if diff_text is None:
        return False, "unavailable source diff; cannot verify executable changes"
    patches = _file_patches(diff_text)
    for path in candidates:
        if path in patches and _has_code_delta(patches[path], path):
            return True, "production executable code changed; semantic review required"
    return (
        False,
        "only documentation, comments, docstrings or formatting changed "
        "in production source files; executable delivery is unverified",
    )



def _previous_source(current: str, patch: str) -> str:
    """Reverse GitHub's patch against complete head source, validating every hunk."""
    lines = current.splitlines()
    previous: list[str] = []
    cursor = 0
    entries = patch.splitlines()
    index = 0
    while index < len(entries):
        header = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", entries[index])
        if not header:
            raise RuntimeError("missing or malformed source patch hunk")
        start = int(header[3]) - (int(header[4] or 1) > 0)
        if start < cursor or start > len(lines):
            raise RuntimeError("source patch has invalid hunk coordinates")
        previous.extend(lines[cursor:start])
        cursor = start
        old_count = new_count = 0
        index += 1
        while index < len(entries) and not entries[index].startswith("@@"):
            entry = entries[index]
            index += 1
            if entry.startswith("\\ No newline"):
                continue
            if not entry or entry[0] not in " +-":
                raise RuntimeError("unrecognized source patch line")
            if entry[0] in " +":
                if cursor >= len(lines) or lines[cursor] != entry[1:]:
                    raise RuntimeError("source patch does not match immutable head")
                cursor += 1
                new_count += 1
            if entry[0] in " -":
                previous.append(entry[1:])
                old_count += 1
        if old_count != int(header[2] or 1) or new_count != int(header[4] or 1):
            raise RuntimeError("incomplete source patch; cannot verify delivery")
    previous.extend(lines[cursor:])
    return "\n".join(previous)


def complete_pr_diff(
    pr_number: int, expected_head: str, repo: str,
    run: Callable[[list[str]], str],
) -> tuple[list[str], str]:
    """Fetch full source context and reconstruct the PR's original base.

    Args:
        pr_number: Open or merged pull request number.
        expected_head: Commit being reviewed.
        repo: Repository owner/name.
        run: GitHub CLI reader that raises RuntimeError on failure.

    Returns:
        Changed paths and a unified diff with complete source context.

    Raises:
        RuntimeError: If the head changes or complete source is unavailable.
    """
    info = json.loads(run(["api", f"repos/{repo}/pulls/{pr_number}"]))
    if info["head"]["sha"] != expected_head:
        raise RuntimeError("PR head changed during implementation inspection")
    files = json.loads(run([
        "api", "--paginate", "--slurp", f"repos/{repo}/pulls/{pr_number}/files",
    ]))
    records = [record for page in files for record in page]
    paths = [record["filename"] for record in records]
    candidates = set(substantive_changed_files(paths))
    patches: list[str] = []
    for record in records:
        path = record["filename"]
        if path not in candidates or record["status"] == "renamed" and not record.get("changes"):
            continue
        patch = record.get("patch")
        if not isinstance(patch, str) or not patch:
            raise RuntimeError(f"source patch unavailable for {path}")
        new = "" if record["status"] == "removed" else run([
            "api", "-H", "Accept: application/vnd.github.raw+json",
            f"repos/{repo}/contents/{quote(path, safe='/')}?ref={expected_head}",
        ])
        # Reverse the original PR patch rather than comparing against current
        # main, which can already contain the merged head during closure.
        old = _previous_source(new, patch)
        patches.append(
            f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
                [line + "\n" for line in old.splitlines()],
                [line + "\n" for line in new.splitlines()],
                fromfile=f"a/{path}", tofile=f"b/{path}",
                n=max(len(old.splitlines()), len(new.splitlines())) + 1,
            ))
        )
    return paths, "\n".join(patches)
