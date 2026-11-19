import picomatch from 'picomatch';
import { KNIP_CONFIG_LOCATIONS } from '../constants.js';
import { isAbsolute, isInNodeModules, join, relative, toAbsolute, toPosix, toRelative } from '../util/path.js';
export class SessionConfigurationChangedError extends Error {
    constructor(filePath) {
        super(`Configuration changed (${filePath})`);
    }
}
export class ConfigurationFiles {
    paths = new Set();
    importers = new Map();
    matchers = [];
    constructor(options) {
        const manifests = [];
        for (const pattern of options.workspaces)
            manifests.push(join(pattern, 'package.json'));
        this.addPatterns(options.cwd, [...KNIP_CONFIG_LOCATIONS, 'pnpm-workspace.yaml', '**/.gitignore', ...manifests]);
        if (options.configFilePath)
            this.paths.add(options.configFilePath);
        for (const filePath of options.preprocessorInputs)
            if (isAbsolute(filePath))
                this.paths.add(filePath);
    }
    addPatterns(dir, patterns) {
        const included = [];
        const excluded = [];
        for (const pattern of patterns) {
            if (pattern.startsWith('!'))
                excluded.push(toRelative(pattern.slice(1), dir));
            else
                included.push(toRelative(pattern, dir));
        }
        if (included.length > 0)
            this.matchers.push({ dir, isMatch: picomatch(included, { dot: true, ignore: excluded }) });
    }
    addImport(importer, imported) {
        this.paths.add(imported);
        const importers = this.importers.get(imported);
        if (importers)
            importers.add(importer);
        else
            this.importers.set(imported, new Set([importer]));
    }
    getAffected(changes, cwd) {
        const affected = new Set();
        for (const change of changes)
            affected.add(toAbsolute(toPosix(change.filePath), cwd));
        for (const filePath of affected) {
            for (const importer of this.importers.get(filePath) ?? [])
                affected.add(importer);
        }
        return affected;
    }
    getChange(changes, cwd) {
        for (const change of changes) {
            const filePath = toAbsolute(toPosix(change.filePath), cwd);
            if (this.paths.has(filePath) ||
                (!isInNodeModules(filePath) && this.matchers.some(({ dir, isMatch }) => isMatch(relative(dir, filePath)))))
                return new SessionConfigurationChangedError(toRelative(filePath, cwd));
        }
    }
}
