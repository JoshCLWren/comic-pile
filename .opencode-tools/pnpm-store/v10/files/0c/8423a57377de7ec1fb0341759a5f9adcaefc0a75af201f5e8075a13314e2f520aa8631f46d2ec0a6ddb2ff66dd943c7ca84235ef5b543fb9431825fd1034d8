# unbash

The best bash parser in JavaScript. Fast, complete, typed.

![unbash logo][1]

[![NPM Version][3]][2] [![NPM Downloads][4]][2]

## Install

```sh
npm install unbash
```

## When to use unbash?

Use unbash when your input is Bash source: a pasted command, a complete script,
or shell source embedded in another format, and you need to inspect its
structure without executing it. It returns a typed, source-positioned AST.

Example use cases:

- Classify scripts for permission prompts, allowlists, or audit findings
- Collect executables and literal file, configuration, and dependency references
- Import or convert commands such as `curl` to code
- Build a shell portability checker using parse errors and AST analysis
- Attach diagnostics to generated or pasted Bash using source-positioned errors
  and partial trees
- Build explanations, visualizations, or structured previews of pipelines,
  conditions, expansions, and nested commands

## Supported syntax

unbash parses GNU Bash.

Currently at Bash v5.3 with non-interactive defaults including `extglob`
patterns. Supported syntax includes commands, control flows, pipelines,
redirects, assignments, compound statements, parameter and word expansions,
process and nested substitutions, coproc, heredocs, herestrings, nested and
generated syntax, etc. etc.

POSIX `sh` scripts parse as Bash. unbash does not gate syntax by version, i.e.
it accepts syntax that older Bash releases reject.

## Unsupported syntax

Other shell languages are not supported: zsh, ksh93, mksh, fish, PowerShell,
`cmd.exe`, csh, Bats test files. Such scripts may produce errors or a misleading
tree.

unbash is a tolerant parser: for malformed, incomplete or excessively nested
input, it recovers where possible and returns a best-effort partial AST with
source-positioned errors for what it detects while parsing.

To parse `process.argv` (`string[]`), use Node.js [`parseArgs`][5] or a library
such as [yargs][6] or [citty][7].

## Usage

```ts
import { parse } from "unbash";

const ast = parse('if [ -f "$1" ]; then cat "$1"; fi');
```

Result:

```js
{
  type: "Script",
  commands: [{
    type: "Statement",
    command: {
      type: "If",
      clause: { type: "CompoundList", commands: [ /* [ -f "$1" ] */ ] },
      then: { type: "CompoundList", commands: [ /* cat "$1" */ ] }
    }
  }]
}
```

See the full AST at [unbash.statichost.page#input=if \[ -f...][8]

Positions are zero-based UTF-16 code-unit offsets forming half-open `[pos, end)`
ranges into the source.

### Visit

`forEachChild(node, callback)` calls the callback once for each direct child,
including word parts such as expansions and the `script` of a substitution,
which resolve on first access. It does not recurse: call it from the callback to
descend, or skip the call to leave a subtree unresolved.

```ts
import { forEachChild, parse, type SyntaxNode } from "unbash";

const source = 'echo "$HOME" $(mktemp -d)';

function visit(node: SyntaxNode): void {
  if (node.type === "Command") console.log(source.slice(node.pos, node.end));
  forEachChild(node, visit);
}

visit(parse(source));
// echo "$HOME" $(mktemp -d)
// mktemp -d
```

The callback receives only the child and its return value is ignored. A nested
script reports its own `errors`, so check them while visiting. See [Migrating
from v5][9] for the node shapes and lazy fields.

### Print

Basic opinionated printer, does not preserve whitespace or comments (except
shebang):

```ts
import { parse } from "unbash";
import { print } from "unbash/printer";

const ast = parse('if [ -f "$1" ]; then cat "$1"; fi');
const script = print(ast);
```

Result:

```sh
if [ -f "$1" ]; then
  cat "$1"
fi
```

## unbash vs tree-sitter-bash

[tree-sitter-bash][10] is the right choice when you need:

- Incremental parsing
- CST output preserving all tokens and punctuation
- Error recovery with `ERROR` nodes and missing tokens

unbash provides:

- A typed, executable-syntax AST instead of a grammar CST
- A synchronous, zero-dependency TypeScript package with no native addon, WASM
  runtime, parser initialization, or query layer
- Structured word parts, arithmetic and test-expression trees, recursively
  parsed substitutions, and direct source positions
- Best-effort error recovery that preserves a partial AST and collects errors
- Also see [tree-sitter-bash gaps covered by unbash][11]

## unbash vs sh-syntax

[sh-syntax][12] is a WASM wrapper around the robust [mvdan/sh][13] Go parser. It
is highly recommended if you need:

- Support for Bash, POSIX sh, mksh, Bats, and experimental Zsh parsing
- Mature, configurable formatting and pretty-printing

unbash provides:

- A zero-dependency, synchronous TypeScript API without WASM loading
- A smaller, JSON-friendly Bash AST with lazy structured word parts, recursively
  parsed substitutions, and direct source positions
- Best-effort partial ASTs for malformed or incomplete editor and user input
- Also see [sh-syntax gaps covered by unbash][14]

## unbash vs bash-parser

[bash-parser][15] and its fork [@ericcornelissen/bash-parser][16] (community
dependency maintenance fork ❤️ now archived) provide:

- A POSIX-only mode that rejects bash-specific syntax

unbash provides:

- A zero-dependency architecture
- A typed TypeScript API (ESM-only)
- Best-effort error recovery that preserves a partial AST and collects errors
- Structured AST nodes for parameter expansions, arithmetic expressions, and `[[
]]` test expressions; `bash-parser` treats `[[ ]]` as ordinary commands and
  `(( ))` as nested subshells
- Herestrings, C-style `for`, `select`, process substitution, `coproc`, array
  assignments, extglob, `;&`/`;;&` case fallthrough, Bash 5.3 command
  substitutions, and `{variable}` file-descriptor redirects

## Benchmarks

Parse throughput in MB/s; higher is better. Median per-run p75 iteration times
from 11 isolated runs per parser and workload, on Apple M1 Pro/32GB with Node.js
24.19.0. Parentheses show speed relative to unbash v6.

| Parser                       | short (1.1KiB) | advanced (0.9KiB) | medium (150KiB) | large (970KiB) |
| ---------------------------- | -------------: | ----------------: | --------------: | -------------: |
| **unbash v6**                |       **79.2** |          **72.7** |       **102.6** |      **121.2** |
| unbash v5                    |   79.5 (1.00x) |      73.3 (0.99x) |   103.6 (0.99x) |  116.6 (1.04x) |
| unbash v4                    |   80.8 (0.98x) |      73.5 (0.99x) |    99.8 (1.03x) |  114.5 (1.06x) |
| tree-sitter-bash (native)    |     4.23 (19x) |        5.95 (12x) |      15.04 (7x) |    11.88 (10x) |
| tree-sitter-bash (WASM)      |     5.08 (16x) |        5.47 (13x) |      8.50 (12x) |     8.12 (15x) |
| sh-syntax                    |   0.04 (1838x) |      0.06 (1264x) |      8.80 (12x) |     14.32 (8x) |
| bash-parser                  |    0.28 (287x) |               n/a |             n/a |            n/a |
| @ericcornelissen/bash-parser |    0.25 (313x) |               n/a |             n/a |            n/a |

Run the isolated suite using Node.js 24.2+:

```sh
pnpm install
pnpm bench
```

Each run used 500ms of warmup, one V8 GC before timing, and at least one second
and 64 iterations of measurement. Results consume top-level node counts; WASM
tree-sitter timings include disposal of returned trees. Each case runs in a
fresh process, with reversed order on repeats.

## Size

The parser bundle is 100K minified and 26K gzipped.

## Playgrounds

- [unbash.statichost.page][17]
- [ast-explorer.dev][18]

## License

ISC

[1]: https://unba.sh/unba.sh.webp
[2]: https://www.npmx.dev/package/unbash
[3]: https://img.shields.io/npm/v/unbash?color=f56e0f
[4]: https://img.shields.io/badge/dynamic/json?url=https://npm-gapless.webpro.nl/downloads/range/last-month/unbash&query=$.totalCompact&label=downloads&suffix=/month&color=f56e0f
[5]: https://nodejs.org/api/util.html#utilparseargsconfig
[6]: https://yargs.js.org/
[7]: https://www.npmjs.com/package/citty
[8]: https://unbash.statichost.page/#input=if%20%5B%20-f%20%22%241%22%20%5D%3B%20then%20cat%20%22%241%22%3B%20fi
[9]: docs/MIGRATION-v5-to-v6.md
[10]: https://github.com/tree-sitter/tree-sitter-bash
[11]: https://github.com/webpro-nl/unbash/issues/6
[12]: https://github.com/un-ts/sh-syntax
[13]: https://github.com/mvdan/sh
[14]: https://github.com/webpro-nl/unbash/issues/7
[15]: https://github.com/vorpaljs/bash-parser
[16]: https://github.com/ericcornelissen/bash-parser
[17]: https://unbash.statichost.page
[18]: https://ast-explorer.dev/#eNoVjDsKwzAQRK8yDK5CyAGS2nVAId02jixZAbFr/Kls393rbh7zeBsrn5xLqpV3jr5X/XVzcYgOKRaD8LoNzffTBqFotgkZf8XtUW14oTdRIHaLq00WYscwpRFtCO8g2psm75n3toPHCdz+Ivg=
