import { forEachChild, parse } from 'unbash';
import { getDependenciesFromCommand, getInputsFromNodeOptions } from '../../binaries/command.js';
import { spawningBinaries } from '../../binaries/fallback.js';
import { isWrapper, toForwardedScript } from '../../binaries/plugins.js';
import { isPackageManager } from '../../binaries/resolvers/index.js';
import { SCRIPT_INTERPOLATION } from '../../constants.js';
import { isBinary } from '../../util/input.js';
import { extractBinary, isRelativeNodeModulesBin } from '../../util/modules.js';
import { isScriptExpansion, collectCommands } from '../../util/scripts.js';
export const getInputsFromMiseScript = (script, options, hasLocalBinPath) => {
    const inputs = [];
    const definedFunctions = new Set();
    const readCommand = (command, source) => {
        let text = '';
        let cursor = command.pos;
        const visit = (node) => {
            if (!isScriptExpansion(node)) {
                forEachChild(node, visit);
                return;
            }
            if (node.script)
                readScript(node.script, node.script.source ?? source);
            if (node.pos >= cursor && node.end <= command.end) {
                text += source.slice(cursor, node.pos) + SCRIPT_INTERPOLATION;
                cursor = node.end;
            }
        };
        forEachChild(command, visit);
        return text + source.slice(cursor, command.end);
    };
    const readScript = (parsed, source) => {
        for (const statement of parsed.commands) {
            if (statement.command.type === 'Function')
                definedFunctions.add(statement.command.name.value);
        }
        for (const command of collectCommands(parsed)) {
            const text = readCommand(command, source);
            const name = command.name?.value;
            if (!name || definedFunctions.has(name))
                continue;
            const binary = extractBinary(name);
            const isPackageCommand = isPackageManager(binary);
            const isExplicit = isPackageCommand || name.startsWith('./') || isRelativeNodeModulesBin(name);
            const hasPath = command.prefix.some(item => item.type === 'Assignment' && item.name === 'PATH');
            const isLocal = hasLocalBinPath && !hasPath;
            const isWrapperCommand = !isPackageCommand && isWrapper(binary);
            if (!isExplicit && !isLocal && !isWrapperCommand && binary !== 'node' && binary !== 'find')
                continue;
            let commandInputs;
            if (isWrapperCommand || binary === 'find') {
                const [marked] = collectCommands(parse(text));
                if (!marked)
                    continue;
                const fromScript = (script) => {
                    inputs.push(...getInputsFromMiseScript(script, options, isLocal));
                    return [];
                };
                const fromArgs = args => fromScript(toForwardedScript(args));
                commandInputs = getDependenciesFromCommand(marked, { ...options, fromArgs });
                if (spawningBinaries.includes(binary))
                    commandInputs.push(...getInputsFromNodeOptions(marked.prefix));
            }
            else {
                commandInputs = options.getInputsFromScripts(text, { cwd: options.cwd, manifest: options.manifest });
            }
            if (!isExplicit && !isLocal && binary !== 'node' && binary !== 'find')
                continue;
            const binaryInput = commandInputs.find(input => isBinary(input) && input.specifier === binary);
            if (!isExplicit && isLocal && binaryInput)
                binaryInput.optional = true;
            for (const input of commandInputs) {
                if (!input.specifier || input.specifier.includes(SCRIPT_INTERPOLATION))
                    continue;
                if (!isExplicit && !isLocal && input === binaryInput)
                    continue;
                inputs.push(input);
            }
        }
    };
    try {
        readScript(parse(script), script);
    }
    catch {
        return [];
    }
    return inputs;
};
