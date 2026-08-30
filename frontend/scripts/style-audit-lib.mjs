import fs from 'node:fs/promises'
import path from 'node:path'

import postcss from 'postcss'
import ts from 'typescript'

const SCRIPT_EXTENSIONS = new Set(['.js', '.jsx', '.ts', '.tsx'])
const SKIPPED_DIRECTORIES = new Set(['generated', 'test', 'unit'])
const DYNAMIC_MARKER = '__STYLE_AUDIT_DYNAMIC__'
const BREAKPOINTS = new Set(['sm', 'md', 'lg', 'xl', '2xl'])
const TEXT_SIZES = new Set([
  'xs',
  'sm',
  'base',
  'lg',
  'xl',
  '2xl',
  '3xl',
  '4xl',
  '5xl',
  '6xl',
  '7xl',
  '8xl',
  '9xl',
])
const FONT_WEIGHTS = new Set([
  'thin',
  'extralight',
  'light',
  'normal',
  'medium',
  'semibold',
  'bold',
  'extrabold',
  'black',
])
const PALETTES = new Set([
  'slate',
  'gray',
  'zinc',
  'neutral',
  'stone',
  'red',
  'orange',
  'amber',
  'yellow',
  'lime',
  'green',
  'emerald',
  'teal',
  'cyan',
  'sky',
  'blue',
  'indigo',
  'violet',
  'purple',
  'fuchsia',
  'pink',
  'rose',
])
const COLOR_UTILITY_PREFIXES = new Set([
  'accent',
  'bg',
  'border',
  'caret',
  'decoration',
  'divide',
  'fill',
  'from',
  'outline',
  'ring',
  'stroke',
  'text',
  'to',
  'via',
])
const CSS_LITERAL_COLOR = /#[0-9a-f]{3,8}\b|(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color)\([^)]*\)/gi
const CSS_VAR_USE = /var\(\s*(--[a-zA-Z0-9_-]+)/g
const SIMPLE_DIMENSION = /^(-?(?:\d+\.?\d*|\.\d+))(px|rem|em|%)$/i

function compareText(left, right) {
  if (left < right) return -1
  if (left > right) return 1
  return 0
}

function normalizePath(value) {
  return value.split(path.sep).join('/')
}

function locationKey(location) {
  return `${location.file}:${location.line}:${location.column}`
}

function compareLocation(left, right) {
  return (
    compareText(left.file, right.file) ||
    left.line - right.line ||
    left.column - right.column
  )
}

function addInventory(map, value, location) {
  if (!value) return
  const current = map.get(value) ?? { count: 0, locations: [] }
  current.count += 1
  current.locations.push(location)
  map.set(value, current)
}

function inventoryEntries(map) {
  return [...map.entries()]
    .map(([value, data]) => ({
      value,
      count: data.count,
      locations: [...data.locations].sort(compareLocation),
    }))
    .sort((left, right) => right.count - left.count || compareText(left.value, right.value))
}

function sourceLocation(sourceFile, node, file) {
  const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
  return { file, line: position.line + 1, column: position.character + 1 }
}

function cssLocation(node, file) {
  return {
    file,
    line: node.source?.start?.line ?? 1,
    column: node.source?.start?.column ?? 1,
  }
}

function diagnosticMessage(diagnostic, sourceFile, file) {
  const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')
  if (typeof diagnostic.start !== 'number') return `${file}: ${message}`
  const position = sourceFile.getLineAndCharacterOfPosition(diagnostic.start)
  return `${file}:${position.line + 1}:${position.character + 1}: ${message}`
}

function scriptKind(file) {
  if (file.endsWith('.tsx')) return ts.ScriptKind.TSX
  if (file.endsWith('.jsx')) return ts.ScriptKind.JSX
  if (file.endsWith('.js')) return ts.ScriptKind.JS
  return ts.ScriptKind.TS
}

function propertyNameText(name) {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text
  }
  return null
}

function combineBinaryStrings(node) {
  const left = extractClassLiterals(node.left)
  const right = extractClassLiterals(node.right)
  if (node.operatorToken.kind !== ts.SyntaxKind.PlusToken) return [...left, ...right]
  if (left.length === 0 || right.length === 0) return [...left, ...right]
  const combined = []
  for (const leftValue of left) {
    for (const rightValue of right) {
      combined.push({ text: `${leftValue.text}${rightValue.text}`, node })
    }
  }
  return combined
}

function templateText(node) {
  if (ts.isNoSubstitutionTemplateLiteral(node)) return node.text
  let value = node.head.text
  for (const span of node.templateSpans) {
    value += DYNAMIC_MARKER
    value += span.literal.text
  }
  return value
}

function extractClassLiterals(node) {
  if (!node) return []
  if (ts.isStringLiteralLike(node)) return [{ text: node.text, node }]
  if (ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateExpression(node)) {
    return [{ text: templateText(node), node }]
  }
  if (ts.isConditionalExpression(node)) {
    return [...extractClassLiterals(node.whenTrue), ...extractClassLiterals(node.whenFalse)]
  }
  if (ts.isBinaryExpression(node)) return combineBinaryStrings(node)
  if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
    return (node.arguments ?? []).flatMap((argument) => extractClassLiterals(argument))
  }
  if (ts.isArrayLiteralExpression(node)) {
    return node.elements.flatMap((element) => extractClassLiterals(element))
  }
  if (
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isTypeAssertionExpression(node) ||
    ts.isNonNullExpression(node) ||
    ts.isSatisfiesExpression(node)
  ) {
    return extractClassLiterals(node.expression)
  }
  if (ts.isTaggedTemplateExpression(node)) return extractClassLiterals(node.template)
  return []
}

export function tokenizeClasses(value) {
  const tokens = []
  let token = ''
  let bracketDepth = 0
  let parenthesisDepth = 0
  let quote = null

  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]
    const escaped = index > 0 && value[index - 1] === '\\'
    if (quote) {
      token += character
      if (character === quote && !escaped) quote = null
      continue
    }
    if ((character === '"' || character === "'") && bracketDepth > 0) {
      quote = character
      token += character
      continue
    }
    if (character === '[') bracketDepth += 1
    if (character === ']') bracketDepth = Math.max(0, bracketDepth - 1)
    if (character === '(') parenthesisDepth += 1
    if (character === ')') parenthesisDepth = Math.max(0, parenthesisDepth - 1)
    if (/\s/.test(character) && bracketDepth === 0 && parenthesisDepth === 0) {
      if (token) tokens.push(token)
      token = ''
      continue
    }
    token += character
  }
  if (token) tokens.push(token)
  return tokens.filter((entry) => entry && !entry.includes(DYNAMIC_MARKER))
}

function splitVariants(token) {
  const parts = []
  let part = ''
  let bracketDepth = 0
  let parenthesisDepth = 0
  let quote = null

  for (let index = 0; index < token.length; index += 1) {
    const character = token[index]
    const escaped = index > 0 && token[index - 1] === '\\'
    if (quote) {
      part += character
      if (character === quote && !escaped) quote = null
      continue
    }
    if ((character === '"' || character === "'") && bracketDepth > 0) {
      quote = character
      part += character
      continue
    }
    if (character === '[') bracketDepth += 1
    if (character === ']') bracketDepth = Math.max(0, bracketDepth - 1)
    if (character === '(') parenthesisDepth += 1
    if (character === ')') parenthesisDepth = Math.max(0, parenthesisDepth - 1)
    if (character === ':' && bracketDepth === 0 && parenthesisDepth === 0) {
      parts.push(part)
      part = ''
      continue
    }
    part += character
  }
  parts.push(part)
  return parts
}

function tokenParts(token) {
  const pieces = splitVariants(token)
  let base = pieces.at(-1) ?? token
  const modifiers = pieces.slice(0, -1)
  if (base.startsWith('!')) base = base.slice(1)
  const positiveBase = base.startsWith('-') ? base.slice(1) : base
  return { base, positiveBase, modifiers }
}

function isBreakpoint(modifier) {
  return (
    BREAKPOINTS.has(modifier) ||
    /^(?:min|max)-(?:sm|md|lg|xl|2xl)$/.test(modifier) ||
    /^(?:min|max)-\[[^\]]+\]$/.test(modifier)
  )
}

function arbitraryContent(base) {
  const start = base.indexOf('[')
  const end = base.lastIndexOf(']')
  if (start < 0 || end <= start) return null
  return base.slice(start + 1, end)
}

function looksLikeDimension(value) {
  return /^(?:-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em|%|vw|vh|dvw|dvh|ch|ex)|calc\(|clamp\(|min\(|max\()/i.test(
    value,
  )
}

function rawPaletteUtility(base) {
  const positiveBase = base.startsWith('-') ? base.slice(1) : base
  const parts = positiveBase.split('-')
  if (!COLOR_UTILITY_PREFIXES.has(parts[0])) return false
  return parts.some(
    (part, index) =>
      PALETTES.has(part) && /^\d{2,3}(?:\/.*)?$/.test(parts[index + 1] ?? ''),
  )
}

function classifyToken(token) {
  const { base, positiveBase, modifiers } = tokenParts(token)
  const arbitrary = arbitraryContent(positiveBase)
  const textArbitrary = positiveBase.startsWith('text-[') && arbitrary && looksLikeDimension(arbitrary)
  const weightArbitrary = positiveBase.startsWith('font-[') && arbitrary && /^\d{3}$/.test(arbitrary)
  return {
    base,
    modifiers,
    arbitrary: arbitrary ? token : null,
    radius: positiveBase.startsWith('rounded') ? base : null,
    textSize:
      positiveBase.startsWith('text-') &&
      (TEXT_SIZES.has(positiveBase.slice(5)) || textArbitrary)
        ? base
        : null,
    fontWeight:
      positiveBase.startsWith('font-') &&
      (FONT_WEIGHTS.has(positiveBase.slice(5)) || weightArbitrary)
        ? base
        : null,
    lineHeight: positiveBase.startsWith('leading-') ? base : null,
    spacing: /^(?:p[trblxyse]?|m[trblxyse]?|gap(?:-[xy])?|space-[xy])-/.test(positiveBase)
      ? base
      : null,
    shadow:
      positiveBase === 'shadow' ||
      positiveBase.startsWith('shadow-') ||
      positiveBase === 'drop-shadow' ||
      positiveBase.startsWith('drop-shadow-')
        ? base
        : null,
    rawPalette: rawPaletteUtility(base) ? base : null,
  }
}

export function analyzeScriptText(text, file = 'frontend/src/fixture.tsx') {
  const sourceFile = ts.createSourceFile(
    file,
    text,
    ts.ScriptTarget.Latest,
    true,
    scriptKind(file),
  )
  const diagnostics = sourceFile.parseDiagnostics ?? []
  if (diagnostics.length > 0) {
    throw new Error(diagnostics.map((diagnostic) => diagnosticMessage(diagnostic, sourceFile, file)).join('\n'))
  }

  const classGroups = []
  const rawControls = { button: [], input: [], select: [], textarea: [] }
  const inlineStyles = []
  const dynamicClassSites = []
  const seenClassLiteralSites = new Set()

  function addClassLiterals(literals) {
    for (const literal of literals) {
      const location = sourceLocation(sourceFile, literal.node, file)
      const key = `${locationKey(location)}:${literal.text}`
      if (seenClassLiteralSites.has(key)) continue
      seenClassLiteralSites.add(key)
      const tokens = tokenizeClasses(literal.text)
      if (tokens.length === 0) continue
      classGroups.push({ text: tokens.join(' '), tokens, location })
    }
  }

  function visit(node) {
    if (ts.isJsxAttribute(node)) {
      const name = node.name.getText(sourceFile)
      if (name === 'className' || name === 'class') {
        let expression = node.initializer
        if (expression && ts.isJsxExpression(expression)) expression = expression.expression
        const literals = extractClassLiterals(expression)
        addClassLiterals(literals)
        if (literals.length === 0 || literals.some((literal) => literal.text.includes(DYNAMIC_MARKER))) {
          dynamicClassSites.push(sourceLocation(sourceFile, node, file))
        }
      }
      if (name === 'style') {
        let expression = node.initializer
        if (expression && ts.isJsxExpression(expression)) expression = expression.expression
        inlineStyles.push({
          kind: expression && ts.isObjectLiteralExpression(expression) ? 'object' : 'dynamic',
          location: sourceLocation(sourceFile, node, file),
        })
      }
    }

    if (ts.isPropertyAssignment(node)) {
      const name = propertyNameText(node.name)
      if (name === 'className' || name === 'class') addClassLiterals(extractClassLiterals(node.initializer))
    }

    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      if (/(?:className|classes|classList|styles?)$/i.test(node.name.text)) {
        addClassLiterals(extractClassLiterals(node.initializer))
      }
    }

    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(sourceFile)
      if (Object.hasOwn(rawControls, tag)) {
        rawControls[tag].push(sourceLocation(sourceFile, node, file))
      }
    }

    ts.forEachChild(node, visit)
  }

  visit(sourceFile)
  for (const control of Object.keys(rawControls)) rawControls[control].sort(compareLocation)
  inlineStyles.sort((left, right) => compareLocation(left.location, right.location))
  dynamicClassSites.sort(compareLocation)
  classGroups.sort((left, right) => compareLocation(left.location, right.location))

  return { classGroups, rawControls, inlineStyles, dynamicClassSites }
}

function splitTopLevel(value, delimiter = ',') {
  const parts = []
  let part = ''
  let bracketDepth = 0
  let parenthesisDepth = 0
  let quote = null
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]
    const escaped = index > 0 && value[index - 1] === '\\'
    if (quote) {
      part += character
      if (character === quote && !escaped) quote = null
      continue
    }
    if (character === '"' || character === "'") {
      quote = character
      part += character
      continue
    }
    if (character === '[') bracketDepth += 1
    if (character === ']') bracketDepth = Math.max(0, bracketDepth - 1)
    if (character === '(') parenthesisDepth += 1
    if (character === ')') parenthesisDepth = Math.max(0, parenthesisDepth - 1)
    if (character === delimiter && bracketDepth === 0 && parenthesisDepth === 0) {
      if (part.trim()) parts.push(part.trim())
      part = ''
      continue
    }
    part += character
  }
  if (part.trim()) parts.push(part.trim())
  return parts
}

function selectorSpecificity(selector) {
  if (/[&]|:(?:is|where|not|has)\(/.test(selector)) return null
  const ids = selector.match(/#[a-zA-Z0-9_-]+/g)?.length ?? 0
  const classes = selector.match(/\.[a-zA-Z0-9_-]+/g)?.length ?? 0
  const attributes = selector.match(/\[[^\]]+\]/g)?.length ?? 0
  const pseudoElements = selector.match(/::[a-zA-Z0-9_-]+/g)?.length ?? 0
  const pseudoClasses = selector.match(/:(?!:)[a-zA-Z0-9_-]+(?:\([^)]*\))?/g)?.length ?? 0
  const stripped = selector
    .replace(/\[[^\]]+\]/g, ' ')
    .replace(/#[a-zA-Z0-9_-]+/g, ' ')
    .replace(/\.[a-zA-Z0-9_-]+/g, ' ')
    .replace(/::?[a-zA-Z0-9_-]+(?:\([^)]*\))?/g, ' ')
  const elements = [...stripped.matchAll(/(?:^|[\s>+~])([a-zA-Z][a-zA-Z0-9_-]*)/g)].length
  return [ids, classes + attributes + pseudoClasses, elements + pseudoElements]
}

function insideKeyframes(rule) {
  let current = rule.parent
  while (current) {
    if (current.type === 'atrule' && /keyframes$/i.test(current.name)) return true
    current = current.parent
  }
  return false
}

export function analyzeCssText(text, file = 'frontend/src/fixture.css') {
  let root
  try {
    root = postcss.parse(text, { from: file })
  } catch (error) {
    throw new Error(`${file}: ${error instanceof Error ? error.message : String(error)}`)
  }

  const declarations = []
  const customPropertyDeclarations = []
  const customPropertyUses = []
  const literalColors = []
  const mediaQueries = []
  const importantDeclarations = []
  const selectorSpecificities = []
  const applyClassGroups = []

  root.walkDecls((declaration) => {
    const location = cssLocation(declaration, file)
    const property = declaration.prop.trim()
    const value = declaration.value.trim()
    declarations.push({ property, value, location })
    if (property.startsWith('--')) customPropertyDeclarations.push({ name: property, value, location })
    for (const match of value.matchAll(CSS_VAR_USE)) {
      customPropertyUses.push({ name: match[1], location })
    }
    for (const match of value.matchAll(CSS_LITERAL_COLOR)) {
      literalColors.push({ value: match[0].toLowerCase(), property, location })
    }
    if (declaration.important) importantDeclarations.push({ property, value, location })
  })

  root.walkAtRules((atRule) => {
    if (atRule.name.toLowerCase() === 'media') {
      mediaQueries.push({ value: atRule.params.trim(), location: cssLocation(atRule, file) })
    }
    if (atRule.name.toLowerCase() === 'apply') {
      const tokens = tokenizeClasses(atRule.params)
      if (tokens.length > 0) {
        applyClassGroups.push({
          text: tokens.join(' '),
          tokens,
          location: cssLocation(atRule, file),
        })
      }
    }
  })

  root.walkRules((rule) => {
    if (insideKeyframes(rule)) return
    for (const selector of splitTopLevel(rule.selector)) {
      const specificity = selectorSpecificity(selector)
      if (!specificity) continue
      selectorSpecificities.push({ selector, specificity, location: cssLocation(rule, file) })
    }
  })

  declarations.sort((left, right) => compareLocation(left.location, right.location))
  customPropertyDeclarations.sort((left, right) => compareLocation(left.location, right.location))
  customPropertyUses.sort((left, right) => compareLocation(left.location, right.location))
  literalColors.sort((left, right) => compareLocation(left.location, right.location))
  mediaQueries.sort((left, right) => compareLocation(left.location, right.location))
  importantDeclarations.sort((left, right) => compareLocation(left.location, right.location))
  selectorSpecificities.sort((left, right) => compareLocation(left.location, right.location))
  applyClassGroups.sort((left, right) => compareLocation(left.location, right.location))

  return {
    declarations,
    customPropertyDeclarations,
    customPropertyUses,
    literalColors,
    mediaQueries,
    importantDeclarations,
    selectorSpecificities,
    applyClassGroups,
  }
}

function meaningfulTokenValue(value) {
  return !/var\(/.test(value) && !/^(?:none|inherit|initial|unset|normal)$/i.test(value) && value.length >= 3
}

function customPropertyFamily(name) {
  return name.replace(/^--/, '').split('-')[0] || 'other'
}

function formatTypographyCombination(classifications) {
  const sizes = [...new Set(classifications.map((entry) => entry.textSize).filter(Boolean))]
  const weights = [...new Set(classifications.map((entry) => entry.fontWeight).filter(Boolean))]
  const lines = [...new Set(classifications.map((entry) => entry.lineHeight).filter(Boolean))]
  if (sizes.length + weights.length + lines.length === 0) return null
  return [
    `size=${sizes.join('+') || 'default'}`,
    `weight=${weights.join('+') || 'default'}`,
    `line=${lines.join('+') || 'default'}`,
  ].join(' | ')
}

function commonParentDirectory(locations) {
  const parents = new Set(locations.map((location) => path.posix.dirname(location.file)))
  return parents.size === 1 ? [...parents][0] : null
}

function sharedLiteralTokenValues(declarations) {
  const byValue = new Map()
  for (const declaration of declarations) {
    if (!meaningfulTokenValue(declaration.value)) continue
    const entry = byValue.get(declaration.value) ?? { names: new Set(), locations: [] }
    entry.names.add(declaration.name)
    entry.locations.push(declaration.location)
    byValue.set(declaration.value, entry)
  }
  return [...byValue.entries()]
    .filter(([, entry]) => entry.names.size > 1)
    .map(([value, entry]) => ({
      value,
      names: [...entry.names].sort(compareText),
      locations: entry.locations.sort(compareLocation),
    }))
    .sort((left, right) => right.names.length - left.names.length || compareText(left.value, right.value))
}

function adjacentNumericValues(property, entries) {
  const dimensions = entries
    .map((entry) => {
      const match = entry.value.match(SIMPLE_DIMENSION)
      if (!match) return null
      return { value: entry.value, number: Number(match[1]), unit: match[2].toLowerCase(), count: entry.count }
    })
    .filter(Boolean)
  const pairs = []
  for (const unit of [...new Set(dimensions.map((entry) => entry.unit))].sort(compareText)) {
    const sorted = dimensions.filter((entry) => entry.unit === unit).sort((left, right) => left.number - right.number)
    for (let index = 1; index < sorted.length; index += 1) {
      const left = sorted[index - 1]
      const right = sorted[index]
      if (left.number === right.number) continue
      const difference = Math.abs(right.number - left.number)
      const scale = Math.max(Math.abs(left.number), Math.abs(right.number), Number.EPSILON)
      pairs.push({
        property,
        left: left.value,
        right: right.value,
        absoluteGap: Number(difference.toFixed(6)),
        relativeGap: Number((difference / scale).toFixed(6)),
        counts: [left.count, right.count],
      })
    }
  }
  return pairs
}

function compareSpecificity(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left.specificity[index] !== right.specificity[index]) {
      return right.specificity[index] - left.specificity[index]
    }
  }
  return compareText(left.selector, right.selector) || compareLocation(left.location, right.location)
}

function createFileStats(file) {
  return {
    file,
    classGroupSites: 0,
    classTokens: 0,
    rawControls: 0,
    inlineStyles: 0,
    dynamicClassSites: 0,
    cssDeclarations: 0,
    presentationDecisionSites: 0,
  }
}

function ensureFileStats(map, file) {
  if (!map.has(file)) map.set(file, createFileStats(file))
  return map.get(file)
}

function buildReport(records) {
  const arbitraryValues = new Map()
  const radiusUtilities = new Map()
  const textSizes = new Map()
  const fontWeights = new Map()
  const lineHeights = new Map()
  const typographyCombinations = new Map()
  const spacingUtilities = new Map()
  const shadows = new Map()
  const breakpoints = new Map()
  const rawPaletteUtilities = new Map()
  const longClassGroups = new Map()
  const cssCustomDeclarations = new Map()
  const cssCustomUses = new Map()
  const cssTokenFamilies = new Map()
  const cssLiteralColors = new Map()
  const cssFontSizes = new Map()
  const cssLineHeights = new Map()
  const cssRadii = new Map()
  const cssShadows = new Map()
  const cssMediaQueries = new Map()
  const rawControls = { button: [], input: [], select: [], textarea: [] }
  const inlineStyles = []
  const dynamicClassSites = []
  const fileStats = new Map()
  const customDeclarations = []
  const importantDeclarations = []
  const selectorSpecificities = []
  let classTokenCount = 0
  let classGroupCount = 0
  let cssDeclarationCount = 0

  function consumeClassGroup(group) {
    classGroupCount += 1
    classTokenCount += group.tokens.length
    const stats = ensureFileStats(fileStats, group.location.file)
    stats.classGroupSites += 1
    stats.classTokens += group.tokens.length
    stats.presentationDecisionSites += 1

    const classifications = group.tokens.map(classifyToken)
    for (const classification of classifications) {
      if (classification.arbitrary) addInventory(arbitraryValues, classification.arbitrary, group.location)
      if (classification.radius) addInventory(radiusUtilities, classification.radius, group.location)
      if (classification.textSize) addInventory(textSizes, classification.textSize, group.location)
      if (classification.fontWeight) addInventory(fontWeights, classification.fontWeight, group.location)
      if (classification.lineHeight) addInventory(lineHeights, classification.lineHeight, group.location)
      if (classification.spacing) addInventory(spacingUtilities, classification.spacing, group.location)
      if (classification.shadow) addInventory(shadows, classification.shadow, group.location)
      if (classification.rawPalette) addInventory(rawPaletteUtilities, classification.rawPalette, group.location)
      for (const modifier of classification.modifiers.filter(isBreakpoint)) {
        addInventory(breakpoints, modifier, group.location)
      }
    }
    const typography = formatTypographyCombination(classifications)
    if (typography) addInventory(typographyCombinations, typography, group.location)
    if (group.tokens.length >= 6) addInventory(longClassGroups, group.text, group.location)
  }

  for (const record of records) {
    ensureFileStats(fileStats, record.file)
    if (record.kind === 'script') {
      for (const group of record.analysis.classGroups) consumeClassGroup(group)
      for (const control of Object.keys(rawControls)) {
        rawControls[control].push(...record.analysis.rawControls[control])
        const stats = ensureFileStats(fileStats, record.file)
        stats.rawControls += record.analysis.rawControls[control].length
        stats.presentationDecisionSites += record.analysis.rawControls[control].length
      }
      inlineStyles.push(...record.analysis.inlineStyles)
      dynamicClassSites.push(...record.analysis.dynamicClassSites)
      const stats = ensureFileStats(fileStats, record.file)
      stats.inlineStyles += record.analysis.inlineStyles.length
      stats.dynamicClassSites += record.analysis.dynamicClassSites.length
      stats.presentationDecisionSites += record.analysis.inlineStyles.length
      continue
    }

    for (const group of record.analysis.applyClassGroups) consumeClassGroup(group)
    for (const declaration of record.analysis.declarations) {
      cssDeclarationCount += 1
      const stats = ensureFileStats(fileStats, record.file)
      stats.cssDeclarations += 1
      stats.presentationDecisionSites += 1
      const property = declaration.property.toLowerCase()
      if (property === 'font-size') addInventory(cssFontSizes, declaration.value, declaration.location)
      if (property === 'line-height') addInventory(cssLineHeights, declaration.value, declaration.location)
      if (property === 'border-radius') addInventory(cssRadii, declaration.value, declaration.location)
      if (property === 'box-shadow' || property === 'text-shadow') {
        addInventory(cssShadows, declaration.value, declaration.location)
      }
    }
    for (const declaration of record.analysis.customPropertyDeclarations) {
      customDeclarations.push(declaration)
      addInventory(cssCustomDeclarations, declaration.name, declaration.location)
      addInventory(cssTokenFamilies, customPropertyFamily(declaration.name), declaration.location)
    }
    for (const usage of record.analysis.customPropertyUses) addInventory(cssCustomUses, usage.name, usage.location)
    for (const color of record.analysis.literalColors) addInventory(cssLiteralColors, color.value, color.location)
    for (const media of record.analysis.mediaQueries) addInventory(cssMediaQueries, media.value, media.location)
    importantDeclarations.push(...record.analysis.importantDeclarations)
    selectorSpecificities.push(...record.analysis.selectorSpecificities)
  }

  const tailwind = {
    arbitraryValues: inventoryEntries(arbitraryValues),
    radiusUtilities: inventoryEntries(radiusUtilities),
    textSizes: inventoryEntries(textSizes),
    fontWeights: inventoryEntries(fontWeights),
    lineHeights: inventoryEntries(lineHeights),
    typographyCombinations: inventoryEntries(typographyCombinations),
    spacingUtilities: inventoryEntries(spacingUtilities),
    shadows: inventoryEntries(shadows),
    breakpoints: inventoryEntries(breakpoints),
    rawPaletteUtilities: inventoryEntries(rawPaletteUtilities),
  }

  const css = {
    customPropertyDeclarations: inventoryEntries(cssCustomDeclarations),
    customPropertyUses: inventoryEntries(cssCustomUses),
    tokenFamilies: inventoryEntries(cssTokenFamilies),
    sharedLiteralTokenValues: sharedLiteralTokenValues(customDeclarations),
    literalColors: inventoryEntries(cssLiteralColors),
    fontSizes: inventoryEntries(cssFontSizes),
    lineHeights: inventoryEntries(cssLineHeights),
    radii: inventoryEntries(cssRadii),
    shadows: inventoryEntries(cssShadows),
    mediaQueries: inventoryEntries(cssMediaQueries),
    importantDeclarations: importantDeclarations.sort((left, right) => compareLocation(left.location, right.location)),
    selectorSpecificity: selectorSpecificities.sort(compareSpecificity),
  }

  const repeatedLongClassGroups = inventoryEntries(longClassGroups)
    .filter((entry) => entry.count >= 2)
    .map((entry) => ({ ...entry, tokenCount: tokenizeClasses(entry.value).length }))
  const featureLocalPatterns = repeatedLongClassGroups
    .map((entry) => ({ ...entry, featureDirectory: commonParentDirectory(entry.locations) }))
    .filter((entry) => entry.featureDirectory)
  const oneOffArbitraryValues = tailwind.arbitraryValues.filter((entry) => entry.count === 1)
  const adjacentValues = [
    ...adjacentNumericValues('font-size', css.fontSizes),
    ...adjacentNumericValues('line-height', css.lineHeights),
    ...adjacentNumericValues('border-radius', css.radii),
  ].sort((left, right) => left.relativeGap - right.relativeGap || compareText(left.property, right.property))
  const concentration = [...fileStats.values()]
    .sort(
      (left, right) =>
        right.presentationDecisionSites - left.presentationDecisionSites ||
        right.classTokens - left.classTokens ||
        compareText(left.file, right.file),
    )

  for (const control of Object.keys(rawControls)) rawControls[control].sort(compareLocation)
  inlineStyles.sort((left, right) => compareLocation(left.location, right.location))
  dynamicClassSites.sort(compareLocation)

  const distinctVocabularyCounts = {
    arbitraryValues: tailwind.arbitraryValues.length,
    radiusUtilities: tailwind.radiusUtilities.length,
    textSizes: tailwind.textSizes.length,
    fontWeights: tailwind.fontWeights.length,
    lineHeights: tailwind.lineHeights.length,
    spacingUtilities: tailwind.spacingUtilities.length,
    shadows: tailwind.shadows.length,
    breakpoints: tailwind.breakpoints.length,
    rawPaletteUtilities: tailwind.rawPaletteUtilities.length,
    cssCustomProperties: css.customPropertyDeclarations.length,
    cssLiteralColors: css.literalColors.length,
    cssFontSizes: css.fontSizes.length,
    cssLineHeights: css.lineHeights.length,
    cssRadii: css.radii.length,
    cssShadows: css.shadows.length,
    cssMediaQueries: css.mediaQueries.length,
  }

  const rawControlTotal = Object.values(rawControls).reduce((sum, locations) => sum + locations.length, 0)
  const filesScanned = records.length
  const scriptFiles = records.filter((record) => record.kind === 'script').length
  const cssFiles = records.filter((record) => record.kind === 'css').length

  return {
    schemaVersion: 1,
    scope: {
      root: 'frontend/src',
      extensions: ['.css', '.js', '.jsx', '.ts', '.tsx'],
      excluded: ['**/*.d.ts', '**/*.test.*', '**/*.spec.*', 'src/generated/**', 'src/test/**', 'src/unit/**'],
      policyMode: 'neutral',
    },
    summary: {
      filesScanned,
      scriptFiles,
      cssFiles,
      classGroupSites: classGroupCount,
      classTokens: classTokenCount,
      cssDeclarations: cssDeclarationCount,
      arbitraryValues: tailwind.arbitraryValues.reduce((sum, entry) => sum + entry.count, 0),
      rawPaletteUtilities: tailwind.rawPaletteUtilities.reduce((sum, entry) => sum + entry.count, 0),
      customPropertyDeclarations: customDeclarations.length,
      customPropertyUses: css.customPropertyUses.reduce((sum, entry) => sum + entry.count, 0),
      literalColors: css.literalColors.reduce((sum, entry) => sum + entry.count, 0),
      importantDeclarations: css.importantDeclarations.length,
      rawControls: rawControlTotal,
      inlineStyles: inlineStyles.length,
      dynamicClassSites: dynamicClassSites.length,
    },
    tailwind,
    css,
    react: {
      rawControls,
      inlineStyles,
      dynamicClassSites,
      files: [...fileStats.values()].sort((left, right) => compareText(left.file, right.file)),
    },
    signals: {
      reviewCandidates: {
        oneOffArbitraryValues,
        repeatedLongClassGroups,
        featureLocalPatterns,
        sharedLiteralTokenValues: css.sharedLiteralTokenValues,
        adjacentNumericValues: adjacentValues.slice(0, 20),
        highestSpecificitySelectors: css.selectorSpecificity.slice(0, 20),
        presentationConcentration: concentration.slice(0, 20),
      },
      ordinaryVariation: {
        distinctVocabularyCounts,
        note: 'Distinct or unique values are inventory evidence, not failures. Review candidates are ranked heuristics only.',
      },
    },
    limitations: [
      'Class inventory is AST-based and records statically authored class strings in class/className sites, class-like constants, and CSS @apply. Fully runtime-computed class names are reported as dynamic sites rather than guessed.',
      'Selector specificity is reported only for selectors that can be measured conservatively without :is(), :where(), :not(), :has(), or nesting syntax.',
      'Adjacent numeric values rank same-property values with the closest relative gap; the ranking is evidence only and has no failure threshold.',
      'This static audit does not inspect rendered geometry or computed styles; #2043 owns browser/rendered auditing.',
    ],
  }
}

async function listSourceFiles(root) {
  const files = []
  async function walk(directory, relativeDirectory) {
    const entries = await fs.readdir(directory, { withFileTypes: true })
    entries.sort((left, right) => compareText(left.name, right.name))
    for (const entry of entries) {
      const relative = relativeDirectory ? path.join(relativeDirectory, entry.name) : entry.name
      if (entry.isDirectory()) {
        if (SKIPPED_DIRECTORIES.has(entry.name)) continue
        await walk(path.join(directory, entry.name), relative)
        continue
      }
      if (!entry.isFile()) continue
      const extension = path.extname(entry.name).toLowerCase()
      if (extension !== '.css' && !SCRIPT_EXTENSIONS.has(extension)) continue
      if (/\.d\.[cm]?ts$/i.test(entry.name) || /\.(?:test|spec)\.[cm]?[jt]sx?$/i.test(entry.name)) continue
      files.push({ absolute: path.join(directory, entry.name), relative: normalizePath(relative), extension })
    }
  }
  await walk(root, '')
  return files
}

export async function scanProject(sourceRoot, { displayRoot = 'frontend/src' } = {}) {
  const files = await listSourceFiles(sourceRoot)
  const records = []
  for (const file of files) {
    const text = await fs.readFile(file.absolute, 'utf8')
    const displayFile = `${displayRoot}/${file.relative}`.replace(/\/+/g, '/')
    if (file.extension === '.css') {
      records.push({ file: displayFile, kind: 'css', analysis: analyzeCssText(text, displayFile) })
    } else {
      records.push({ file: displayFile, kind: 'script', analysis: analyzeScriptText(text, displayFile) })
    }
  }
  return buildReport(records)
}

function markdownEscape(value) {
  return String(value).replace(/\|/g, '\\|').replace(/\n/g, ' ')
}

function locationText(location) {
  return `${location.file}:${location.line}`
}

function inventoryMarkdown(title, entries, limit = 50) {
  const visible = entries.slice(0, limit)
  const lines = [`### ${title}`, '']
  if (entries.length === 0) return [...lines, '_None found._', ''].join('\n')
  lines.push('| Value | Count | Locations |', '| --- | ---: | --- |')
  for (const entry of visible) {
    const locations = entry.locations.slice(0, 5).map(locationText)
    if (entry.locations.length > 5) locations.push(`+${entry.locations.length - 5} more`)
    lines.push(`| \`${markdownEscape(entry.value)}\` | ${entry.count} | ${markdownEscape(locations.join(', '))} |`)
  }
  if (entries.length > limit) lines.push('', `_Showing ${limit} of ${entries.length}; JSON contains the complete inventory._`)
  lines.push('')
  return lines.join('\n')
}

function locationsCell(locations, limit = 4) {
  const visible = locations.slice(0, limit).map(locationText)
  if (locations.length > limit) visible.push(`+${locations.length - limit} more`)
  return markdownEscape(visible.join(', '))
}

export function renderMarkdown(report) {
  const lines = [
    '# Static frontend style-drift audit',
    '',
    '> Informational evidence only. Counts and unique values do not fail the audit. Parser/runtime/tooling errors do.',
    '',
    `Policy mode: **${report.scope.policyMode}**. #2044 had not established a merged canonical visual grammar when this audit was implemented, so the report does not label current values as compliant/non-compliant.`,
    '',
    '## Summary',
    '',
    '| Metric | Count |',
    '| --- | ---: |',
  ]
  for (const [key, value] of Object.entries(report.summary)) {
    lines.push(`| ${key} | ${value} |`)
  }

  lines.push(
    '',
    '## Review candidates',
    '',
    'These are ranked evidence for human review, not lint failures or cleanup tickets.',
    '',
    '### One-off arbitrary Tailwind values',
    '',
  )
  const oneOffs = report.signals.reviewCandidates.oneOffArbitraryValues.slice(0, 30)
  if (oneOffs.length === 0) lines.push('_None found._')
  else {
    lines.push('| Value | Location |', '| --- | --- |')
    for (const entry of oneOffs) lines.push(`| \`${markdownEscape(entry.value)}\` | ${locationsCell(entry.locations, 1)} |`)
  }

  lines.push('', '### Repeated long class groups', '')
  const repeated = report.signals.reviewCandidates.repeatedLongClassGroups.slice(0, 25)
  if (repeated.length === 0) lines.push('_None found._')
  else {
    lines.push('| Tokens | Count | Class group | Locations |', '| ---: | ---: | --- | --- |')
    for (const entry of repeated) {
      lines.push(`| ${entry.tokenCount} | ${entry.count} | \`${markdownEscape(entry.value)}\` | ${locationsCell(entry.locations)} |`)
    }
  }

  lines.push('', '### Shared literal custom-property values', '')
  const sharedTokens = report.signals.reviewCandidates.sharedLiteralTokenValues
  if (sharedTokens.length === 0) lines.push('_None found._')
  else {
    lines.push('| Literal | Custom properties | Locations |', '| --- | --- | --- |')
    for (const entry of sharedTokens) {
      lines.push(`| \`${markdownEscape(entry.value)}\` | ${markdownEscape(entry.names.join(', '))} | ${locationsCell(entry.locations)} |`)
    }
  }

  lines.push('', '### Closest adjacent authored numeric values', '')
  const adjacent = report.signals.reviewCandidates.adjacentNumericValues
  if (adjacent.length === 0) lines.push('_None found._')
  else {
    lines.push('| Property | Values | Relative gap | Counts |', '| --- | --- | ---: | --- |')
    for (const entry of adjacent) {
      lines.push(`| ${entry.property} | \`${entry.left}\` ↔ \`${entry.right}\` | ${(entry.relativeGap * 100).toFixed(2)}% | ${entry.counts.join(' / ')} |`)
    }
  }

  lines.push('', '### Highest selector specificity (conservatively measurable)', '')
  const selectors = report.signals.reviewCandidates.highestSpecificitySelectors
  if (selectors.length === 0) lines.push('_None found._')
  else {
    lines.push('| Specificity | Selector | Location |', '| --- | --- | --- |')
    for (const entry of selectors) {
      lines.push(`| ${entry.specificity.join(',')} | \`${markdownEscape(entry.selector)}\` | ${locationText(entry.location)} |`)
    }
  }

  lines.push('', '### Highest presentation-decision concentrations', '')
  const concentrations = report.signals.reviewCandidates.presentationConcentration
  if (concentrations.length === 0) lines.push('_None found._')
  else {
    lines.push('| File | Decision sites | Class groups | Class tokens | Raw controls | Inline styles | CSS declarations |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |')
    for (const entry of concentrations) {
      lines.push(`| ${entry.file} | ${entry.presentationDecisionSites} | ${entry.classGroupSites} | ${entry.classTokens} | ${entry.rawControls} | ${entry.inlineStyles} | ${entry.cssDeclarations} |`)
    }
  }

  lines.push('', '## Tailwind / authored class vocabulary', '')
  lines.push(inventoryMarkdown('Arbitrary values', report.tailwind.arbitraryValues))
  lines.push(inventoryMarkdown('Radius utilities', report.tailwind.radiusUtilities))
  lines.push(inventoryMarkdown('Text sizes', report.tailwind.textSizes))
  lines.push(inventoryMarkdown('Font weights', report.tailwind.fontWeights))
  lines.push(inventoryMarkdown('Line heights', report.tailwind.lineHeights))
  lines.push(inventoryMarkdown('Typography combinations', report.tailwind.typographyCombinations))
  lines.push(inventoryMarkdown('Spacing / gap / margin / padding', report.tailwind.spacingUtilities))
  lines.push(inventoryMarkdown('Shadows / elevation', report.tailwind.shadows))
  lines.push(inventoryMarkdown('Breakpoints', report.tailwind.breakpoints))
  lines.push(inventoryMarkdown('Raw Tailwind palette utilities', report.tailwind.rawPaletteUtilities))

  lines.push('## CSS / theme vocabulary', '')
  lines.push(inventoryMarkdown('Custom-property declarations', report.css.customPropertyDeclarations))
  lines.push(inventoryMarkdown('Custom-property uses', report.css.customPropertyUses))
  lines.push(inventoryMarkdown('Custom-property families', report.css.tokenFamilies))
  lines.push(inventoryMarkdown('Literal colors', report.css.literalColors))
  lines.push(inventoryMarkdown('Font sizes', report.css.fontSizes))
  lines.push(inventoryMarkdown('Line heights', report.css.lineHeights))
  lines.push(inventoryMarkdown('Radius values', report.css.radii))
  lines.push(inventoryMarkdown('Shadows', report.css.shadows))
  lines.push(inventoryMarkdown('Media-query breakpoints', report.css.mediaQueries))

  lines.push('### !important declarations', '')
  if (report.css.importantDeclarations.length === 0) lines.push('_None found._')
  else {
    lines.push('| Property | Value | Location |', '| --- | --- | --- |')
    for (const entry of report.css.importantDeclarations) {
      lines.push(`| ${entry.property} | \`${markdownEscape(entry.value)}\` | ${locationText(entry.location)} |`)
    }
  }

  lines.push('', '## React / UI structure', '')
  lines.push('| Raw control | Count | Locations |', '| --- | ---: | --- |')
  for (const control of ['button', 'input', 'select', 'textarea']) {
    const locations = report.react.rawControls[control]
    lines.push(`| \`<${control}>\` | ${locations.length} | ${locationsCell(locations, 12)} |`)
  }
  lines.push('', `Inline style sites: **${report.react.inlineStyles.length}**`)
  if (report.react.inlineStyles.length > 0) {
    lines.push('', '| Kind | Location |', '| --- | --- |')
    for (const entry of report.react.inlineStyles.slice(0, 50)) {
      lines.push(`| ${entry.kind} | ${locationText(entry.location)} |`)
    }
  }
  lines.push('', `Dynamic class sites not guessed by the audit: **${report.react.dynamicClassSites.length}**`)

  lines.push('', '## Ordinary variation', '')
  lines.push(report.signals.ordinaryVariation.note, '')
  lines.push('| Vocabulary | Distinct values |', '| --- | ---: |')
  for (const [key, value] of Object.entries(report.signals.ordinaryVariation.distinctVocabularyCounts)) {
    lines.push(`| ${key} | ${value} |`)
  }

  lines.push('', '## Limitations', '')
  for (const limitation of report.limitations) lines.push(`- ${limitation}`)
  lines.push('')
  return lines.join('\n')
}

export async function writeReports(report, outputDirectory) {
  await fs.mkdir(outputDirectory, { recursive: true })
  const jsonPath = path.join(outputDirectory, 'report.json')
  const markdownPath = path.join(outputDirectory, 'report.md')
  await fs.writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  await fs.writeFile(markdownPath, renderMarkdown(report), 'utf8')
  return { jsonPath, markdownPath }
}
