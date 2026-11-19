import { compact } from '../../util/array.js';
import { isFile, loadJSON } from '../../util/fs.js';
import { toConfig, toModule, toEntryPath, toDependency } from '../../util/input.js';
import { get } from '../../util/object.js';
import { dirname, isInternal, join, relative, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { substringBefore } from '../../util/string.js';
const title = 'Nx';
const enablers = ['nx', /^@nrwl\//, /^@nx\//];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['nx.json', 'project.json', '{apps,libs}/**/project.json', 'package.json'];
const findNxDependenciesInNxJson = async (localConfig) => {
    const targetsDefault = localConfig.targetDefaults
        ? Object.keys(localConfig.targetDefaults)
            .filter(it => it.includes(':') && it.startsWith('@'))
            .map(it => substringBefore(it, ':'))
        : [];
    const plugins = localConfig.plugins && Array.isArray(localConfig.plugins)
        ? localConfig.plugins
            .map(value => (typeof value === 'string' ? value : value.plugin))
            .filter(value => value !== undefined)
        : [];
    const generators = localConfig.generators
        ? Object.keys(localConfig.generators)
            .filter(value => value !== undefined)
            .map(value => substringBefore(value, ':'))
        : [];
    return [
        ...compact([...targetsDefault, ...generators]).map(id => toDependency(id)),
        ...compact(plugins).map(id => (isInternal(id) ? toModule(id) : toDependency(id))),
    ];
};
const resolveConfig = async (localConfig, options) => {
    const { configFileName } = options;
    if (configFileName === 'nx.json') {
        return findNxDependenciesInNxJson(localConfig, options);
    }
    const config = localConfig;
    const targets = config.targets ? Object.values(config.targets) : [];
    const executors = targets
        .map(target => target?.executor)
        .filter(executor => executor && !executor.startsWith('.'))
        .map(executor => executor && substringBefore(executor, ':'));
    const expand = (value) => value.replaceAll('{projectRoot}', options.configFileDir).replaceAll('{workspaceRoot}', options.rootCwd);
    const resolveTargetCwd = (targetCwd) => targetCwd ? toAbsolute(expand(targetCwd), options.rootCwd) : options.cwd;
    const inputs = targets
        .filter(target => target.executor === 'nx:run-commands' || target.command)
        .flatMap(target => {
        let commands = [];
        if (target.command)
            commands = [target.command];
        else if (target.options?.command)
            commands = [target.options.command];
        else if (target.options?.commands)
            commands = target.options.commands.map(commandConfig => typeof commandConfig === 'string' ? commandConfig : commandConfig.command);
        const cwd = resolveTargetCwd(target.options?.cwd);
        const expandRelative = (command) => command
            .replaceAll('{projectRoot}', relative(cwd, options.configFileDir))
            .replaceAll('{workspaceRoot}', relative(cwd, options.rootCwd));
        const scriptInputs = options.getInputsFromScripts(commands.map(expandRelative), { cwd });
        for (const input of scriptInputs)
            input.dir ??= cwd;
        return scriptInputs;
    });
    const toTargetConfig = (pluginName, specifier) => toConfig(pluginName, expand(specifier), { dir: options.rootCwd });
    const configInputs = targets.flatMap(target => {
        const opts = target.options;
        if (!opts)
            return [];
        const configs = [];
        if ('eslintConfig' in opts && typeof opts.eslintConfig === 'string') {
            configs.push(toTargetConfig('eslint', opts.eslintConfig));
        }
        if ('jestConfig' in opts && typeof opts.jestConfig === 'string') {
            configs.push(toTargetConfig('jest', opts.jestConfig));
        }
        if ('karmaConfig' in opts && typeof opts.karmaConfig === 'string') {
            configs.push(toTargetConfig('karma', opts.karmaConfig));
        }
        if ('tsConfig' in opts && typeof opts.tsConfig === 'string') {
            configs.push(toTargetConfig('typescript', opts.tsConfig));
        }
        if ('vitestConfig' in opts && typeof opts.vitestConfig === 'string') {
            configs.push(toTargetConfig('vitest', opts.vitestConfig));
        }
        if ('webpackConfig' in opts && typeof opts.webpackConfig === 'string') {
            configs.push(toTargetConfig('webpack', opts.webpackConfig));
        }
        return configs;
    });
    return compact([...executors, ...inputs, ...configInputs]).map(id => typeof id === 'string' ? toDependency(id) : id);
};
const collections = [
    ['generators', 'schematics'],
    ['executors', 'builders'],
];
const resolve = async (options) => {
    const inputs = [];
    for (const [key, alias] of collections) {
        const file = get(options.manifest, key) ?? get(options.manifest, alias);
        if (typeof file !== 'string')
            continue;
        const filePath = join(options.cwd, file);
        if (!isFile(filePath))
            continue;
        const collection = await loadJSON(filePath);
        for (const entries of [collection[key], collection[alias]]) {
            for (const entry of Object.values(entries ?? {})) {
                if (!entry || typeof entry !== 'object')
                    continue;
                for (const id of [entry.implementation || entry.factory, entry.batchImplementation]) {
                    if (typeof id === 'string' && id.length > 0) {
                        inputs.push(toEntryPath(substringBefore(id, '#'), { dir: dirname(filePath) }));
                    }
                }
            }
        }
    }
    return inputs;
};
const args = {
    fromArgs: (parsed) => (parsed._[0] === 'exec' ? [...parsed._.slice(1), ...(parsed['--'] ?? [])] : []),
};
export const docs = {
    note: `Also see [integrated monorepos](/features/integrated-monorepos) and the note regarding internal workspace dependencies.`,
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    resolve,
    args,
};
export default plugin;
