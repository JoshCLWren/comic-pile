import { toModule, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { toCosmiconfig } from '../../util/plugin-config.js';
const title = 'npm-package-json-lint';
const enablers = ['npm-package-json-lint'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const packageJsonPath = 'npmpackagejsonlint';
const config = ['package.json', ...toCosmiconfig('npmpackagejsonlint')];
const resolveConfig = (localConfig, options) => {
    if (!localConfig?.extends)
        return [];
    return [localConfig.extends].flat().map(id => {
        if (!isInternal(id))
            return toDependency(id);
        return id.startsWith('./') ? toModule(id, { dir: options.cwd }) : toModule(id);
    });
};
const plugin = {
    title,
    enablers,
    isEnabled,
    packageJsonPath,
    config,
    resolveConfig,
};
export default plugin;
