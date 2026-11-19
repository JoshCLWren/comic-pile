import type { RawConfiguration } from '../types/config.ts';
import type { DependencySet } from '../types/workspace.ts';
import type { Compilers, RawCompilers } from './types.ts';
export declare const normalizeCompilerExtension: (ext: string) => string;
export declare const normalizeCompilers: (rawLocalConfig: RawConfiguration) => RawCompilers;
export declare const builtInCompilers: {
    dependencies: string[];
    compiler: import("./types.ts").CompilerSync;
    extensions: string[];
}[];
export declare const getIncludedCompilers: (rawCompilers: RawCompilers, dependencies: DependencySet, onReferencedDependency?: (packageName: string) => void) => Compilers;
