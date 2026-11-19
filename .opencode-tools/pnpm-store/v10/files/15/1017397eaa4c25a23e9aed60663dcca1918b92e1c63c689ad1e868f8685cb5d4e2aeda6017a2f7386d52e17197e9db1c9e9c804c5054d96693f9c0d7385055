import type { Exports, PackageJson } from '../types/package-json.ts';
declare const INDENT: unique symbol;
declare const NEWLINE: unique symbol;
interface ExtendedPackageJson extends PackageJson {
    [INDENT]?: string;
    [NEWLINE]?: string;
}
export declare const getEntriesFromExports: (obj: any) => string[];
export declare const toDeclarationSpecifier: (specifier: string) => string | undefined;
export declare const getPublishedTypeManifest: (manifest: PackageJson) => PackageJson;
export declare const getPublishedTypeExportSpecifiers: (exports: PackageJson['exports']) => Set<string>;
export declare const getPublishedTypeEntrySpecifiers: (manifest: PackageJson) => {
    candidates: string[];
    versioned: Set<string>;
};
export declare const getPackageMapTarget: (map: Exports, key: string) => {
    target: Exports;
    subpath: string;
    patternMatch?: undefined;
} | {
    target: Exports;
    subpath: string;
    patternMatch: string;
} | undefined;
export declare const expandPackageTarget: (target: string | undefined, patternMatch: string | undefined) => string | undefined;
export declare const toPackagePath: (dir: string, target: string) => string | undefined;
export declare const getPackageTargetPaths: (value: unknown, dir: string, patternMatch: string | undefined, isIncludeTypes: boolean, paths?: string[]) => string[];
export declare const getExportEntries: (exports: NonNullable<PackageJson['exports']>) => [string, Exports][] | (readonly [".", NonNullable<Exports | undefined>])[];
export declare const isPublishedTypeExportTarget: (exports: PackageJson['exports'], candidate: string) => boolean;
export declare const load: (filePath: string) => Promise<ExtendedPackageJson>;
export declare const save: (filePath: string, content: ExtendedPackageJson) => Promise<void>;
export declare const getEntrySpecifiersFromManifest: (manifest: PackageJson, isIncludeSubpathExports?: boolean) => Set<string>;
export type Manifest = PackageJson & {
    scriptNames: Set<string>;
    getMajor: (name: string) => number | undefined;
};
export declare const createManifest: (raw: PackageJson) => Manifest;
export declare const getManifestImportDependencies: (manifest: PackageJson) => Set<string>;
export {};
