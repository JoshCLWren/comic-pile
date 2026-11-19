import type { ConfigParams } from '../rsbuild/types.ts';
type TestEnvironment = 'node' | 'jsdom' | 'happy-dom';
export type RstestProjectConfig = {
    root?: string;
    include?: string[];
    exclude?: string[] | {
        patterns: string[];
    };
    testEnvironment?: TestEnvironment | {
        name: TestEnvironment;
    };
    setupFiles?: string | string[];
    globalSetup?: string | string[];
    browser?: {
        enabled?: boolean;
    };
    resolve?: {
        alias?: Record<string, string | false | (string | false)[]>;
    };
};
type RstestConfig = RstestProjectConfig & {
    projects?: (string | RstestProjectConfig)[];
    coverage?: {
        provider?: 'istanbul' | 'v8';
    };
};
export type RstestConfigOrFn = RstestConfig | ((params: ConfigParams) => RstestConfig | Promise<RstestConfig>);
export {};
