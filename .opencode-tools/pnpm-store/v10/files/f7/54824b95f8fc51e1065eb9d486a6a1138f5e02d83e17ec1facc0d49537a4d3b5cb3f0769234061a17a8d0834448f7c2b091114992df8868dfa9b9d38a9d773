import { toModule, toEntryPath, toEntry } from '../../util/input.js';
import { isDirectory } from '../../util/fs.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Mocha';
const enablers = ['mocha'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['.mocharc.{js,cjs,mjs,json,jsonc,yml,yaml}', 'package.json'];
const entry = ['**/test/*.{js,cjs,mjs}'];
const defaultExtensions = ['js', 'cjs', 'mjs'];
const builtInReporters = new Set([
    'Base',
    'base',
    'Dot',
    'dot',
    'Doc',
    'doc',
    'TAP',
    'tap',
    'JSON',
    'json',
    'HTML',
    'html',
    'List',
    'list',
    'Min',
    'min',
    'Spec',
    'spec',
    'Nyan',
    'nyan',
    'XUnit',
    'xunit',
    'Markdown',
    'markdown',
    'Progress',
    'progress',
    'Landing',
    'landing',
    'JSONStream',
    'json-stream',
    'GithubActions',
    'github-actions',
]);
const isExternalReporter = (reporter) => typeof reporter === 'string' && !builtInReporters.has(reporter);
const resolveConfig = (localConfig, options) => {
    const entryPatterns = localConfig.spec ? [localConfig.spec].flat() : entry;
    const files = localConfig.file ? [localConfig.file].flat() : [];
    const require = localConfig.require ? [localConfig.require].flat() : [];
    const inputs = [];
    inputs.push(...entryPatterns.map(id => toEntry(id)));
    inputs.push(...files.map(id => toEntryPath(id, { dir: options.cwd })));
    inputs.push(...require.map(id => toModule(id, { dir: options.cwd })));
    if (isExternalReporter(localConfig.reporter))
        inputs.push(toModule(localConfig.reporter, { dir: options.cwd }));
    return inputs;
};
const args = {
    nodeImportArgs: true,
    boolean: [
        'allow-uncaught',
        'async-only',
        'bail',
        'check-leaks',
        'colors',
        'delay',
        'diff',
        'dry-run',
        'exit',
        'forbid-only',
        'forbid-pending',
        'inline-diffs',
        'invert',
        'parallel',
        'recursive',
        'sort',
        'watch',
    ],
    alias: {
        'async-only': ['A'],
        bail: ['b'],
        colors: ['c'],
        fgrep: ['f'],
        grep: ['g'],
        invert: ['i'],
        jobs: ['j'],
        'node-option': ['n'],
        parallel: ['p'],
        reporter: ['R'],
        'reporter-option': ['O'],
        slow: ['s'],
        sort: ['S'],
        timeout: ['t'],
        ui: ['u'],
        watch: ['w'],
    },
    string: ['extension', 'file', 'ignore', 'reporter', 'spec'],
    config: ['config'],
    resolveInputs: (parsed, { cwd }) => {
        const extensions = [parsed.extension ?? []]
            .flat()
            .flatMap(value => String(value).split(','))
            .map(extension => extension.replace(/^\./, ''));
        const list = extensions.length > 0 ? extensions : defaultExtensions;
        const suffix = list.length === 1 ? `*.${list[0]}` : `*.{${list.join(',')}}`;
        const inputs = [];
        const operands = [...parsed._, ...(parsed['--'] ?? []).filter(value => !value.startsWith('-'))];
        for (const value of [...operands, ...[parsed.spec ?? []].flat(), ...[parsed.file ?? []].flat()].map(String)) {
            if (isDirectory(cwd, value))
                inputs.push(toEntry(`${value.replace(/\/$/, '')}/${parsed.recursive ? '**/' : ''}${suffix}`));
            else
                inputs.push(toEntry(value));
        }
        for (const value of [parsed.ignore ?? []].flat())
            inputs.push(toEntry(`!${String(value)}`));
        if (isExternalReporter(parsed.reporter))
            inputs.push(toModule(parsed.reporter));
        return inputs;
    },
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    resolveConfig,
    args,
};
export default plugin;
