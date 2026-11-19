import { isDirectory } from '../../util/fs.js';
import { toModule } from '../../util/input.js';
import { toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'AWS CDK';
const enablers = ['aws-cdk', 'aws-cdk-lib'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['cdk.json'];
const resolveConfig = (localConfig, options) => {
    const scripts = [localConfig.build, localConfig.app].filter((script) => typeof script === 'string');
    const inputs = options.getInputsFromScripts(scripts, { optionalBinaries: true, cwd: options.configFileDir });
    for (const id of localConfig.plugin ?? [])
        inputs.push(toModule(id));
    return inputs;
};
const args = {
    binaries: ['cdk'],
    string: ['app'],
    alias: { app: ['a'] },
    fromArgs: (parsed, _, { cwd }) => typeof parsed.app === 'string' && parsed.app.includes(' ') && !isDirectory(toAbsolute(parsed.app, cwd))
        ? parsed.app
        : [],
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    args,
};
export default plugin;
