import { toEntryPath } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'pm2';
const enablers = ['pm2'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['pm2.config.{json,js,cjs,mjs}', 'ecosystem.config.{json,js,cjs,mjs}'];
const addApplicationEntry = (application, entries, cwd) => {
    if (application.script && isInternal(application.script))
        entries.push(toEntryPath(application.script, { dir: cwd }));
};
const resolveConfig = (config, { cwd }) => {
    const entries = [];
    if (Array.isArray(config)) {
        for (const application of config)
            addApplicationEntry(application, entries, cwd);
        return entries;
    }
    addApplicationEntry(config, entries, cwd);
    if (!config.apps)
        return entries;
    const applications = Array.isArray(config.apps) ? config.apps : [config.apps];
    for (const application of applications)
        addApplicationEntry(application, entries, cwd);
    return entries;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
