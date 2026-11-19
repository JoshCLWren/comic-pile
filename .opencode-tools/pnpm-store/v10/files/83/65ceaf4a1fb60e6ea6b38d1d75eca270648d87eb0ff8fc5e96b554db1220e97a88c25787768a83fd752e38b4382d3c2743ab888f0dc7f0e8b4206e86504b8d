import { toAbsolute } from '../../util/path.js';
import { toEntryPath, toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Lunaria';
const enablers = ['@lunariajs/core', '@lunariajs/starlight'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['lunaria.config.json'];
const resolveConfig = async (localConfig, options) => {
    if (!localConfig)
        return [];
    const files = localConfig.files?.map(f => f.location) ?? [];
    const renderer = localConfig.renderer ? [localConfig.renderer] : [];
    const customCss = localConfig.dashboard?.customCss ?? [];
    const favicon = localConfig.dashboard?.favicon?.inline ? [localConfig.dashboard.favicon.inline] : [];
    const baseDir = options.configFileDir;
    return [
        ...files.map(id => toEntry(toAbsolute(id, baseDir), { production: true })),
        ...[...renderer, ...customCss, ...favicon].map(id => toEntryPath(toAbsolute(id, baseDir), { production: true })),
    ];
};
const args = {
    binaries: ['lunaria'],
    config: ['config'],
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
