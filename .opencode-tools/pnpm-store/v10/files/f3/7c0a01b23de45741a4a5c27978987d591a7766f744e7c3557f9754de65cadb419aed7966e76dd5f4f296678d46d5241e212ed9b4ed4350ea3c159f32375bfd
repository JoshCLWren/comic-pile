import type { PartsResolver } from "./word.ts";
export interface SubstitutionContext {
    boundaries: Map<number, number> | undefined;
    wordParts: PartsResolver | undefined;
    embeddedParts: PartsResolver | undefined;
    arrayParts: PartsResolver | undefined;
}
export declare function createSubstitutionContext(parent?: SubstitutionContext): SubstitutionContext;
export declare function substitutionBoundaries(context: SubstitutionContext): Map<number, number>;
