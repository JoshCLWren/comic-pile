#!/usr/bin/env node
/**
 * Fail when current Markdown docs cite repository code paths that do not exist.
 *
 * The check is offline and deterministic. It inspects inline-backtick file paths in the Markdown
 * files selected by `iterMarkdownFiles` (Markdown links are validated by
 * scripts/check_markdown_docs.py in the docs workflow). Fenced code blocks are ignored so
 * examples are not treated as contracts.
 *
 * Resolution rules:
 *
 * - A path containing `/` resolves against the repository root, then the citing document's
 *   directory, then `frontend/` and `frontend/src/` (so `src/App.tsx` style references in
 *   frontend docs work).
 * - A bare code filename (for example `lib.rs`) must match the basename of some tracked file.
 * - Globs, placeholders, URLs, and well-known generated-output locations are skipped.
 *
 * Historical documents opt out explicitly, so point-in-time paths stay intentional:
 *
 * - `<!-- docs-path-check: historical -->` anywhere in a file skips the whole file.
 * - `<!-- docs-path-check: ignore -->` on a line skips that line.
 * - Files under HISTORICAL_PREFIXES are skipped (per-issue plans and changelogs).
 */
import {execFileSync} from 'node:child_process';
import {GENERATED_FILES, isGeneratedArtifactPath} from './generate_api_artifacts.mjs';
import {existsSync, readFileSync, readdirSync, statSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const HISTORICAL_PREFIXES = ['docs/issue-plans/', 'docs/changelog'];
export const HISTORICAL_FILE_MARKER = '<!-- docs-path-check: historical -->';
export const IGNORE_LINE_MARKER = '<!-- docs-path-check: ignore -->';
export const ROUTE_BURNDOWN_BEGIN = '<!-- route-burndown:begin';
export const ROUTE_BURNDOWN_END = '<!-- route-burndown:end -->';
export const GENERATED_PREFIXES = [
  'dogfood-output/',
  'frontend/test-results/',
  'test-results/',
  'static/react/',
  'node_modules/',
  'target/',
];
// Gitignored generated API artifacts (owner directive 2026-11-19) are valid
// references even though a fresh checkout has not generated them yet.
const GENERATED_BASENAMES = new Set(GENERATED_FILES.map((p) => p.slice(p.lastIndexOf('/') + 1)));
const IGNORED_DIRECTORIES = new Set(['.git', '.venv', '.vercel', 'node_modules', 'archive']);
const CODE_EXTENSIONS = '(?:py|rs|tsx?|jsx?|mjs|cjs|sh|sql|css|html|ya?ml|toml|json|md)';
const BARE_CODE_EXTENSIONS = new Set([
  'py', 'rs', 'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs', 'sh', 'yml', 'yaml',
]);
const INLINE_CODE_RE = /`([^`\n]+)`/g;
const FENCE_RE = /^\s*(`{3,}|~{3,})(.*)$/;
const PATH_RE = new RegExp(
  `^(?:\\./)?[A-Za-z0-9_.@\\-]+(?:/[A-Za-z0-9_.@\\-]+)+\\.${CODE_EXTENSIONS}$` +
    `|^[A-Za-z0-9_\\-]+\\.${CODE_EXTENSIONS}$`,
);
const SUFFIX_RE = /(?:::[\p{L}\p{N}_:]+|:\d+(?:-\d+)?|#L?\d+\S*)$/u;
const PLACEHOLDER_RE = /[*{}<>$]|YYYY|NNN|\bXXX/;

/**
 * Advance CommonMark fence state for one line. `fence` is null outside a fence, otherwise the
 * opening marker (any indentation, so list-nested fences work); only a same-character, at-least-as-long, info-free marker closes it.
 * Returns `[nextFence, isFenceLine]`.
 */
function advanceFence(fence, line) {
  const match = FENCE_RE.exec(line);
  if (!match) {
    return [fence, false];
  }
  const [, marker, rest] = match;
  if (fence === null) {
    return marker[0] === '`' && rest.includes('`') ? [fence, false] : [marker, true];
  }
  if (marker[0] === fence[0] && marker.length >= fence.length && rest.trim() === '') {
    return [null, true];
  }
  return [fence, false];
}

/** Split text into lines the way Python's `str.splitlines` does. */
function splitLines(text) {
  const lines = text.split(/\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/);
  if (lines.length > 0 && lines[lines.length - 1] === '') {
    lines.pop();
  }
  return lines;
}

function stripInlineCode(line) {
  return line.replace(INLINE_CODE_RE, '');
}

function compareParts(a, b) {
  const left = a.split('/');
  const right = b.split('/');
  for (let i = 0; i < Math.min(left.length, right.length); i += 1) {
    if (left[i] !== right[i]) {
      return left[i] < right[i] ? -1 : 1;
    }
  }
  return left.length - right.length;
}

function walk(root, skip) {
  const files = [];
  const visit = (dir) => {
    for (const entry of readdirSync(dir, {withFileTypes: true})) {
      if (skip.has(entry.name)) {
        continue;
      }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        visit(full);
      } else if (entry.isFile() || (entry.isSymbolicLink() && existsSync(full) && statSync(full).isFile())) {
        files.push(full);
      }
    }
  };
  visit(root);
  return files;
}

/** Return Markdown paths (sorted) that participate in documentation checks. */
export function iterMarkdownFiles(root) {
  return walk(root, IGNORED_DIRECTORIES)
    .filter((file) => file.endsWith('.md'))
    .sort((a, b) =>
      compareParts(path.relative(root, a).split(path.sep).join('/'), path.relative(root, b).split(path.sep).join('/')),
    );
}

/** Return repository-relative tracked file paths, falling back to a directory walk. */
export function trackedFiles(root) {
  try {
    const out = execFileSync('git', ['-C', root, 'ls-files'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      maxBuffer: 256 * 1024 * 1024,
    });
    return out.split('\n').filter(Boolean);
  } catch {
    return walk(root, new Set(['.git'])).map((file) => path.relative(root, file).split(path.sep).join('/'));
  }
}

/** Return `[lineNumber, candidatePath]` pairs from inline code outside fences and generated blocks. */
export function extractPaths(text) {
  const found = [];
  let fence = null;
  let inGeneratedBlock = false;
  splitLines(text).forEach((line, index) => {
    const [next, isFenceLine] = advanceFence(fence, line);
    const inFence = fence !== null;
    fence = next;
    if (isFenceLine) {
      return;
    }
    if (inGeneratedBlock) {
      if (!inFence && stripInlineCode(line).includes(ROUTE_BURNDOWN_END)) {
        inGeneratedBlock = false;
      }
      return;
    }
    if (inFence) {
      return;
    }
    const visible = stripInlineCode(line);
    if (visible.includes(ROUTE_BURNDOWN_BEGIN)) {
      inGeneratedBlock = true;
      return;
    }
    if (visible.includes(IGNORE_LINE_MARKER)) {
      return;
    }
    for (const match of line.matchAll(INLINE_CODE_RE)) {
      const candidate = match[1].trim().replace(SUFFIX_RE, '');
      if (PLACEHOLDER_RE.test(candidate) || !PATH_RE.test(candidate)) {
        continue;
      }
      found.push([index + 1, candidate.startsWith('./') ? candidate.slice(2) : candidate]);
    }
  });
  return found;
}

/** Return whether `candidate` names an existing file or an intentionally skipped path. */
export function pathResolves(root, doc, candidate, basenames, tracked) {
  if (GENERATED_PREFIXES.some((prefix) => candidate.startsWith(prefix)) || isGeneratedArtifactPath(candidate)) {
    return true;
  }
  if (candidate.includes('/')) {
    const bases = [root, path.dirname(doc), path.join(root, 'frontend'), path.join(root, 'frontend', 'src')];
    return bases.some((base) => existsSync(`${base}/${candidate}`)) || tracked.has(candidate);
  }
  const extension = candidate.slice(candidate.lastIndexOf('.') + 1);
  if (!BARE_CODE_EXTENSIONS.has(extension)) {
    return true;
  }
  return basenames.has(candidate) || GENERATED_BASENAMES.has(candidate);
}

/** Return whether `marker` appears as a real comment, not in a code span, fence, or generated block. */
function hasMarker(text, marker) {
  let fence = null;
  let inGeneratedBlock = false;
  for (const line of splitLines(text)) {
    const [next, isFenceLine] = advanceFence(fence, line);
    const inFence = fence !== null;
    fence = next;
    if (isFenceLine) {
      continue;
    }
    if (inGeneratedBlock) {
      if (!inFence && stripInlineCode(line).includes(ROUTE_BURNDOWN_END)) {
        inGeneratedBlock = false;
      }
      continue;
    }
    if (inFence) {
      continue;
    }
    const visible = stripInlineCode(line);
    if (visible.includes(ROUTE_BURNDOWN_BEGIN)) {
      inGeneratedBlock = true;
      continue;
    }
    if (visible.includes(marker)) {
      return true;
    }
  }
  return false;
}

/** Return one error per documented code path that no longer resolves. */
export function findStalePaths(root, markdownFiles) {
  const tracked = new Set(trackedFiles(root));
  const basenames = new Set([...tracked].map((name) => name.slice(name.lastIndexOf('/') + 1)));
  const errors = [];
  for (const doc of markdownFiles) {
    const relative = path.relative(root, doc).split(path.sep).join('/');
    if (HISTORICAL_PREFIXES.some((prefix) => relative.startsWith(prefix))) {
      continue;
    }
    const text = readFileSync(doc, 'utf8');
    if (hasMarker(text, HISTORICAL_FILE_MARKER)) {
      continue;
    }
    for (const [number, candidate] of extractPaths(text)) {
      if (!pathResolves(root, doc, candidate, basenames, tracked)) {
        errors.push(`${relative}:${number}: stale code path: ${candidate}`);
      }
    }
  }
  return errors;
}

/** Run the check and return a process exit status. */
export function main(argv = process.argv.slice(2)) {
  let root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const flag = argv.indexOf('--root');
  if (flag !== -1 && argv[flag + 1]) {
    root = path.resolve(argv[flag + 1]);
  }
  const files = iterMarkdownFiles(root);
  const errors = findStalePaths(root, files);
  for (const error of errors) {
    console.log(error);
  }
  if (errors.length > 0) {
    console.log(
      `${errors.length} stale doc code path(s). Fix the path, remove the section, or mark ` +
        `history with \`${HISTORICAL_FILE_MARKER}\` / \`${IGNORE_LINE_MARKER}\`.`,
    );
    return 1;
  }
  console.log(`Doc code paths resolve in ${files.length} Markdown files.`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
