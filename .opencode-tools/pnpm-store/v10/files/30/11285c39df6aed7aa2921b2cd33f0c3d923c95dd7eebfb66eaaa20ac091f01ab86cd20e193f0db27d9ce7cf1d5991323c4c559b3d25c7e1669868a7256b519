import type { ArithmeticExpression, ArithmeticWord } from "./internal-types.ts";
import { ScriptExpansionImpl } from "./expansion.ts";
export interface ArithmeticParseCollector {
    embeddedWords: ArithmeticWord[];
    commandExpansion: (pos: number, end: number, text: string) => ScriptExpansionImpl<"ArithmeticCommandExpansion">;
    findClosingBracket?: (start: number, end: number) => number;
    findClosingBrace: (start: number, end: number) => number;
    findClosingParenthesis: (start: number, end: number) => number;
    findArithmeticExpansionEnd: (start: number, end: number) => number;
    findArithmeticWordEnd?: (start: number, end: number) => number;
}
export declare function parseArithmeticExpression(src: string, offset?: number, collector?: ArithmeticParseCollector, nestingDepth?: number): ArithmeticExpression | null;
