import { toModule, toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Cucumber';
const enablers = ['@cucumber/cucumber'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['cucumber.{json,yaml,yml,js,cjs,mjs}'];
const entry = ['features/**/*.@(js|cjs|mjs)'];
const builtinFormatters = new Set([
    'html',
    'json',
    'junit',
    'message',
    'pretty',
    'progress',
    'progress-bar',
    'rerun',
    'snippets',
    'summary',
    'usage',
    'usage-json',
]);
const toFormatterName = (format) => {
    if (Array.isArray(format))
        return format[0];
    const [name, quotedName] = format.match(/^"([^"]*)"|^[^:]*/) ?? [format];
    return quotedName ?? name;
};
const resolveProfile = (config) => {
    const imports = (config?.import ? config.import : entry).map(id => toEntry(id));
    const requires = (config?.require ? config.require : []).map(id => toEntry(id));
    const formatters = (config?.format ? config.format : [])
        .map(toFormatterName)
        .filter(name => !builtinFormatters.has(name))
        .map(id => toModule(id));
    return [...imports, ...requires, ...formatters];
};
const resolveConfig = (config, options) => {
    if (typeof config !== 'object' || config === null)
        return resolveProfile();
    const isProfiles = /\.(json|ya?ml)$/.test(options.configFileName) || 'default' in config;
    if (!isProfiles)
        return resolveProfile(config);
    const profiles = 'default' in config ? Object.values(config) : [undefined, ...Object.values(config)];
    return profiles.flatMap(resolveProfile);
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    resolveConfig,
};
export default plugin;
