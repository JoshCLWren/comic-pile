import type { FileNode } from '../types/module-graph.ts';
export declare const isIncrementalFile: (file: FileNode) => boolean;
export declare const getFileTopology: (file: FileNode) => {
    internal: import("../types/module-graph.ts").ImportMap;
    paths: string[];
    imports: {
        specifier: string;
        filePath: string | undefined;
        identifier: string | undefined;
        alias: string | undefined;
        isTypeOnly: boolean;
        modifiers: number;
        jsDocTags: Set<string> | undefined;
    }[];
    external: {
        specifier: string;
        filePath: string | undefined;
        identifier: string | undefined;
        alias: string | undefined;
        isTypeOnly: boolean;
        modifiers: number;
        jsDocTags: Set<string> | undefined;
    }[];
    unresolved: {
        specifier: string;
        filePath: string | undefined;
        identifier: string | undefined;
        alias: string | undefined;
        isTypeOnly: boolean;
        modifiers: number;
        jsDocTags: Set<string> | undefined;
    }[];
    subpathImports: Map<string, string | undefined> | undefined;
    externalRefs: Set<import("../types/module-graph.ts").ExternalRef>;
    exports: {
        identifier: string;
        binding: string;
        type: import("../types/issues.ts").SymbolType;
        jsDocTags: Set<string>;
        hasRefsInFile: boolean;
        isRegistered: boolean;
        referencedIn: Set<string> | undefined;
        isReExport: boolean;
        isBindingReExport: boolean;
        members: {
            identifier: string;
            type: import("../types/issues.ts").SymbolType;
            flags: number;
            jsDocTags: Set<string>;
            hasRefsInFile: boolean;
        }[];
    }[];
    skipExports: boolean;
};
export declare const hasSameTopology: (before: ReturnType<typeof getFileTopology>, after: FileNode) => boolean;
