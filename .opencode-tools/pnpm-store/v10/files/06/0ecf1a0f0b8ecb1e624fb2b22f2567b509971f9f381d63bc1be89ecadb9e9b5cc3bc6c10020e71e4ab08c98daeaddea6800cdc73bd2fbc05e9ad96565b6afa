import { toModule } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
import { isObject } from '../../util/validation.js';
const title = 'electron-builder';
const enablers = ['electron-builder'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const packageJsonPath = 'build';
const config = ['package.json', 'electron-builder.{yml,yaml,json,json5,toml,js,cjs,ts}'];
const hooks = [
    'beforePack',
    'afterExtract',
    'afterPack',
    'afterSign',
    'artifactBuildStarted',
    'artifactBuildCompleted',
    'afterAllArtifactBuild',
    'msiProjectCreated',
    'appxManifestCreated',
    'onNodeModuleFile',
    'beforeBuild',
];
const resolveConfig = async (config, options) => {
    const request = {
        packageKey: 'build',
        configFilename: 'electron-builder',
        projectDir: options.cwd,
        packageMetadata: { value: Promise.resolve(options.manifest) },
    };
    const localConfig = typeof config === 'function' ? await config(request) : config;
    if (!isObject(localConfig))
        return [];
    const ids = [];
    for (const hook of hooks)
        ids.push(localConfig[hook]);
    for (const target of [localConfig.mac, localConfig.mas, localConfig.masDev]) {
        if (isObject(target))
            ids.push(target.sign);
    }
    const win = localConfig.win;
    if (isObject(win) && isObject(win.signtoolOptions))
        ids.push(win.signtoolOptions.sign);
    const inputs = [];
    for (const id of ids)
        if (typeof id === 'string')
            inputs.push(toModule(id, { dir: options.cwd }));
    return inputs;
};
const args = {
    config: true,
    args: (args) => args.filter(arg => !/^--?c(onfig)?\./.test(arg)),
};
const plugin = {
    title,
    enablers,
    isEnabled,
    packageJsonPath,
    config,
    resolveConfig,
    args,
};
export default plugin;
