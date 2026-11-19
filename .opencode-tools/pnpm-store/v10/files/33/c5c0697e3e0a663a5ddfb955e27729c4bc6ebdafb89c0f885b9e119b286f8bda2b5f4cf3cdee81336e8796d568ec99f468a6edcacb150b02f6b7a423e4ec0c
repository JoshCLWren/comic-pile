import { arrayify } from '../../util/array.js';
import { toModule, toEntryPath } from '../../util/input.js';
import { join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'TypeDoc';
const enablers = ['typedoc'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const packageJsonPath = 'typedocOptions';
const config = [
    'typedoc.{js,cjs,mjs,json,jsonc}',
    'typedoc.config.{js,cjs,mjs}',
    '.config/typedoc.{js,cjs,mjs,json,jsonc}',
    '.config/typedoc.config.{js,cjs,mjs}',
    'package.json',
    'tsconfig.json',
];
const resolveConfig = (config, options) => {
    const cfg = 'typedocOptions' in config ? config.typedocOptions : config;
    const plugins = arrayify(cfg?.plugin);
    const themes = arrayify(cfg?.theme);
    const inputs = [...plugins, ...themes].map(id => toModule(id));
    for (const file of [cfg?.customCss, cfg?.customJs]) {
        if (file)
            inputs.push(toEntryPath(join(options.configFileDir, file)));
    }
    return inputs;
};
const args = {
    config: ['options'],
    resolve: ['plugin', 'theme'],
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
