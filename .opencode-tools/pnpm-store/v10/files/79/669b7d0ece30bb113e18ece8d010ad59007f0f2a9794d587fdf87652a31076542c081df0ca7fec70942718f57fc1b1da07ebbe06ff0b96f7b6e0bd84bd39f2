import { Plugins, pluginArgsMap } from '../plugins.js';
import { toModule } from '../util/input.js';
import { extractBinary, isInNodeModulesBin, isRelativeNodeModulesBin } from '../util/modules.js';
import { getCommandWords } from '../util/scripts.js';
import { resolve as fallbackResolve, spawningBinaries } from './fallback.js';
import KnownResolvers, { isPackageManager } from './resolvers/index.js';
import { getWrappedCommand, resolve as resolverFromPlugins } from './plugins.js';
import { parseNodeArgs, toCommandBinary } from './util.js';
export const getInputsFromNodeOptions = (prefix) => {
    const inputs = [];
    for (const item of prefix) {
        if (item.type !== 'Assignment' || item.name !== 'NODE_OPTIONS' || item.value.type !== 'Word')
            continue;
        const args = parseNodeArgs(item.value.value.split(' '));
        if (args.require)
            for (const id of [args.require].flat())
                inputs.push(toModule(id));
    }
    return inputs;
};
export const getDependenciesFromCommand = (node, options, fromWords = options.fromArgs) => {
    const text = node.name?.value;
    if (!text)
        return [];
    const binary = extractBinary(text);
    if (!binary || binary === '.' || binary === 'source' || binary === '[')
        return [];
    if (binary.startsWith('-') || binary.startsWith('..'))
        return [];
    const isExplicitBin = isInNodeModulesBin(text) || text.startsWith('.bin/');
    if (options.optionalBinaries && (isExplicitBin || isPackageManager(binary))) {
        const { fromArgs } = options;
        options = {
            ...options,
            optionalBinaries: !isExplicitBin,
            fromArgs: (args, opts) => fromArgs(args, { optionalBinaries: false, ...opts }),
        };
    }
    const { fromArgs } = options;
    const words = getCommandWords(node);
    if (binary === '!' || binary === 'test')
        return fromArgs(words);
    const fromNodeOptions = getInputsFromNodeOptions(node.prefix);
    if (binary in KnownResolvers) {
        const resolver = KnownResolvers[binary];
        return [...resolver(binary, words, options), ...fromNodeOptions];
    }
    if (pluginArgsMap.has(binary)) {
        return [...resolverFromPlugins(binary, words, options), ...fromNodeOptions];
    }
    if (spawningBinaries.includes(binary)) {
        return [
            toCommandBinary(binary, options),
            ...fromWords(getWrappedCommand(binary, words, options.cwd) ?? [], options),
            ...fromNodeOptions,
        ];
    }
    if (binary in Plugins) {
        const inputs = fallbackResolve(binary, words, options);
        if (options.isForwardedArgs)
            for (const input of inputs)
                input.optional = true;
        return [...inputs, ...fromNodeOptions];
    }
    if (options.isForwardedArgs && !text.startsWith('.') && !isRelativeNodeModulesBin(text))
        return [];
    return [...fallbackResolve(binary, words, options), ...fromNodeOptions];
};
