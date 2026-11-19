import type { FileNode, ModuleGraph } from '../../types/module-graph.ts';
export interface ExportOrigin {
    filePath: string;
    identifier: string;
}
export interface ExportOriginResolution {
    origins: ExportOrigin[];
    hasExplicitExport: boolean;
}
export interface ExportTableEntry {
    origins: ReadonlyMap<string, ExportOrigin>;
    hasExplicitExport: boolean;
}
export type ExportTable = Map<string, ExportTableEntry>;
export interface ExportTableCache {
    entries: ExportTable;
    complete: boolean;
}
interface ExportInfo {
    node: FileNode | undefined;
    references: Map<string, ExportOrigin[]>;
    terminals: Map<string, ExportOrigin[]>;
    stars: string[];
}
export declare const createExportResolver: (graph: ModuleGraph) => {
    getTable: (filePath: string) => ExportTable;
    resolve: (filePath: string, identifier: string) => ExportTableEntry | undefined;
    getInfo: (filePath: string) => ExportInfo;
    reachesOrigin: (source: ExportOrigin, origin: ExportOrigin, site: ExportOrigin) => boolean;
};
export declare const resolveExportOrigins: (graph: ModuleGraph, filePath: string, identifier: string) => ExportOriginResolution;
export {};
