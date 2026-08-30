#!/usr/bin/env node
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { scanProject, writeReports } from './style-audit-lib.mjs'

const frontendRoot = fileURLToPath(new URL('../', import.meta.url))
const sourceRoot = path.join(frontendRoot, 'src')
const repositoryRoot = path.resolve(frontendRoot, '..')
const outputDirectory = path.join(repositoryRoot, 'dogfood-output', 'style-audit')

try {
  const report = await scanProject(sourceRoot)
  const output = await writeReports(report, outputDirectory)
  console.log(
    [
      `Static style audit scanned ${report.summary.filesScanned} files`,
      `${report.summary.classTokens} authored class tokens`,
      `${report.summary.cssDeclarations} CSS declarations`,
      `${report.summary.rawControls} raw controls`,
      `${report.summary.inlineStyles} inline styles`,
    ].join(' | '),
  )
  console.log(
    `Review evidence: ${report.signals.reviewCandidates.oneOffArbitraryValues.length} one-off arbitrary values | ` +
      `${report.signals.reviewCandidates.repeatedLongClassGroups.length} repeated long class groups | ` +
      `${report.signals.reviewCandidates.sharedLiteralTokenValues.length} shared literal token values`,
  )
  console.log(`Markdown report: ${path.relative(repositoryRoot, output.markdownPath)}`)
  console.log(`JSON report: ${path.relative(repositoryRoot, output.jsonPath)}`)
} catch (error) {
  console.error(`Static style audit failed: ${error instanceof Error ? error.message : String(error)}`)
  process.exitCode = 1
}
