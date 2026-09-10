#!/usr/bin/env node
// Script to replace vi.mock() patterns with vi.spyOn() patterns
// Usage: node scripts/fix-vi-mock.js <file-path>
// Or: node scripts/fix-vi-mock.js --batch

import { readFileSync, writeFileSync, existsSync } from 'fs'
import { globSync } from 'fs';

// Try dynamic import for glob
let globFn;
try {
  const glob = await import('glob');
  globFn = glob.globSync;
} catch {
  // fallback
}

function fixFile(filePath) {
  const content = readFileSync(filePath, 'utf-8');
  if (!content.includes('vi.mock(')) return false;

  let newContent = content;
  const mockCalls = [];
  
  // Find all vi.mock(...) calls
  const mockRegex = /vi\.mock\(\s*([^)]+)\s*,\s*([^)]+)\s*\)/gs;
  let match;
  while ((match = mockRegex.exec(content)) !== null) {
    mockCalls.push({ fullMatch: match[0], moduleArg: match[1], factoryArg: match[2], index: match.index });
  }

  // Also handle vi.mock('module', async (importOriginal) => ...)
  const asyncMockRegex = /vi\.mock\(\s*('[^']+'|"[^"]+"|`[^`]+`)\s*,\s*async\s*\(importOriginal\)\s*=>\s*\{[^}]*\}[^)]*\)/gs;
  let asyncMatch;
  while ((asyncMatch = asyncMockRegex.exec(content)) !== null) {
    // Handle separately
  }

  // For now, just report what we found
  console.log(`Found ${mockCalls.length} vi.mock() calls in ${filePath}`);
  mockCalls.forEach((mc, i) => {
    console.log(`  ${i+1}: vi.mock(${mc.moduleArg}, ...)`);
  });

  return true;
}

// Main
const args = process.argv.slice(2);
if (args[0] === '--batch') {
  const srcDir = args[1] || '/home/runner/work/comic-pile/comic-pile/frontend/src/unit';
  const files = globSync('**/*.test.{ts,tsx}', { cwd: srcDir });
  let count = 0;
  for (const file of files) {
    const fullPath = `${srcDir}/${file}`;
    const content = readFileSync(fullPath, 'utf-8');
    if (content.includes('vi.mock(')) {
      count++;
      console.log(`Processing: ${file}`);
    }
  }
  console.log(`\nTotal files with vi.mock(): ${count}`);
} else if (args[0]) {
  fixFile(args[0]);
} else {
  console.log('Usage: node scripts/fix-vi-mock.js [--batch] [file-path]');
}
