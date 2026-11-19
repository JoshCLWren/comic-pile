import parseArgs from '../../util/parse-args.js';
import { getCatalogReference } from '../../util/catalog.js';
import { toCatalog, toDependency } from '../../util/input.js';
import { extractBinary, stripVersionFromSpecifier } from '../../util/modules.js';
const toDependencyInputs = (packageSpecifier) => {
    const dependency = toDependency(stripVersionFromSpecifier(packageSpecifier), { optional: true });
    const reference = getCatalogReference(packageSpecifier);
    return reference ? [dependency, toCatalog(reference.packageName, reference.catalogName)] : [dependency];
};
const parseOptions = {
    isStorePositions: true,
    boolean: ['silent'],
    alias: { package: 'p', 'shell-mode': 'c', dir: 'C' },
};
export const resolveDlx = (words, options) => {
    const parsed = parseArgs(words, parseOptions);
    const packageSpecifier = parsed._[0];
    const commandIndex = parsed.positionalIndices[0] ?? words.length;
    const flags = parseArgs(words.slice(0, commandIndex), parseOptions);
    const packages = flags.package && !flags.yes ? [flags.package].flat() : [];
    const command = flags['shell-mode'] ? options.fromArgs([flags['shell-mode']]) : [];
    const dependencyInputs = packageSpecifier ? toDependencyInputs(packageSpecifier) : [];
    const executable = packageSpecifier ? extractBinary(String(packageSpecifier)) : '';
    const forwarded = executable && !flags.dir ? options.fromArgs([executable, ...words.slice(commandIndex + 1)]) : [];
    const isOuterCommand = forwarded[0]?.specifier === executable;
    return [
        ...dependencyInputs,
        ...packages.flatMap(toDependencyInputs),
        ...command,
        ...(isOuterCommand ? forwarded.slice(1) : forwarded),
    ];
};
export const resolve = (_binary, words, options) => {
    return resolveDlx(words, options);
};
