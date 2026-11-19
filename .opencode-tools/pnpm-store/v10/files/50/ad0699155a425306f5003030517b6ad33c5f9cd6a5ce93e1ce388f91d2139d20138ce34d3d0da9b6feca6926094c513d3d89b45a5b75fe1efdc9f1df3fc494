import { toModule } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Payload CMS';
const enablers = ['payload'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['payload.config.{js,ts}', 'src/payload.config.{js,ts}'];
const resolveConfig = async (config) => {
    const awaitedConfig = await config;
    const importMapFile = awaitedConfig?.admin?.importMap?.importMapFile;
    if (importMapFile) {
        return [toModule(importMapFile, { optional: true })];
    }
    const adminRoute = awaitedConfig?.routes?.admin ?? '/admin';
    const possibleImportMapPaths = [
        `app/(payload)${adminRoute}/importMap.js`,
        `src/app/(payload)${adminRoute}/importMap.js`,
    ];
    return possibleImportMapPaths.map(id => toModule(id, { optional: true }));
};
const project = ['!migrations/**', '!src/migrations/**', '!payload-types.ts', '!src/payload-types.ts'];
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    project,
};
export default plugin;
