import { IOptions } from './options';
/**
 * Check if `vhost` is a valid suffix of `hostname` (top-domain)
 *
 * It means that `vhost` needs to be a suffix of `hostname` and we then need to
 * make sure that: either they are equal, or the character preceding `vhost` in
 * `hostname` is a '.' (it should not be a partial label).
 *
 * * hostname = 'not.evil.com' and vhost = 'vil.com'      => not ok
 * * hostname = 'not.evil.com' and vhost = 'evil.com'     => ok
 * * hostname = 'not.evil.com' and vhost = 'not.evil.com' => ok
 */
export declare function shareSameDomainSuffix(hostname: string, vhost: string): boolean;
/**
 * Detects the domain based on rules and upon and a host string
 */
export default function getDomain(suffix: string, hostname: string, options: IOptions): string | null;
