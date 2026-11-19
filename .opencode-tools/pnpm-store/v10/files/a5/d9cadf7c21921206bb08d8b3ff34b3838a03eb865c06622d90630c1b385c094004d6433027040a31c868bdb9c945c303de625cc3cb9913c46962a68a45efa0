import parseArgs, {} from '../util/parse-args.js';
import { compact } from '../util/array.js';
import { toModule, toEntry } from '../util/input.js';
import { isValidBinary } from '../util/modules.js';
import { isAbsolute } from '../util/path.js';
import { argsFrom, toCommandBinary } from './util.js';
export const shellSpawningBinaries = ['cross-env-shell'];
export const spawningBinaries = ['cross-env', ...shellSpawningBinaries];
const isEnvAssignment = /^\w+=/;
export const getEnvAssignmentCount = (values) => {
    let count = 0;
    while (count < values.length && isEnvAssignment.test(values[count]))
        count++;
    return count;
};
const endOfCommandBinaries = ['doppler', 'dotenvx', 'infisical', 'op'];
const commandFlagBinaries = new Map([
    ['doppler', ['command']],
    ['infisical', ['command', 'c']],
]);
const positionals = new Set(['babel-node', 'esbuild', 'execa', 'jiti', 'oxnode', 'vite-node', 'zx']);
const positionalBinaries = new Set(['concurrently']);
export const isWrapper = (binary) => spawningBinaries.includes(binary) || endOfCommandBinaries.includes(binary) || positionalBinaries.has(binary);
const parse = (binary, words) => parseArgs(words, {
    boolean: ['quiet', 'verbose'],
    string: commandFlagBinaries.get(binary) ?? [],
    '--': endOfCommandBinaries.includes(binary),
});
const toWrappedScripts = (binary, words, parsed) => {
    const scripts = [];
    if (parsed['--'] && parsed['--'].length > 0)
        scripts.push(argsFrom(words, '--').slice(1));
    if (positionalBinaries.has(binary))
        for (const script of parsed._)
            scripts.push([script]);
    for (const flag of commandFlagBinaries.get(binary) ?? [])
        if (parsed[flag])
            scripts.push([parsed[flag]]);
    return scripts;
};
export const getWrappedScripts = (binary, words) => endOfCommandBinaries.includes(binary) || commandFlagBinaries.has(binary) || positionalBinaries.has(binary)
    ? toWrappedScripts(binary, words, parse(binary, words))
    : [];
export const resolve = (binary, words, options) => {
    const { fromArgs } = options;
    const parsed = parse(binary, words);
    const bin = binary.startsWith('.') || (binary.includes('/') && !isAbsolute(binary))
        ? toEntry(binary)
        : isValidBinary(binary)
            ? toCommandBinary(binary, options)
            : undefined;
    const pos = positionals.has(binary) ? [toModule(parsed._[0])] : [];
    const commands = toWrappedScripts(binary, words, parsed).flatMap(script => fromArgs(script));
    return compact([bin, ...pos, ...commands]);
};
