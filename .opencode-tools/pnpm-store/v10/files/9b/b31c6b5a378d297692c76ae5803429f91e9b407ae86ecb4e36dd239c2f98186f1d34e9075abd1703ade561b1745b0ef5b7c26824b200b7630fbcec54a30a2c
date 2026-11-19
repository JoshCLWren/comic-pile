import type { ModuleGraph } from '../types/module-graph.ts';
import { isReferenced } from './operations/is-referenced.ts';
export declare const createGraphExplorer: (graph: ModuleGraph, entryPaths: Set<string>, cacheUsage?: boolean) => {
    isReferenced: (filePath: string, identifier: string, options: Parameters<typeof isReferenced>[4]) => readonly [false, string | undefined, Set<string> | undefined];
    hasStrictlyNsReferences: (filePath: string, identifier: string) => [boolean, (string | undefined)?];
    isEnumerated: (filePath: string, identifier: string) => boolean;
    buildExportsTree: (options: {
        filePath?: string;
        identifier?: string;
    }) => import("./operations/build-exports-tree.ts").ExportsTreeNode[];
    resolveExportOrigins: (filePath: string, identifier: string) => import("./operations/resolve-export-origins.ts").ExportOriginResolution;
    getDependencyUsage: (pattern?: string | RegExp) => Map<string, import("./operations/get-dependency-usage.ts").DependencyNodes>;
    resolveDefinition: (filePath: string, identifier: string) => import("./operations/resolve-definition.ts").DefinitionResult | null;
    getUsage: (filePath: string, identifier: string) => import("./operations/get-usage.ts").UsageResult;
    findCycles: (filePath: string, maxDepth?: number) => import("../session/types.ts").Cycle[];
    findAllCycles: (ignoredFlags?: number) => import("../session/types.ts").Cycle[];
    getContention: (filePath: string) => Map<string, import("../session/types.ts").ContentionDetails>;
    invalidateCache: () => void;
};
export type GraphExplorer = ReturnType<typeof createGraphExplorer>;
