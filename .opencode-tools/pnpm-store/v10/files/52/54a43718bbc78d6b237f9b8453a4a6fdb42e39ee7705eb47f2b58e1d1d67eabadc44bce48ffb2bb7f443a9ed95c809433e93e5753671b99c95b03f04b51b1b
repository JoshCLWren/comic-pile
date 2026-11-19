import { IOptions } from '../options';
import { IPublicSuffix } from './interface';
/**
 * Apply `options.extraSuffixes` to the built-in lookup result in `out`, as if
 * they were part of the list (`isException`: the built-in winner is an
 * exception rule). As in browsers, the longest match prevails and an exception
 * beats a rule of the same length. Remaining ties go to the built-in match
 * (unless it matched no rule: both flags falsy), then to `icann`.
 */
export default function extraSuffixLookup(hostname: string, options: IOptions, isException: boolean, out: IPublicSuffix): void;
