import type { MainOptions } from '../util/create-options.ts';
import type { WatchChange } from '../util/watch.ts';
export declare class SessionConfigurationChangedError extends Error {
    constructor(filePath: string);
}
export declare class ConfigurationFiles {
    paths: Set<string>;
    private importers;
    private matchers;
    constructor(options: MainOptions);
    addPatterns(dir: string, patterns: string[]): void;
    addImport(importer: string, imported: string): void;
    getAffected(changes: WatchChange[], cwd: string): Set<string>;
    getChange(changes: WatchChange[], cwd: string): SessionConfigurationChangedError | undefined;
}
