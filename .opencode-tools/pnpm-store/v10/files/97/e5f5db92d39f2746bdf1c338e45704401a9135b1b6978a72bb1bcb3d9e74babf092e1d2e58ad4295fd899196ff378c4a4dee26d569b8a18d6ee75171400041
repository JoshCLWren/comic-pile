import { Visitor } from 'oxc-parser';
import { findProperty, getFirstPropertyValue, getStringValues } from '../../typescript/ast-helpers.js';
import { getStringValue } from '../../typescript/ast-nodes.js';
import { getGitRemoteUrls } from '../../util/git.js';
import { join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Railway';
const enablers = ['railway'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['.railway/railway.ts'];
const args = {
    config: ['file'],
    resolve: ['runner'],
};
const getCommands = (node) => {
    const command = getStringValue(node);
    return command ? [command] : [...getStringValues(node)];
};
const isExternalSourceType = (type) => type === 'github' || type === 'image' || type === 'template';
const getGitHubRepository = (value) => {
    const normalized = value
        ?.trim()
        .replace(/^git\+/, '')
        .replace(/\.git\/?$/, '')
        .replace(/\/$/, '');
    return normalized?.match(/(?:^|github(?:\.com)?[/:])([^/:]+\/[^/]+)$/i)?.[1].toLowerCase();
};
const resolveFromAST = (program, options) => {
    const serviceNames = new Set();
    const sourceTypes = new Map();
    const bindings = new Map();
    const localRepositories = new Set();
    for (const repository of [options.manifest.repository, options.rootManifest?.repository]) {
        const name = getGitHubRepository(typeof repository === 'string' ? repository : repository?.url);
        if (name)
            localRepositories.add(name);
    }
    for (const url of getGitRemoteUrls(options.rootCwd)) {
        const name = getGitHubRepository(url);
        if (name)
            localRepositories.add(name);
    }
    for (const node of program.body) {
        if (node.type === 'ImportDeclaration' && getStringValue(node.source) === 'railway/iac') {
            for (const specifier of node.specifiers) {
                if (specifier.type !== 'ImportSpecifier' || specifier.imported.type !== 'Identifier')
                    continue;
                if (specifier.imported.name === 'service')
                    serviceNames.add(specifier.local.name);
                if (isExternalSourceType(specifier.imported.name)) {
                    sourceTypes.set(specifier.local.name, specifier.imported.name);
                }
            }
        }
        else if (node.type === 'VariableDeclaration') {
            for (const declaration of node.declarations) {
                if (declaration.id.type === 'Identifier' && declaration.init)
                    bindings.set(declaration.id.name, declaration.init);
            }
        }
    }
    const resolveBinding = (node) => {
        const seen = new Set();
        while (node?.type === 'Identifier' && bindings.has(node.name) && !seen.has(node.name)) {
            seen.add(node.name);
            node = bindings.get(node.name);
        }
        return node;
    };
    const inputs = [];
    const visitor = new Visitor({
        CallExpression(node) {
            if (node.callee.type !== 'Identifier' || !serviceNames.has(node.callee.name))
                return;
            const serviceConfig = node.arguments[1];
            if (serviceConfig?.type !== 'ObjectExpression')
                return;
            const source = resolveBinding(findProperty(serviceConfig, 'source'));
            const repository = getFirstPropertyValue(source, 'repo');
            const image = getFirstPropertyValue(source, 'image');
            const template = getFirstPropertyValue(source, 'template');
            const sourceType = (source?.type === 'CallExpression' && source.callee.type === 'Identifier'
                ? sourceTypes.get(source.callee.name)
                : undefined) ??
                getFirstPropertyValue(source, 'type') ??
                (repository ? 'github' : image ? 'image' : template ? 'template' : undefined);
            const sourceRepository = getGitHubRepository(source?.type === 'CallExpression' ? getStringValue(source.arguments[0]) : repository);
            if (sourceType === 'image' ||
                sourceType === 'template' ||
                (sourceType === 'github' &&
                    sourceRepository !== undefined &&
                    localRepositories.size > 0 &&
                    !localRepositories.has(sourceRepository))) {
                return;
            }
            const sourceConfig = source?.type === 'CallExpression' ? source.arguments[1] : source;
            const rootDirectory = getFirstPropertyValue(sourceConfig, 'rootDirectory') ??
                getFirstPropertyValue(serviceConfig, 'root') ??
                getFirstPropertyValue(serviceConfig, 'rootDirectory');
            const cwd = rootDirectory ? join(options.cwd, rootDirectory) : options.cwd;
            const manifest = options.getManifest(cwd) ?? options.manifest;
            const build = findProperty(serviceConfig, 'build');
            const commands = [
                ...getCommands(build),
                ...getCommands(findProperty(build, 'buildCommand')),
                ...getCommands(findProperty(serviceConfig, 'start')),
                ...getCommands(findProperty(serviceConfig, 'preDeploy')),
                ...getCommands(findProperty(findProperty(serviceConfig, 'deploy'), 'preDeployCommand')),
            ];
            for (const input of options.getInputsFromScripts(commands, { optionalBinaries: true, cwd, manifest })) {
                inputs.push({ ...input, dir: cwd });
            }
        },
    });
    visitor.visit(program);
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    args,
    resolveFromAST,
};
export default plugin;
