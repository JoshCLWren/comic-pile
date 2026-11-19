import { arrayify } from '../../util/array.js';
import { toModule, toEntryPath, toEntry } from '../../util/input.js';
import { join, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Playwright';
const enablers = ['@playwright/test'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['playwright.config.{js,cjs,mjs,ts,cts,mts}'];
export const entry = ['**/*.@(spec|test).?(c|m)[jt]s?(x)'];
const toEntryPatterns = (testMatch, configDir, localConfig, rootConfig) => {
    const testDir = localConfig.testDir ?? rootConfig.testDir;
    const dir = testDir ? toAbsolute(testDir, configDir) : configDir;
    const patterns = [testMatch].flat().filter((p) => typeof p === 'string');
    return patterns.map(pattern => toEntry(join(dir, pattern)));
};
const builtinReporters = ['dot', 'line', 'list', 'junit', 'html', 'blob', 'json', 'github', 'null'];
export const resolveConfig = async (localConfig, options) => {
    const { configFileDir } = options;
    const inputs = [];
    for (const id of arrayify(localConfig.globalSetup))
        inputs.push(toEntryPath(toAbsolute(id, configFileDir)));
    for (const id of arrayify(localConfig.globalTeardown))
        inputs.push(toEntryPath(toAbsolute(id, configFileDir)));
    for (const server of [localConfig.webServer].flat()) {
        if (!server?.command)
            continue;
        const dir = server.cwd ? toAbsolute(server.cwd, configFileDir) : configFileDir;
        for (const input of options.getInputsFromScripts(server.command, {
            optionalBinaries: true,
            cwd: dir,
            manifest: options.getManifest(dir) ?? options.manifest,
        })) {
            inputs.push({ ...input, dir: input.dir ?? dir });
        }
    }
    const projects = localConfig.projects ? [localConfig, ...localConfig.projects] : [localConfig];
    const reporters = [localConfig.reporter].flat().flatMap(reporter => {
        const name = typeof reporter === 'string' ? reporter : reporter?.[0];
        if (!name || builtinReporters.includes(name))
            return [];
        return [name];
    });
    return projects
        .flatMap(config => toEntryPatterns(config.testMatch ?? entry, configFileDir, config, localConfig))
        .concat(reporters.map(id => toModule(id)))
        .concat(inputs);
};
const args = {
    positional: true,
    args: (args) => args.filter(arg => arg !== 'install' && arg !== 'test'),
    config: true,
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    resolveConfig,
    args,
};
export default plugin;
