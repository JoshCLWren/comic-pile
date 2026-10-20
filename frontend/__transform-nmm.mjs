import ts from 'typescript'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'

const FRONTEND = process.cwd()
const testFile = path.resolve(process.argv[2])
const apply = process.argv.includes('--apply')

const sourceText = fs.readFileSync(testFile, 'utf8')
const sf = ts.createSourceFile(
  testFile,
  sourceText,
  ts.ScriptTarget.ES2022,
  true,
  testFile.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
)

const exportsCache = new Map()

function moduleExports(absPath) {
  if (exportsCache.has(absPath)) return exportsCache.get(absPath)
  const outFile = path.join(FRONTEND, '__exports-info.mjs')
  let info = {}
  try {
    const raw = execFileSync('node', [outFile, path.relative(FRONTEND, absPath)], {
      cwd: FRONTEND,
      encoding: 'utf8',
    })
    info = JSON.parse(raw)
  } catch (err) {
    info = { __error: String(err.stderr || err.message) }
  }
  exportsCache.set(absPath, info)
  return info
}

function resolveModule(spec, fromFile) {
  if (!spec.startsWith('.')) return null
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const c of [base + '.ts', base + '.tsx', path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c
  }
  return null
}

// ---- imports of the test file ----
const importBindings = new Map() // local name -> { module, imported }
const importDecls = [] // { decl, spec, names: Set<string> }
for (const stmt of sf.statements) {
  if (!ts.isImportDeclaration(stmt)) continue
  if (!ts.isStringLiteral(stmt.moduleSpecifier)) continue
  const mod = stmt.moduleSpecifier.text
  const clause = stmt.importClause
  if (!clause) continue
  if (clause.name) importBindings.set(clause.name.text, { module: mod, imported: 'default' })
  const names = new Set()
  if (clause.name) names.add(clause.name.text)
  if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
    for (const el of clause.namedBindings.elements) {
      importBindings.set(el.name.text, {
        module: mod,
        imported: el.propertyName ? el.propertyName.text : el.name.text,
      })
      names.add(el.name.text)
    }
  }
  importDecls.push({ decl: stmt, spec: mod, names })
}

// ---- pre-scan vi.mocked references ----
const referenced = new Set() // "obj.prop" or "name"
function scanMocked(node) {
  if (
    ts.isCallExpression(node) &&
    ts.isPropertyAccessExpression(node.expression) &&
    node.expression.expression.getText() === 'vi' &&
    node.expression.name.text === 'mocked' &&
    node.arguments.length === 1
  ) {
    const arg = node.arguments[0]
    if (ts.isPropertyAccessExpression(arg)) {
      referenced.add(`${arg.expression.getText()}.${arg.name.getText()}`)
    } else if (ts.isIdentifier(arg)) {
      referenced.add(arg.text)
    }
  }
  ts.forEachChild(node, scanMocked)
}
scanMocked(sf)

const namespaceAliases = new Map()
const aliasUsed = new Set(importBindings.keys())

function namespaceAlias(spec) {
  if (namespaceAliases.has(spec)) return namespaceAliases.get(spec)
  const base = path.basename(spec).replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9]/g, '')
  let candidate = base.charAt(0).toLowerCase() + base.slice(1) + 'Module'
  let n = 2
  while (aliasUsed.has(candidate)) {
    candidate = `${base.charAt(0).toLowerCase() + base.slice(1)}Module${n}`
    n += 1
  }
  aliasUsed.add(candidate)
  namespaceAliases.set(spec, candidate)
  return candidate
}

function findMockCalls() {
  const found = []
  function visit(node) {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.expression.getText() === 'vi' &&
      node.expression.name.text === 'mock'
    ) {
      found.push(node)
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return found
}

function returnedObjectLiteral(factory) {
  let body = factory.body
  if (ts.isParenthesizedExpression(body)) body = body.expression
  if (ts.isObjectLiteralExpression(body)) return body
  if (ts.isBlock(body)) {
    const returns = body.statements.filter(ts.isReturnStatement)
    if (returns.length === 1 && returns[0].expression) {
      let expr = returns[0].expression
      if (ts.isParenthesizedExpression(expr)) expr = expr.expression
      if (ts.isObjectLiteralExpression(expr)) return expr
    }
  }
  return null
}

const edits = []
const manual = []

for (const call of findMockCalls()) {
  const [specArg, factoryArg] = call.arguments
  if (!specArg || !ts.isStringLiteral(specArg)) {
    manual.push('non-literal specifier')
    continue
  }
  const spec = specArg.text
  const abs = resolveModule(spec, testFile)
  if (!abs) {
    manual.push(`unresolved module ${spec}`)
    continue
  }
  if (!factoryArg || !ts.isArrowFunction(factoryArg)) {
    manual.push(`non-arrow factory ${spec}`)
    continue
  }
  const obj = returnedObjectLiteral(factoryArg)
  if (!obj) {
    manual.push(`non-object factory ${spec}`)
    continue
  }
  const exports = moduleExports(abs)
  if (exports.__error) {
    manual.push(`exports error ${spec}: ${exports.__error}`)
    continue
  }
  const alias = namespaceAlias(spec)
  const lines = []
  let needsNamespace = false
  const manualLen = manual.length

  for (const prop of obj.properties) {
    if (!ts.isPropertyAssignment(prop)) {
      manual.push(`${spec}: non-assignment property ${prop.getText().slice(0, 60)}`)
      continue
    }
    const key = ts.isIdentifier(prop.name)
      ? prop.name.text
      : ts.isStringLiteral(prop.name)
        ? prop.name.text
        : null
    if (!key) {
      manual.push(`${spec}: computed key`)
      continue
    }
    const init = prop.initializer
    const realKind = exports[key]
    if (realKind === undefined) {
      manual.push(`${spec}: export ${key} not found in real module`)
      continue
    }
    if (realKind === 'function') {
      if (referenced.has(key)) continue
      needsNamespace = true
      if (ts.isCallExpression(init) && init.expression.getText() === 'vi.fn') {
        if (init.arguments.length === 0) {
          lines.push(`vi.spyOn(${alias}, '${key}')`)
        } else {
          const impl = init.arguments[0].getText()
          lines.push(
            `// SAFETY: the injected test double returns a partial view of the real contract\nvi.spyOn(${alias}, '${key}').mockImplementation((${impl}) as never)`,
          )
        }
      } else if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) {
        const impl = init.getText()
        lines.push(
          `// SAFETY: the injected test double returns a partial view of the real contract\nvi.spyOn(${alias}, '${key}').mockImplementation((${impl}) as never)`,
        )
      } else {
        manual.push(`${spec}: unsupported function initializer for ${key}: ${init.getText().slice(0, 60)}`)
      }
    } else {
      if (!ts.isObjectLiteralExpression(init)) {
        manual.push(`${spec}: unsupported object initializer for ${key}`)
        continue
      }
      const binding = importBindings.has(key) ? key : null
      if (!binding) {
        manual.push(`${spec}: object export ${key} is not imported in the test file`)
        continue
      }
      for (const nested of init.properties) {
        if (!ts.isPropertyAssignment(nested)) {
          manual.push(`${spec}: nested non-assignment for ${key}`)
          continue
        }
        const mKey = ts.isIdentifier(nested.name)
          ? nested.name.text
          : ts.isStringLiteral(nested.name)
            ? nested.name.text
            : null
        if (!mKey) {
          manual.push(`${spec}: nested computed key for ${key}`)
          continue
        }
        if (referenced.has(`${binding}.${mKey}`)) continue
        const nestedInit = nested.initializer
        if (ts.isCallExpression(nestedInit) && nestedInit.expression.getText() === 'vi.fn') {
          if (nestedInit.arguments.length === 0) {
            lines.push(`vi.spyOn(${binding}, '${mKey}')`)
          } else {
            const impl = nestedInit.arguments[0].getText()
            lines.push(
              `// SAFETY: the injected test double returns a partial view of the real contract\nvi.spyOn(${binding}, '${mKey}').mockImplementation((${impl}) as never)`,
            )
          }
        } else {
          manual.push(`${spec}: unsupported nested initializer ${key}.${mKey}`)
        }
      }
    }
  }

  if (manual.length === manualLen && lines.length > 0) {
    edits.push({ start: call.getStart(sf), end: call.getEnd(), text: lines.join('\n') })
  }
}

if (manual.length > 0) {
  console.error('MANUAL:\n' + manual.map((m) => '  - ' + m).join('\n'))
}

// ---- apply edits (end -> start) ----
let out = sourceText
const sorted = edits.slice().sort((a, b) => b.start - a.start)
for (const edit of sorted) {
  out = out.slice(0, edit.start) + edit.text + out.slice(edit.end)
}

// ---- rewrite vi.mocked(...) ----
out = out.replace(/vi\.mocked\(\s*([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*\)/g, (m, objName, prop) => {
  if (!importBindings.has(objName)) return m
  return `vi.spyOn(${objName}, '${prop}')`
})
out = out.replace(/vi\.mocked\(\s*([A-Za-z_$][\w$]*)\s*\)/g, (m, name) => {
  const binding = importBindings.get(name)
  if (!binding) return m
  const alias = namespaceAliases.get(binding.module)
  if (!alias) return m
  const abs = resolveModule(binding.module, testFile)
  if (!abs) return m
  const exports = moduleExports(abs)
  if (exports.__error) return m
  const kind = exports[binding.imported]
  if (kind !== 'function') return m
  return `vi.spyOn(${alias}, '${binding.imported}')`
})

// ---- add namespace imports (only those actually used) ----
const namespaceImports = []
for (const [spec, alias] of namespaceAliases.entries()) {
  const re = new RegExp(`\\b${alias}\\b`, 'g')
  const count = (out.match(re) || []).length
  if (count === 0) continue
  namespaceImports.push(`import * as ${alias} from '${spec}'`)
}
if (namespaceImports.length > 0) {
  let insertAt = 0
  for (const stmt of sf.statements) {
    if (ts.isImportDeclaration(stmt)) insertAt = stmt.getEnd()
  }
  out = out.slice(0, insertAt) + '\n' + namespaceImports.join('\n') + out.slice(insertAt)
}

// ---- drop imports that are no longer referenced ----
{
  const outSf = ts.createSourceFile(
    'out.tsx',
    out,
    ts.ScriptTarget.ES2022,
    true,
    testFile.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  )
  const spans = []
  for (const stmt of outSf.statements) {
    if (ts.isImportDeclaration(stmt)) spans.push([stmt.getStart(outSf), stmt.getEnd(), stmt])
  }
  let bodyText = ''
  let cursor = 0
  for (const [s, e] of spans) {
    bodyText += out.slice(cursor, s)
    cursor = e
  }
  bodyText += out.slice(cursor)

  const removals = []
  for (const [s, e, stmt] of spans) {
    const clause = stmt.importClause
    if (!clause) continue
    const names = []
    if (clause.name) names.push({ local: clause.name.text, named: false })
    if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
      for (const el of clause.namedBindings.elements) {
        names.push({ local: el.name.text, named: true, imported: el.propertyName ? el.propertyName.text : el.name.text })
      }
    }
    const kept = names.filter((n) => (bodyText.match(new RegExp(`\\b${n.local}\\b`, 'g')) || []).length > 0)
    if (kept.length === names.length) continue
    if (kept.length === 0) {
      removals.push([s, e + 1, ''])
      continue
    }
    const keptDefault = kept.find((n) => !n.named)
    const keptNamed = kept.filter((n) => n.named)
    const parts = []
    if (keptDefault) parts.push(keptDefault.local)
    if (keptNamed.length > 0) {
      const spec = keptNamed
        .map((n) => (n.imported !== n.local ? `${n.imported} as ${n.local}` : n.local))
        .join(', ')
      parts.push(`{ ${spec} }`)
    }
    const spec = stmt.moduleSpecifier.text
    removals.push([s, e + 1, `import ${parts.join(', ')} from '${spec}'\n`])
  }
  for (const [s, e, text] of removals.sort((a, b) => b[0] - a[0])) {
    out = out.slice(0, s) + text + out.slice(e)
  }
}

out = out.replace(/\n{3,}/g, '\n\n')

if (apply) {
  fs.writeFileSync(testFile, out)
  console.log('applied', path.relative(FRONTEND, testFile))
} else {
  console.log(out)
}
