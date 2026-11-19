import { toModule, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Commitizen';
const enablers = ['commitizen'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const isRootOnly = true;
const packageJsonPath = 'config.commitizen';
const config = ['.czrc', '.cz.json', 'package.json'];
const resolveConfig = (config, options) => {
    if (!config.path)
        return [];
    return [isInternal(config.path) ? toModule(config.path, { dir: options.cwd }) : toDependency(config.path)];
};
const plugin = {
    title,
    enablers,
    isEnabled,
    isRootOnly,
    packageJsonPath,
    config,
    resolveConfig,
};
export default plugin;
