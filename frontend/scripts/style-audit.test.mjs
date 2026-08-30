import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  analyzeCssText,
  analyzeScriptText,
  renderMarkdown,
  scanProject,
  writeReports,
} from './style-audit-lib.mjs'

test('TSX parsing inventories authored classes, raw controls, and inline styles without comment false positives', () => {
  const source = `
    // <select className="rounded-[99px]" />
    export function Fixture({ active }) {
      return (
        <button
          className={active
            ? 'rounded-xl p-4 text-sm font-bold leading-5 bg-red-500 shadow-lg'
            : 'rounded-[13px] p-[18px] text-[15px]'}
          style={{ color: 'red' }}
        >
          <input className="px-2 md:px-4" />
        </button>
      )
    }
  `
  const analysis = analyzeScriptText(source, 'frontend/src/Fixture.tsx')

  assert.equal(analysis.rawControls.button.length, 1)
  assert.equal(analysis.rawControls.input.length, 1)
  assert.equal(analysis.rawControls.select.length, 0)
  assert.equal(analysis.inlineStyles.length, 1)
  assert.equal(analysis.inlineStyles[0].kind, 'object')
  assert.ok(analysis.classGroups.some((group) => group.tokens.includes('rounded-[13px]')))
  assert.ok(analysis.classGroups.some((group) => group.tokens.includes('md:px-4')))
})

test('CSS parsing inventories tokens, literal values, media queries, important usage, and measurable specificity', () => {
  const source = `
    :root {
      --brand: #fff;
      --legacy-brand: #fff;
      font-size: 16px;
      line-height: 1.5;
    }
    #shell .card[data-state="open"] {
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
      color: rgb(255, 255, 255) !important;
    }
    @media (min-width: 768px) {
      .card { font-size: 1rem; }
    }
  `
  const analysis = analyzeCssText(source, 'frontend/src/fixture.css')

  assert.equal(analysis.customPropertyDeclarations.length, 2)
  assert.equal(analysis.importantDeclarations.length, 1)
  assert.equal(analysis.mediaQueries[0].value, '(min-width: 768px)')
  assert.ok(analysis.literalColors.some((entry) => entry.value === '#fff'))
  assert.ok(analysis.literalColors.some((entry) => entry.value === 'rgb(255, 255, 255)'))
  assert.deepEqual(
    analysis.selectorSpecificities.find((entry) => entry.selector.includes('#shell'))?.specificity,
    [1, 2, 0],
  )
})

test('project scan produces stable structured output and human-readable review evidence', async (context) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'comic-pile-style-audit-'))
  context.after(async () => fs.rm(root, { recursive: true, force: true }))

  await fs.writeFile(
    path.join(root, 'App.tsx'),
    `
      export function App() {
        return <button className="rounded-xl p-4 text-sm font-semibold leading-5 bg-red-500 shadow-lg">Go</button>
      }
    `,
  )
  await fs.writeFile(
    path.join(root, 'Card.tsx'),
    `
      export function Card() {
        return <div className="rounded-xl p-4 text-sm font-semibold leading-5 bg-red-500 shadow-lg" style={{ padding: 1 }} />
      }
    `,
  )
  await fs.writeFile(
    path.join(root, 'styles.css'),
    `
      :root { --brand: #d6890e; --legacy-accent: #d6890e; }
      .card { border-radius: 8px; font-size: 16px; line-height: 24px; }
      .card-compact { border-radius: 9px; font-size: 15px; line-height: 23px; }
      @media (min-width: 768px) { .card { box-shadow: 0 1px 2px rgba(0, 0, 0, .2); } }
    `,
  )
  await fs.mkdir(path.join(root, 'unit'))
  await fs.writeFile(path.join(root, 'unit', 'ignored.tsx'), '<select className="rounded-[99px]" />')

  const first = await scanProject(root)
  const second = await scanProject(root)

  assert.deepEqual(first, second)
  assert.equal(first.summary.filesScanned, 3)
  assert.equal(first.react.rawControls.button.length, 1)
  assert.equal(first.react.inlineStyles.length, 1)
  assert.equal(first.tailwind.rawPaletteUtilities.find((entry) => entry.value === 'bg-red-500')?.count, 2)
  assert.equal(first.signals.reviewCandidates.repeatedLongClassGroups.length, 1)
  assert.equal(first.signals.reviewCandidates.sharedLiteralTokenValues.length, 1)
  assert.ok(first.signals.reviewCandidates.adjacentNumericValues.some((entry) => entry.property === 'border-radius'))

  const markdown = renderMarkdown(first)
  assert.match(markdown, /Review candidates/)
  assert.match(markdown, /Ordinary variation/)
  assert.match(markdown, /Raw Tailwind palette utilities/)

  const output = path.join(root, 'output')
  const paths = await writeReports(first, output)
  const json = JSON.parse(await fs.readFile(paths.jsonPath, 'utf8'))
  const reportMarkdown = await fs.readFile(paths.markdownPath, 'utf8')
  assert.deepEqual(json, first)
  assert.equal(reportMarkdown, markdown)
})

test('parser failures surface with file context instead of being converted to findings', () => {
  assert.throws(
    () => analyzeScriptText('export const Broken = () => <div>', 'frontend/src/Broken.tsx'),
    /frontend\/src\/Broken\.tsx:/,
  )
  assert.throws(
    () => analyzeCssText('.broken { color: red;', 'frontend/src/broken.css'),
    /frontend\/src\/broken\.css:/,
  )
})
