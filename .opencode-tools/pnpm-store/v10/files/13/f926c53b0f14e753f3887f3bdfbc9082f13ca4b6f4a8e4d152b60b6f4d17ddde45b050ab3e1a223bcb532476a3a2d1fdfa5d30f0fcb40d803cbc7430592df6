import { isFile } from '../../util/fs.js';
import { toModule, toEntry, toIgnore } from '../../util/input.js';
import parseArgs from '../../util/parse-args.js';
const title = 'Bun';
const enablers = 'This plugin is enabled when a `bun.lock` or `bun.lockb` file is found or a `bun test` script is configured.';
const patterns = ['**/*.{test,spec}.{js,jsx,ts,tsx}', '**/*_{test,spec}.{js,jsx,ts,tsx}'];
const getBunTest = (script, cwd, getScriptCommands) => {
    for (const { binary, args } of getScriptCommands(script, cwd)) {
        if (binary !== 'bun')
            continue;
        const parsed = parseArgs(args, { string: ['timeout', 'rerun-each', 'preload'] });
        if (parsed._[0] === 'test')
            return parsed;
    }
};
const hasBunTest = (scripts, cwd, getScriptCommands) => scripts &&
    Object.values(scripts).some(script => typeof script === 'string' && getBunTest(script, cwd, getScriptCommands));
const isEnabled = ({ cwd, manifest, getScriptCommands }) => isFile(cwd, 'bun.lock') || isFile(cwd, 'bun.lockb') || !!hasBunTest(manifest.scripts, cwd, getScriptCommands);
const config = ['bunfig.toml'];
const resolveConfig = localConfig => {
    const preload = localConfig.test?.preload ?? [];
    return preload.map(specifier => toModule(specifier));
};
const isPath = (arg) => /^\.{0,2}\//.test(arg);
const toFilterPatterns = (filter) => {
    if (filter === '.')
        return patterns;
    if (/\.[cm]?[jt]sx?$/.test(filter))
        return [`**/*${filter}`];
    return [
        ...patterns.map(pattern => `**/*${filter}*/${pattern}`),
        ...patterns.map(pattern => pattern.replace('**/*', `**/*${filter}*`)),
    ];
};
const toPatterns = (arg) => {
    if (/[*{?]/.test(arg))
        return [arg];
    if (!isPath(arg))
        return toFilterPatterns(arg);
    if (/\.\w+$/.test(arg))
        return [arg];
    const dir = arg.replace(/\/+$/, '');
    return patterns.map(pattern => `${dir}/${pattern}`);
};
const resolve = options => {
    const scripts = { ...options.rootManifest?.scripts, ...options.manifest.scripts };
    const inputs = [toIgnore('bun', 'dependencies')];
    for (const [name, script] of Object.entries(scripts)) {
        if (typeof script !== 'string')
            continue;
        const cwd = options.manifest.scripts?.[name] !== undefined ? options.cwd : options.rootCwd;
        const parsed = getBunTest(script, cwd, options.getScriptCommands);
        if (!parsed)
            continue;
        const targets = parsed._.slice(1);
        for (const pattern of targets.length === 0 ? patterns : targets.flatMap(toPatterns))
            inputs.push(toEntry(pattern));
        for (const specifier of [parsed.preload ?? []].flat())
            inputs.push(toModule(specifier));
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolve,
    resolveConfig,
};
export default plugin;
