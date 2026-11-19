import { isFile } from '../../util/fs.js';
const title = 'Travis CI';
const enablers = 'This plugin is enabled when a `.travis.yml` file is found in the root folder.';
const isEnabled = ({ cwd }) => isFile(cwd, '.travis.yml');
const isRootOnly = true;
const config = ['.travis.yml'];
const resolveConfig = async (config, options) => {
    if (!config)
        return [];
    const beforeDeploy = config.before_deploy ?? [];
    const beforeInstall = config.before_install ?? [];
    const beforeScript = config.before_script ?? [];
    const scripts = [beforeDeploy, beforeInstall, beforeScript].flat();
    return options.getInputsFromScripts(scripts, { optionalBinaries: true });
};
const plugin = {
    title,
    enablers,
    isEnabled,
    isRootOnly,
    config,
    resolveConfig,
};
export default plugin;
