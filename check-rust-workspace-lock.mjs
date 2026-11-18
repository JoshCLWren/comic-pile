#!/usr/bin/env node
// Verify that both Cargo workspace packages resolve the canonical root lockfile.
// This script is intentionally dependency-free: the Vercel Rust builder runs it
// before compiling either production function, and local/CI callers use the same
// executable path.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const SKIPPED_DIRECTORIES = new Set([
  ".git",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
  ".venv",
  "__pycache__",
  "node_modules",
  "target",
  "venv",
]);

function cargoMetadata(cwd, manifest) {
  const result = spawnSync(
    "cargo",
    ["metadata", "--locked", "--format-version", "1", "--manifest-path", manifest],
    {
      cwd,
      encoding: "utf8",
      env: { ...process.env, CARGO_TERM_COLOR: "never" },
      maxBuffer: 64 * 1024 * 1024,
    },
  );
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const detail = result.stderr.trim() || `cargo metadata exited ${result.status}`;
    throw new Error(detail);
  }
  return JSON.parse(result.stdout);
}

async function findLockfiles(directory) {
  const found = [];
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (!SKIPPED_DIRECTORIES.has(entry.name)) {
        found.push(...(await findLockfiles(entryPath)));
      }
    } else if (entry.isFile() && entry.name === "Cargo.lock") {
      found.push(entryPath);
    }
  }
  return found.sort();
}

function withoutResolveRoot(resolve) {
  const { root: _root, ...graph } = resolve;
  return graph;
}

async function main() {
  const arguments_ = process.argv.slice(2);
  const printOnlyLockHash = arguments_[0] === "--lock-sha256";
  const requestedRoot = arguments_[printOnlyLockHash ? 1 : 0];
  const workspaceRoot = path.resolve(requestedRoot ?? SCRIPT_DIRECTORY);
  const serviceRoot = path.join(workspaceRoot, "native", "roll-service");
  const rootLockfile = path.join(workspaceRoot, "Cargo.lock");

  const lockfiles = await findLockfiles(workspaceRoot);
  assert.deepEqual(
    lockfiles,
    [rootLockfile],
    `the workspace must contain exactly one root Cargo.lock; found ${lockfiles.join(", ")}`,
  );

  const lockBefore = await readFile(rootLockfile);
  const rootMetadata = cargoMetadata(workspaceRoot, "Cargo.toml");
  const serviceMetadata = cargoMetadata(serviceRoot, "Cargo.toml");
  const lockAfter = await readFile(rootLockfile);

  assert.equal(
    rootMetadata.workspace_root,
    workspaceRoot,
    "the root manifest must identify the canonical workspace root",
  );
  assert.equal(
    serviceMetadata.workspace_root,
    workspaceRoot,
    "the service manifest must resolve through the canonical workspace root",
  );
  assert.deepEqual(
    rootMetadata.workspace_members,
    serviceMetadata.workspace_members,
    "root and service invocations must select the same workspace members",
  );
  assert.deepEqual(
    rootMetadata.target_directory,
    serviceMetadata.target_directory,
    "root and service invocations must use the same target directory",
  );
  assert.deepEqual(
    rootMetadata.packages,
    serviceMetadata.packages,
    "root and service invocations must resolve identical package metadata",
  );
  assert.deepEqual(
    withoutResolveRoot(rootMetadata.resolve),
    withoutResolveRoot(serviceMetadata.resolve),
    "root and service invocations must resolve identical dependency edges",
  );
  assert.deepEqual(
    lockBefore,
    lockAfter,
    "locked metadata resolution must not modify the canonical root lockfile",
  );

  const rootPackage = rootMetadata.packages.find(
    (candidate) => candidate.id === rootMetadata.resolve.root,
  );
  const servicePackage = serviceMetadata.packages.find(
    (candidate) => candidate.id === serviceMetadata.resolve.root,
  );
  assert.equal(rootPackage?.name, "comicpile-vercel-native");
  assert.equal(servicePackage?.name, "comicpile-roll-service");

  const lockSha256 = createHash("sha256").update(lockAfter).digest("hex");
  if (printOnlyLockHash) {
    console.log(lockSha256);
    return;
  }

  const workspacePackages = rootMetadata.workspace_members.map((memberId) => {
    const workspacePackage = rootMetadata.packages.find(
      (candidate) => candidate.id === memberId,
    );
    return {
      name: workspacePackage?.name ?? memberId,
      version: workspacePackage?.version ?? "unknown",
    };
  });
  console.log(
    JSON.stringify({
      status: "ok",
      workspace_root: workspaceRoot,
      lockfile: rootLockfile,
      lock_sha256: lockSha256,
      resolved_packages: rootMetadata.resolve.nodes.length,
      workspace_packages: workspacePackages,
    }),
  );
}

try {
  await main();
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  console.error(`Rust workspace lock check failed: ${detail}`);
  process.exitCode = 1;
}
