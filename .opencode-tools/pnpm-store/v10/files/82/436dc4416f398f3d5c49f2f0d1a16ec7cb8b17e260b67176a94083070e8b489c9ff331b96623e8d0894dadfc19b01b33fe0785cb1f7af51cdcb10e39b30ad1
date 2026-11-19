import parseArgs from '../../util/parse-args.js';
import { toBinary, toModule, toDependency } from '../../util/input.js';
import { stripVersionFromSpecifier } from '../../util/modules.js';
import { isInternal } from '../../util/path.js';
import { argsFrom, npmBooleanAliases, npmBooleanFlags } from '../util.js';
const noInstallFlags = new Set(['--no', '--no-install', '--yes=false', '--no-yes']);
export const resolve = (_binary, words, options) => {
    const { fromArgs, cwd } = options;
    const toPackage = (id, opts) => isInternal(id) ? toModule(id, { ...opts, dir: cwd }) : toDependency(id, opts);
    const args = {
        isStorePositions: true,
        boolean: npmBooleanFlags,
        alias: { ...npmBooleanAliases, package: 'p', call: 'c' },
    };
    const parsed = parseArgs(words, args);
    const commandIndex = parsed.positionalIndices[0] ?? words.length;
    const flags = parseArgs(words.slice(0, commandIndex), args);
    const packageSpecifier = parsed._[0];
    const specifier = packageSpecifier ? stripVersionFromSpecifier(packageSpecifier) : '';
    const packages = flags.package ? [flags.package].flat().map(stripVersionFromSpecifier) : [];
    const command = flags.call ? fromArgs([flags.call]) : [];
    const isBinary = specifier && !packageSpecifier.includes('@') && !isInternal(specifier);
    const noInstall = words.slice(0, commandIndex).some(word => noInstallFlags.has(word.value));
    const opts = noInstall ? undefined : { optional: true };
    const dependency = isBinary ? toBinary(specifier, opts) : toPackage(specifier, opts);
    const specifiers = dependency ? [dependency] : [];
    return [
        ...specifiers,
        ...packages.map(id => toPackage(id, { optional: true })),
        ...command,
        ...fromArgs(argsFrom(words, packageSpecifier)).slice(1),
    ];
};
