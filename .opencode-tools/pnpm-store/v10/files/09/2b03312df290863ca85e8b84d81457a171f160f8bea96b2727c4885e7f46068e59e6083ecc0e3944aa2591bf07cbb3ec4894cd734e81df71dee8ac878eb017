import { findProperty, getPropertyValues, resolveObjectArg } from '../../typescript/ast-helpers.js';
import { toEntry } from '../../util/input.js';
import { toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Web Test Runner';
const enablers = ['@web/test-runner'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['web-test-runner.config.{js,cjs,mjs}'];
const toFileEntries = (ids, base) => Array.from(ids, id => {
    const pattern = String(id);
    return toEntry(pattern.startsWith('!') ? `!${toAbsolute(pattern.slice(1), base)}` : toAbsolute(pattern, base));
});
const getConfigObject = (program) => {
    const body = program.body ?? [];
    const bindings = new Map();
    for (const node of body) {
        if (node.type !== 'VariableDeclaration')
            continue;
        for (const declaration of node.declarations) {
            if (declaration.id?.type === 'Identifier' && declaration.init)
                bindings.set(declaration.id.name, declaration.init);
        }
    }
    const dereference = (node) => {
        const seen = new Set();
        while (node?.type === 'Identifier' && bindings.has(node.name) && !seen.has(node.name)) {
            seen.add(node.name);
            node = bindings.get(node.name);
        }
        return node;
    };
    for (const node of body) {
        if (node.type === 'ExportDefaultDeclaration')
            return resolveObjectArg(dereference(node.declaration));
        const { expression } = node;
        if (node.type === 'ExpressionStatement' &&
            expression?.type === 'AssignmentExpression' &&
            expression.left?.type === 'MemberExpression' &&
            expression.left.object?.name === 'module' &&
            expression.left.property?.name === 'exports') {
            return resolveObjectArg(dereference(expression.right));
        }
    }
};
const resolveFromAST = (program, options) => {
    const localConfig = getConfigObject(program);
    const patterns = new Set();
    for (const pattern of getPropertyValues(localConfig, 'files'))
        patterns.add(pattern);
    const groups = findProperty(localConfig, 'groups');
    if (groups?.type === 'ArrayExpression') {
        for (const group of groups.elements ?? [])
            for (const pattern of getPropertyValues(group, 'files'))
                patterns.add(pattern);
    }
    return toFileEntries(patterns, options.cwd);
};
const args = {
    binaries: ['web-test-runner', 'wtr'],
    config: ['config'],
    string: ['files'],
    boolean: [
        'coverage',
        'debug',
        'help',
        'manual',
        'node-resolve',
        'open',
        'playwright',
        'preserve-symlinks',
        'puppeteer',
        'static-logging',
        'update-snapshots',
        'watch',
    ],
    resolveInputs: (parsed, { cwd }) => toFileEntries([...parsed._, ...(parsed['--'] ?? []), ...[parsed.files ?? []].flat()].map(String), cwd),
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveFromAST,
    args,
};
export default plugin;
