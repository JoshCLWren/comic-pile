import type { Word, WordPart } from "./internal-types.ts";
import type { PartsResolver } from "./word.ts";
import { type SubstitutionContext } from "./substitution-context.ts";
export declare const computeBareWordParts: PartsResolver;
export declare function wordPartsResolver(context: SubstitutionContext): PartsResolver;
export declare function embeddedPartsResolver(context: SubstitutionContext): PartsResolver;
export declare function arrayPartsResolver(context: SubstitutionContext): PartsResolver;
/**
 * Compute the structural parts of a word by re-scanning the source.
 * This is the "cold path" — only called when consumers actually need parts.
 *
 * Returns undefined for simple words (no quotes, expansions, or special structure).
 */
export declare function computeWordParts(source: string, word: Pick<Word, "pos" | "end">, depth?: number, context?: SubstitutionContext): WordPart[] | undefined;
/** Compute structural parts for a word-like span that may contain shell operators or whitespace. */
export declare function computeEmbeddedWordParts(source: string, word: Pick<Word, "pos" | "end">, depth: number | undefined, context: SubstitutionContext, arithmetic?: boolean): WordPart[] | undefined;
export declare function computeArrayElementParts(source: string, word: Word, depth: number | undefined, context: SubstitutionContext): WordPart[] | undefined;
/**
 * Compute parts for an unquoted heredoc body.
 * Heredoc bodies use different scanning rules than shell words: newlines are
 * literal and single/double quotes have no special meaning.
 */
export declare function computeHereDocBodyParts(source: string, word: Pick<Word, "pos" | "end">, depth: number | undefined, context: SubstitutionContext): WordPart[] | undefined;
