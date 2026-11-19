import type { ArithmeticExpression, ArithmeticExpansionPart, ParsedScript, ProcessSubstitutionPart } from "./internal-types.ts";
import type { parseRegion } from "./parser.ts";
import type { parseArithmeticWithParts } from "./arithmetic-parts.ts";
import type { SubstitutionContext } from "./substitution-context.ts";
type ScriptExpansionType = "CommandExpansion" | "ProcessSubstitution" | "ArithmeticCommandExpansion";
export interface ScriptWindow {
    readonly source: string;
    readonly start: number;
    readonly end: number;
    readonly depth: number;
    readonly parenBoundary: boolean;
    readonly context: SubstitutionContext | undefined;
}
export declare class ScriptExpansionImpl<T extends ScriptExpansionType> {
    #private;
    static _resolveScript: typeof parseRegion;
    type: T;
    pos: number;
    end: number;
    text: string;
    constructor(type: T, pos: number, end: number, text: string, window?: ScriptWindow);
    get script(): ParsedScript | undefined;
    set script(script: ParsedScript | undefined);
    toJSON(): {
        type: T;
        pos: number;
        end: number;
        text: string;
        script: ParsedScript | undefined;
    };
}
export declare class ProcessSubstitutionImpl extends ScriptExpansionImpl<"ProcessSubstitution"> {
    operator: "<" | ">";
    constructor(pos: number, end: number, text: string, operator: "<" | ">", window: ScriptWindow | undefined);
    toJSON(): ProcessSubstitutionPart;
}
export interface ArithmeticWindow {
    readonly source: string;
    readonly body: string;
    readonly offset: number;
    readonly depth: number;
    readonly context: SubstitutionContext;
}
export declare class ArithmeticExpansionImpl implements ArithmeticExpansionPart {
    #private;
    static _resolveExpression: typeof parseArithmeticWithParts;
    type: "ArithmeticExpansion";
    pos: number;
    end: number;
    text: string;
    constructor(pos: number, end: number, text: string, window: ArithmeticWindow);
    get expression(): ArithmeticExpression | undefined;
    set expression(expression: ArithmeticExpression | undefined);
    toJSON(): ArithmeticExpansionPart;
}
export {};
