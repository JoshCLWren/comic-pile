import { toModule, toEntryPath, toDependency, toEntry } from '../../util/input.js';
import { get } from '../../util/object.js';
import { isInternal, join, normalize } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { isConfigurationOutput, isGraphqlConfigTypes, isGraphqlProjectsConfigTypes, isNearOperationFilePreset, } from './types.js';
const title = 'GraphQL Codegen';
const enablers = [/^@graphql-codegen\//, 'graphql-config'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const args = {
    config: true,
};
const packageJsonPath = manifest => get(manifest, 'codegen') ?? get(manifest, 'graphql');
const config = [
    'package.json',
    'codegen.{json,yml,yaml,js,ts}',
    '.codegenrc.{json,yml,yaml,js,ts}',
    'codegen.config.js',
    '.graphqlrc',
    '.graphqlrc.{json,yml,yaml,toml,js,ts}',
    'graphql.config.{json,yml,yaml,toml,js,cjs,ts}',
];
const getPluginPackageName = (name) => {
    if (name.startsWith('@') || name.includes('codegen-'))
        return name;
    return `@graphql-codegen/${name}`;
};
const getOutputInput = (output, outputConfig, dir) => {
    if (isConfigurationOutput(outputConfig) && isNearOperationFilePreset(outputConfig.preset)) {
        const presetConfig = outputConfig.presetConfig ?? {};
        const { folder = '', extension = '.generated.ts', fileName = '*', filePerOperation = false } = presetConfig;
        const subfolder = normalize(folder)
            .split('/')
            .filter(segment => segment !== '' && segment !== '.' && segment !== '..');
        return toEntry(join(dir, output, '**', ...subfolder, `${filePerOperation ? '*' : fileName}${extension}`), {
            production: true,
        });
    }
    return output.endsWith('/')
        ? toEntry(join(dir, `${output}**`), { production: true })
        : toEntryPath(output, { production: true, dir });
};
const resolveConfig = (config, options) => {
    const codegenConfigs = isGraphqlProjectsConfigTypes(config)
        ? Object.values(config.projects).flatMap(project => project.extensions?.codegen ?? [])
        : isGraphqlConfigTypes(config)
            ? [config.extensions?.codegen]
            : [config];
    const generateConfigs = codegenConfigs.filter((config) => Boolean(config?.generates));
    const generateSet = generateConfigs.flatMap(config => Object.values(config.generates));
    const outputs = generateConfigs
        .flatMap(config => Object.entries(config.generates))
        .map(([output, outputConfig]) => getOutputInput(output, outputConfig, options.configFileDir));
    const configurationOutput = generateSet.filter(isConfigurationOutput);
    const presets = configurationOutput
        .map(configOutput => (configOutput.preset ? configOutput.preset : undefined))
        .filter((preset) => typeof preset === 'string')
        .map(presetName => isInternal(presetName)
        ? toModule(presetName, { dir: options.cwd })
        : presetName.startsWith('@graphql-codegen/')
            ? presetName
            : `@graphql-codegen/${presetName}${presetName.endsWith('-preset') ? '' : '-preset'}`);
    const flatPlugins = generateSet
        .filter((config) => !isConfigurationOutput(config))
        .flatMap(item => Object.keys(item))
        .map(plugin => getPluginPackageName(plugin));
    const nestedPlugins = configurationOutput
        .flatMap(configOutput => (configOutput.plugins ? configOutput.plugins : []))
        .flatMap(plugin => {
        if (typeof plugin === 'object')
            return Object.keys(plugin);
        return [plugin];
    })
        .flatMap(plugin => {
        if (typeof plugin !== 'string')
            return [];
        if (isInternal(plugin))
            return [toEntryPath(plugin, { dir: options.cwd })];
        return [toDependency(getPluginPackageName(plugin))];
    });
    return [...presets, ...flatPlugins, ...nestedPlugins, ...outputs].map(id => typeof id === 'string' ? toDependency(id) : id);
};
const plugin = {
    title,
    args,
    enablers,
    isEnabled,
    packageJsonPath,
    config,
    resolveConfig,
};
export default plugin;
