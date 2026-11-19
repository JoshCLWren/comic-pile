import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { Visitor } from 'oxc-parser';
import { scriptBodies } from '../../compilers/compilers.js';
import { stylePreprocessorImports } from '../../compilers/style-preprocessors.js';
import { DEFAULT_EXTENSIONS } from '../../constants.js';
import { _parseFile } from '../../typescript/ast-nodes.js';
import { isFile } from '../../util/fs.js';
import { _syncGlob } from '../../util/glob.js';
import { dirname, isInNodeModules, join } from '../../util/path.js';
import { _createSyncModuleResolver } from '../../util/resolve.js';
const getVueSfc = (cwd) => {
    try {
        const sfc = createRequire(join(cwd, 'package.json'))('vue/compiler-sfc');
        if (typeof sfc.parseComponent === 'function') {
            return {
                parse: (source, path) => ({
                    descriptor: sfc.parse({ source, filename: path, sourceMap: false }),
                }),
                compileTemplate: (source, path, isTS, preprocessLang) => sfc.compileTemplate({
                    source,
                    filename: path,
                    sourceMap: false,
                    isProduction: true,
                    prettify: false,
                    isTS,
                    preprocessLang,
                }),
            };
        }
        return {
            parse: (source, path) => sfc.parse(source, { filename: path, sourceMap: false }),
        };
    }
    catch { }
    return {
        parse: (source, path) => ({
            descriptor: { script: { content: scriptBodies(source, path) }, scriptSetup: null, template: { content: '' } },
        }),
    };
};
const readFile = (filePath) => {
    try {
        return readFileSync(filePath, 'utf8');
    }
    catch {
        return '';
    }
};
export const readAndParseFile = (filePath) => _parseFile(filePath, readFile(filePath));
const collectIdentifiers = (source, fileName, importedComponents) => {
    const identifiers = new Set();
    const visitor = new Visitor({
        Identifier(node) {
            identifiers.add(node.name);
        },
        ImportDeclaration(node) {
            if (importedComponents && node.source.value === '#components') {
                for (const specifier of node.specifiers) {
                    if (specifier.type === 'ImportSpecifier') {
                        importedComponents.add(specifier.imported.type === 'Identifier' ? specifier.imported.name : specifier.imported.value);
                    }
                }
            }
        },
    });
    visitor.visit(_parseFile(fileName, source).program);
    return identifiers;
};
const collectTemplateInfo = (tree) => {
    const tags = new Set();
    const identifiers = new Set();
    const visited = new Set();
    const addExprIdentifiers = (expr) => {
        for (const id of collectIdentifiers(expr, 'expr.ts'))
            identifiers.add(id);
    };
    const visit = (node) => {
        if (visited.has(node))
            return;
        visited.add(node);
        if (node.tag)
            tags.add(node.tag);
        if (node.type === 5 && node.content && !node.content.isStatic)
            addExprIdentifiers(node.content.content);
        if (node.props) {
            for (const prop of node.props) {
                if (prop.type === 7) {
                    if (prop.exp && !prop.exp.isStatic)
                        addExprIdentifiers(prop.exp.content);
                    if (prop.arg && !prop.arg.isStatic)
                        addExprIdentifiers(prop.arg.content);
                }
            }
        }
        if (node.children)
            for (const child of node.children)
                visit(child);
        if (node.ifConditions)
            for (const condition of node.ifConditions)
                visit(condition.block);
        if (node.scopedSlots)
            for (const name in node.scopedSlots)
                visit(node.scopedSlots[name]);
    };
    visit(tree);
    return { tags, identifiers };
};
const collectVue2TemplateIdentifiers = (source) => {
    const identifiers = new Set();
    const visitor = new Visitor({
        MemberExpression(node) {
            if (!node.computed &&
                node.object.type === 'Identifier' &&
                node.object.name === '_vm' &&
                node.property.type === 'Identifier') {
                const name = node.property.name;
                if (name !== '_self' && name !== '$set' && name !== '$delete' && !(name.length === 2 && name[0] === '_')) {
                    identifiers.add(name);
                }
            }
        },
    });
    visitor.visit(_parseFile('template.js', source).program);
    return identifiers;
};
const toKebabCase = (s) => s.replace(/[A-Z]/g, (m, i) => (i ? '-' : '') + m.toLowerCase());
const isLocalSpecifier = (specifier) => specifier.startsWith('.') && !isInNodeModules(specifier);
const resolveModule = _createSyncModuleResolver([...DEFAULT_EXTENSIONS, '.vue']);
export const collectLocalImportPaths = (filePath, result) => {
    const dir = dirname(filePath);
    const paths = new Set();
    const visitor = new Visitor({
        TSImportType(node) {
            const specifier = node.source.value;
            if (isLocalSpecifier(specifier))
                paths.add(join(dir, specifier));
        },
    });
    visitor.visit(result.program);
    return paths;
};
export function buildAutoImportMap(filePath, result, maps, isComponents) {
    const dir = dirname(filePath);
    const importTypes = [];
    const collectVisitor = new Visitor({
        TSImportType(node) {
            importTypes.push({ start: node.start, end: node.end, specifier: node.source.value });
        },
    });
    collectVisitor.visit(result.program);
    const addEntry = (name, start, end) => {
        const importType = importTypes.find(it => it.start >= start && it.end <= end);
        if (!importType || !isLocalSpecifier(importType.specifier))
            return;
        const absSpecifier = resolveModule(importType.specifier, filePath) ?? join(dir, importType.specifier);
        if (isComponents) {
            const components = maps.componentMap.get(name);
            if (components) {
                if (!components.includes(absSpecifier))
                    components.push(absSpecifier);
            }
            else
                maps.componentMap.set(name, [absSpecifier]);
        }
        else {
            maps.importMap.set(name, absSpecifier);
        }
    };
    const matchVisitor = new Visitor({
        VariableDeclarator(node) {
            if (node.id?.type !== 'Identifier' || node.id.name.startsWith('Lazy'))
                return;
            addEntry(node.id.name, node.start, node.end);
        },
        TSPropertySignature(node) {
            if (!isComponents)
                return;
            const key = node.key;
            const name = key?.type === 'Identifier' ? key.name : key?.type === 'Literal' ? String(key.value) : undefined;
            if (name)
                addEntry(name, node.start, node.end);
        },
        ExportNamedDeclaration(node) {
            if (!node.source)
                return;
            const specifier = node.source.value;
            if (!isLocalSpecifier(specifier))
                return;
            const absSpecifier = resolveModule(specifier, filePath) ?? join(dir, specifier);
            for (const s of node.specifiers) {
                const name = s.exported.type === 'Identifier' ? s.exported.name : s.exported.value;
                if (name)
                    maps.importMap.set(name, absSpecifier);
            }
        },
    });
    matchVisitor.visit(result.program);
}
export const createAutoImportMaps = () => ({ importMap: new Map(), componentMap: new Map() });
export const findGeneratedDts = (cwd, signature) => _syncGlob({ cwd, patterns: ['*.d.ts', 'src/**/*.d.ts'] }).filter(filePath => readFile(filePath).slice(0, 300).includes(signature));
const generators = [
    { signature: 'Generated by unplugin-vue-components', isComponents: true },
    { signature: 'Generated by unplugin-auto-import', isComponents: false },
];
const getVueAutoImportMaps = (cwd) => {
    const maps = createAutoImportMaps();
    for (const filePath of _syncGlob({ cwd, patterns: ['*.d.ts', 'src/**/*.d.ts'] })) {
        const source = readFile(filePath);
        const generator = generators.find(({ signature }) => source.slice(0, 300).includes(signature));
        if (generator)
            buildAutoImportMap(filePath, _parseFile(filePath, source), maps, generator.isComponents);
    }
    return maps;
};
const getSyntheticImports = (maps, identifiers, filePath, templateTags) => {
    const { importMap, componentMap } = maps;
    if (importMap.size === 0 && (!templateTags || componentMap.size === 0))
        return [];
    const syntheticImports = [];
    for (const [name, specifier] of importMap) {
        if (identifiers.has(name) && specifier !== filePath) {
            syntheticImports.push(`import { ${name} } from '${specifier}';`);
        }
    }
    if (templateTags) {
        for (const [name, specifiers] of componentMap) {
            const kebab = toKebabCase(name);
            if (templateTags.has(name) ||
                templateTags.has(kebab) ||
                templateTags.has(`Lazy${name}`) ||
                templateTags.has(`lazy-${kebab}`)) {
                const targets = specifiers.filter(specifier => specifier !== filePath);
                if (targets.length === 0)
                    continue;
                syntheticImports.push(`import { default as ${name} } from '${targets[0]}';`);
                for (let i = 1; i < targets.length; i++)
                    syntheticImports.push(`import '${targets[i]}';`);
            }
        }
    }
    return syntheticImports;
};
const getImportedComponentImports = (maps, names) => {
    const imports = [];
    for (const importedName of names) {
        const name = importedName.startsWith('Lazy') ? importedName.slice(4) : importedName;
        for (const specifier of maps.componentMap.get(name) ?? [])
            imports.push(`import '${specifier}';`);
    }
    return imports;
};
const srcBlockMatcher = /<!--[\s\S]*?-->|<(script|style)(?=[\s/>])((?:[^>"']|"[^"]*"|'[^']*')*?)(?:\/>|>[\s\S]*?<\/\1\s*>)/g;
const attributeMatcher = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
const getSrc = (attrs) => {
    for (const [, name, double, single, unquoted] of attrs.matchAll(attributeMatcher)) {
        if (name === 'src')
            return double ?? single ?? unquoted;
    }
};
const getSrcImports = (source) => {
    if (!source.includes('src'))
        return '';
    const imports = [];
    for (const [, tag, attrs] of source.matchAll(srcBlockMatcher)) {
        const src = tag && getSrc(attrs);
        if (!src)
            continue;
        const specifier = JSON.stringify(src);
        if (tag === 'script') {
            imports.push(`import _sfc_main from ${specifier};\nexport * from ${specifier};\nexport default _sfc_main;`);
        }
        else
            imports.push(`import ${specifier};`);
    }
    return imports.join('\n');
};
const compileVueSfc = (source, path, maps, root) => {
    if (maps.importMap.size === 0 && maps.componentMap.size === 0) {
        return [scriptBodies(source, path), getSrcImports(source), stylePreprocessorImports(source, path)]
            .filter(Boolean)
            .join(';\n');
    }
    const sfc = sfcForRoot(root);
    const { descriptor } = sfc.parse(source, path);
    const scripts = [];
    if (descriptor.script?.content)
        scripts.push(descriptor.script.content);
    if (descriptor.scriptSetup?.content)
        scripts.push(descriptor.scriptSetup.content);
    const importedComponents = new Set();
    const identifiers = scripts.length === 0 ? new Set() : collectIdentifiers(scripts.join('\n'), path, importedComponents);
    const template = descriptor.template;
    const compiled = template && !template.ast && sfc.compileTemplate
        ? sfc.compileTemplate(template.content, path, descriptor.script?.lang === 'ts' ||
            descriptor.script?.lang === 'tsx' ||
            descriptor.scriptSetup?.lang === 'ts' ||
            descriptor.scriptSetup?.lang === 'tsx', template.lang)
        : undefined;
    let templateTags;
    const templateAst = template?.ast ?? compiled?.ast;
    if (templateAst) {
        const info = collectTemplateInfo(templateAst);
        templateTags = info.tags;
        for (const id of info.identifiers)
            identifiers.add(id);
    }
    if (compiled?.code) {
        for (const id of collectVue2TemplateIdentifiers(compiled.code))
            identifiers.add(id);
    }
    scripts.push(...getSyntheticImports(maps, identifiers, path, templateTags));
    scripts.push(...getImportedComponentImports(maps, importedComponents));
    const srcImports = getSrcImports(source);
    if (srcImports)
        scripts.push(srcImports);
    const styles = stylePreprocessorImports(source, path);
    if (styles)
        scripts.push(styles);
    return scripts.join(';\n');
};
const compileTs = (source, path, maps) => {
    if ((maps.importMap.size === 0 && maps.componentMap.size === 0) ||
        path.endsWith('.d.ts') ||
        path.endsWith('.config.ts'))
        return source;
    const importedComponents = new Set();
    const syntheticImports = getSyntheticImports(maps, collectIdentifiers(source, path, importedComponents), path);
    syntheticImports.push(...getImportedComponentImports(maps, importedComponents));
    return syntheticImports.length === 0 ? source : `${source}\n${syntheticImports.join('\n')}`;
};
const tagMatcher = /<([a-zA-Z][\w.-]*)/g;
const fencedCodeMatcher = /(`{3,}|~{3,})[\s\S]*?^[ \t]*\1/gm;
const inlineCodeMatcher = /`[^`\n]*`/g;
const stripCode = (md) => md.replace(fencedCodeMatcher, '').replace(inlineCodeMatcher, '');
const compileMarkdown = (source, path, maps) => {
    const code = stripCode(source);
    const scripts = scriptBodies(code, path);
    if (maps.importMap.size === 0 && maps.componentMap.size === 0)
        return scripts;
    const tags = new Set();
    for (const [, tag] of code.matchAll(tagMatcher))
        tags.add(tag);
    const identifiers = scripts ? collectIdentifiers(scripts, path) : new Set();
    return [scripts, ...getSyntheticImports(maps, identifiers, path, tags)].filter(Boolean).join(';\n');
};
export const createVueCompiler = (maps, cwd) => (source, path) => compileVueSfc(source, path, maps, cwd);
export const createTsCompiler = (maps) => (source, path) => compileTs(source, path, maps);
const EMPTY_MAPS = createAutoImportMaps();
const rootByDir = new Map();
const mapsByRoot = new Map();
const sfcByRoot = new Map();
const findRoot = (fromDir) => {
    const cached = rootByDir.get(fromDir);
    if (cached !== undefined)
        return cached;
    let dir = fromDir;
    let root = '';
    for (;;) {
        if (isFile(join(dir, 'package.json'))) {
            root = dir;
            break;
        }
        const parent = dirname(dir);
        if (parent === dir)
            break;
        dir = parent;
    }
    rootByDir.set(fromDir, root);
    return root;
};
const mapsForFile = (path) => {
    const root = findRoot(dirname(path));
    if (!root)
        return EMPTY_MAPS;
    let maps = mapsByRoot.get(root);
    if (!maps) {
        maps = getVueAutoImportMaps(root);
        mapsByRoot.set(root, maps);
    }
    return maps;
};
function sfcForRoot(root) {
    let sfc = sfcByRoot.get(root);
    if (!sfc) {
        sfc = getVueSfc(root);
        sfcByRoot.set(root, sfc);
    }
    return sfc;
}
export const vueAutoImportCompiler = (source, path) => compileVueSfc(source, path, mapsForFile(path), findRoot(dirname(path)));
export const tsAutoImportCompiler = (source, path) => compileTs(source, path, mapsForFile(path));
export const markdownAutoImportCompiler = (source, path) => compileMarkdown(source, path, mapsForFile(path));
