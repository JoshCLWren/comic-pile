import { Visitor, } from 'oxc-parser';
import { findProperty, getPropertyValues, resolveObjectArg } from '../../typescript/ast-helpers.js';
import { getStringValue } from '../../typescript/ast-nodes.js';
import { isDirectory } from '../../util/fs.js';
import { toConfig, toModule, toEntryPath, toEntry } from '../../util/input.js';
import { isInNodeModules, join, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Next.js';
const enablers = ['next'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['next.config.{js,ts,cjs,mjs,mts}'];
const defaultPageExtensions = ['{js,jsx,ts,tsx}'];
const productionEntryFilePatterns = [
    'app/{,[(]*[)]/}{manifest,robots}.{js,ts}',
    'app/**/sitemap.{js,ts}',
    'app/**/{icon,apple-icon,opengraph-image,twitter-image}.{js,jsx,ts,tsx}',
];
const rootOrSrc = '{,src/}';
const getRouterDirPrefix = (cwd, name) => {
    if (!cwd)
        return rootOrSrc;
    if (isDirectory(cwd, name))
        return '';
    if (isDirectory(cwd, `src/${name}`))
        return 'src/';
    return rootOrSrc;
};
const getEntryFilePatterns = (pageExtensions = defaultPageExtensions, cwd) => {
    const ext = pageExtensions.length === 1 ? pageExtensions[0] : `{${pageExtensions.join(',')}}`;
    const appDirPrefix = getRouterDirPrefix(cwd, 'app');
    const pagesDirPrefix = getRouterDirPrefix(cwd, 'pages');
    return [
        ...productionEntryFilePatterns.map(pattern => `${appDirPrefix}${pattern}`),
        `${rootOrSrc}{instrumentation,instrumentation-client,middleware,proxy}.${ext}`,
        `${appDirPrefix}app/global-{error,not-found}.${ext}`,
        `${appDirPrefix}app/**/{default,error,forbidden,loading,not-found,unauthorized}.${ext}`,
        `${appDirPrefix}app/**/{layout,page,route,template}.${ext}`,
        `${pagesDirPrefix}pages/**/*.${ext}`,
    ];
};
const production = getEntryFilePatterns();
const getInputs = (pageExtensions, loaders, aliasTargets, files, configFileDir) => {
    const extensions = pageExtensions.length > 0 ? pageExtensions : defaultPageExtensions;
    const patterns = [...getEntryFilePatterns(extensions, configFileDir), 'next-env.d.ts'];
    const inputs = patterns.map(id => toEntry(join(configFileDir, id), { production: true }));
    for (const loader of loaders)
        inputs.push(toModule(loader));
    for (const target of aliasTargets)
        inputs.push(toModule(target, { dir: configFileDir, production: true }));
    for (const file of files)
        inputs.push(toEntryPath(toAbsolute(file, configFileDir), { production: true }));
    return inputs;
};
const isObject = (value) => typeof value === 'object' && value !== null;
const addSpecifier = (specifiers, value) => {
    if (typeof value === 'string' && !isInNodeModules(value))
        specifiers.add(value);
};
const collectLoaderValues = (value, loaders) => {
    if (Array.isArray(value))
        for (const item of value)
            collectLoaderValues(item, loaders);
    else if (isObject(value)) {
        addSpecifier(loaders, value.loader);
        collectLoaderValues(value.loaders, loaders);
    }
    else
        addSpecifier(loaders, value);
};
const collectAliasTargetValues = (value, targets) => {
    if (Array.isArray(value))
        for (const item of value)
            collectAliasTargetValues(item, targets);
    else if (isObject(value))
        collectAliasTargetValues(value.browser, targets);
    else
        addSpecifier(targets, value);
};
const resolveConfig = async (localConfig, { configFileDir }) => {
    const config = typeof localConfig === 'function'
        ? await localConfig('phase-production-build', { defaultConfig: {} })
        : localConfig;
    const pageExtensions = Array.isArray(config?.pageExtensions)
        ? config.pageExtensions.filter(extension => typeof extension === 'string')
        : [];
    const loaders = new Set();
    for (const rule of Object.values(config?.turbopack?.rules ?? {}))
        collectLoaderValues(rule, loaders);
    const aliasTargets = new Set();
    for (const target of Object.values(config?.turbopack?.resolveAlias ?? {}))
        collectAliasTargetValues(target, aliasTargets);
    const files = new Set();
    addSpecifier(files, config?.images?.loaderFile);
    addSpecifier(files, config?.cacheHandler);
    for (const handler of Object.values(config?.cacheHandlers ?? {}))
        addSpecifier(files, handler);
    return getInputs(pageExtensions, loaders, aliasTargets, files, configFileDir);
};
const isModuleExports = (node) => node.type === 'MemberExpression' &&
    node.object.type === 'Identifier' &&
    node.object.name === 'module' &&
    node.property.type === 'Identifier' &&
    node.property.name === 'exports';
const getConfigObject = (program) => {
    const declarations = new Map();
    let node;
    for (const statement of program.body) {
        if (statement.type === 'VariableDeclaration') {
            for (const declaration of statement.declarations) {
                if (declaration.id.type === 'Identifier' && declaration.init)
                    declarations.set(declaration.id.name, declaration.init);
            }
        }
        else if (statement.type === 'ExportDefaultDeclaration') {
            node = statement.declaration;
        }
        else if (statement.type === 'ExpressionStatement' &&
            statement.expression.type === 'AssignmentExpression' &&
            isModuleExports(statement.expression.left)) {
            node = statement.expression.right;
        }
    }
    while (node) {
        if (node.type === 'TSSatisfiesExpression' ||
            node.type === 'TSAsExpression' ||
            node.type === 'ParenthesizedExpression')
            node = node.expression;
        else if (node.type === 'CallExpression')
            node = node.arguments[0];
        else if (node.type === 'Identifier') {
            const init = declarations.get(node.name);
            declarations.delete(node.name);
            node = init;
        }
        else
            return resolveObjectArg(node);
    }
};
const resolveFromAST = (program, { configFileDir }) => {
    const pageExtensions = new Set();
    const loaders = new Set();
    const aliasTargets = new Set();
    const files = new Set();
    const config = getConfigObject(program);
    addSpecifier(files, getStringValue(findProperty(findProperty(config, 'images'), 'loaderFile')));
    addSpecifier(files, getStringValue(findProperty(config, 'cacheHandler')));
    for (const handler of getPropertyValues(config, 'cacheHandlers'))
        addSpecifier(files, handler);
    const collectAliasTargets = (node) => {
        const target = getStringValue(node);
        if (target)
            aliasTargets.add(target);
        else if (node?.type === 'ArrayExpression') {
            for (const element of node.elements)
                collectAliasTargets(element);
        }
        else if (node?.type === 'ObjectExpression') {
            collectAliasTargets(findProperty(node, 'browser'));
        }
    };
    const collectTurbopackAliases = (node) => {
        const aliases = findProperty(node, 'resolveAlias');
        if (aliases?.type !== 'ObjectExpression')
            return;
        for (const alias of aliases.properties) {
            if (alias.type === 'Property')
                collectAliasTargets(alias.value);
        }
    };
    const collectLoaders = (node) => {
        if (node?.type === 'ArrayExpression') {
            for (const element of node.elements)
                collectLoaders(element);
        }
        else {
            const loader = getStringValue(node) ?? getStringValue(findProperty(node, 'loader'));
            if (loader)
                loaders.add(loader);
            const nested = findProperty(node, 'loaders');
            if (nested?.type === 'ArrayExpression')
                collectLoaders(nested);
        }
    };
    const visitor = new Visitor({
        ObjectExpression(node) {
            for (const extension of getPropertyValues(node, 'pageExtensions'))
                pageExtensions.add(extension);
            const turbopack = findProperty(node, 'turbopack');
            if (turbopack?.type === 'ConditionalExpression') {
                collectTurbopackAliases(turbopack.consequent);
                collectTurbopackAliases(turbopack.alternate);
            }
            else {
                collectTurbopackAliases(turbopack);
            }
            const rules = findProperty(turbopack, 'rules');
            if (rules?.type !== 'ObjectExpression')
                return;
            for (const rule of rules.properties) {
                if (rule.type === 'Property')
                    collectLoaders(rule.value);
            }
        },
    });
    visitor.visit(program);
    return getInputs([...pageExtensions], loaders, aliasTargets, files, configFileDir);
};
const commands = new Set(['dev', 'build', 'start']);
const args = {
    boolean: ['turbo', 'turbopack'],
    resolveInputs: parsed => {
        const dir = commands.has(parsed._[0]) ? parsed._[1] : undefined;
        if (!dir)
            return [];
        return [toConfig('next', join(dir, 'next.config'))];
    },
};
const note = `Knip loads \`next.config.*\` to read Turbopack loaders and alias targets, the custom image loader
(\`images.loaderFile\`) and cache handlers (\`cacheHandler\`, \`cacheHandlers\`) from the composed configuration,
including values a shared configuration factory adds. A configuration file that fails to load is analyzed statically.`;
export const docs = { note };
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    production,
    isLoadConfigOptional: true,
    resolveConfig,
    resolveFromAST,
    args,
};
export default plugin;
