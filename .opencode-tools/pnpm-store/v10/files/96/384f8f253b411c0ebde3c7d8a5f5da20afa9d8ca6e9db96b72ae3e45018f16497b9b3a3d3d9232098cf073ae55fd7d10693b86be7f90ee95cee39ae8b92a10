import { hasDependency } from '../../util/plugin.js';
import { toShellCommand } from '../../util/scripts.js';
const title = 'Buf';
const enablers = ['@bufbuild/buf', '@bufbuild/protoc-gen-es'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['buf.gen.yaml'];
const args = {
    config: ['template'],
};
const resolveConfig = (config, options) => {
    const inputs = [];
    for (const plugin of config.plugins ?? []) {
        const name = plugin.plugin ?? plugin.name;
        const command = plugin.local ?? plugin.path ?? (name && !name.includes('/') ? `protoc-gen-${name}` : undefined);
        if (!command)
            continue;
        const script = toShellCommand(typeof command === 'string' ? [command] : command);
        for (const input of options.getInputsFromScripts(script, { optionalBinaries: true })) {
            input.dir ??= options.cwd;
            inputs.push(input);
        }
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    args,
    resolveConfig,
};
export default plugin;
