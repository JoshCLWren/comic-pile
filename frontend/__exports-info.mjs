import ts from 'typescript'
import path from 'path'

const file = path.resolve(process.argv[2])
const program = ts.createProgram([file], {
  jsx: ts.JsxEmit.ReactJSX,
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
  allowJs: false,
  skipLibCheck: true,
  noResolve: false,
})
const checker = program.getTypeChecker()
const sf = program.getSourceFile(file)
if (!sf) {
  console.error('no source file')
  process.exit(1)
}
const moduleSymbol = checker.getSymbolAtLocation(sf)
if (!moduleSymbol) {
  console.error('no module symbol')
  process.exit(1)
}
const out = {}
for (const sym of checker.getExportsOfModule(moduleSymbol)) {
  const name = sym.getName()
  const decl = sym.valueDeclaration ?? sym.declarations?.[0] ?? sf
  let kind = 'unknown'
  try {
    const type = checker.getTypeOfSymbolAtLocation(sym, decl)
    if (type.getCallSignatures().length > 0) kind = 'function'
    else kind = 'object'
  } catch {
    kind = 'unknown'
  }
  out[name] = kind
}
console.log(JSON.stringify(out))
