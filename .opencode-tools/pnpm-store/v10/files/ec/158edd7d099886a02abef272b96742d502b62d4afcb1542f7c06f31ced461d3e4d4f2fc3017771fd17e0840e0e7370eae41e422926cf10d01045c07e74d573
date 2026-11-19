import type { HereDocBody, WordPart } from "./internal-types.ts";
import type { SubstitutionContext } from "./substitution-context.ts";
export declare class HereDocBodyImpl implements HereDocBody {
    #private;
    type: "HereDocBody";
    pos: number;
    end: number;
    text: string;
    constructor(source: string, pos: number, quoted: boolean, depth: number, context: SubstitutionContext);
    get parts(): WordPart[] | undefined;
    toJSON(): {
        type: "HereDocBody";
        pos: number;
        end: number;
        text: string;
        parts: WordPart[] | undefined;
    };
}
