import { isDirectory } from '../../util/fs.js';
import { toConfig, toEntryPath } from '../../util/input.js';
const title = 'Maestro';
const enablers = 'This plugin is enabled when a `.maestro` folder is found.';
const isEnabled = ({ cwd }) => isDirectory(cwd, '.maestro');
const config = ['.maestro/**/*.{yaml,yml}'];
const parseConfig = async (source) => {
    const { parseAllDocuments } = await import('yaml');
    return parseAllDocuments(source, { logLevel: 'error' }).map(document => {
        if (document.errors.length > 0)
            throw document.errors[0];
        return document.toJS();
    });
};
const getFile = (value) => (typeof value === 'string' ? value : value?.file);
const addInputs = (commands, inputs) => {
    if (!Array.isArray(commands))
        return;
    for (const command of commands) {
        if (!command || typeof command !== 'object')
            continue;
        const script = getFile(command.runScript);
        if (typeof script === 'string')
            inputs.push(toEntryPath(script));
        for (const nested of [command.runFlow, command.retry]) {
            const flow = getFile(nested);
            if (typeof flow === 'string')
                inputs.push(toConfig('maestro', flow));
        }
        for (const nested of [command.runFlow, command.repeat, command.retry]) {
            if (nested && typeof nested === 'object')
                addInputs(nested.commands, inputs);
        }
    }
};
const resolveConfig = config => {
    const inputs = [];
    if (config.length === 2) {
        const [header, commands] = config;
        addInputs(header?.onFlowStart, inputs);
        addInputs(header?.onFlowComplete, inputs);
        addInputs(commands, inputs);
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    parseConfig,
    resolveConfig,
};
export default plugin;
