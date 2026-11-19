import { getUrlSpecifier, isScopedPackage, isTildePackage, splitSpec } from './shared.js';
import { hasUrlScheme } from '../util/url.js';
const dependencies = ['sass', 'sass-embedded', 'node-sass'];
const dependencyMatcher = /"(?:\\(?:\r\n|[\s\S]|$)|[^"\\\r\n\f])*(?:"|[\r\n\f]|$)|'(?:\\(?:\r\n|[\s\S]|$)|[^'\\\r\n\f])*(?:'|[\r\n\f]|$)|\/\*[\s\S]*?(?:\*\/|$)|\/\/[^\r\n]*(?:[\r\n]|$)|@(?:use|import|forward)\s+['"](pkg:)?([^'"]+)['"]|url\(\s*(?:["']([^"'\r\n]*)["']|([^'")\s]+))\s*\)/g;
const candidates = (specifier) => {
    const { dir, name } = splitSpec(specifier);
    const hasExt = name.endsWith('.scss') || name.endsWith('.sass');
    const bases = hasExt ? [name] : [`${name}.scss`, `${name}.sass`];
    const out = [];
    for (const base of bases) {
        out.push(`${dir}/${base}`);
        if (!name.startsWith('_'))
            out.push(`${dir}/_${base}`);
    }
    return out;
};
export const compiler = text => {
    if (!text.includes('@use') && !text.includes('@import') && !text.includes('@forward') && !text.includes('url('))
        return '';
    const out = [];
    let i = 0;
    let match;
    dependencyMatcher.lastIndex = 0;
    while ((match = dependencyMatcher.exec(text))) {
        const url = match[3] ?? match[4];
        if (url !== undefined) {
            const spec = getUrlSpecifier(url);
            if (spec)
                out.push(`import _$${i++} from '${spec}';`);
            continue;
        }
        let spec = match[2];
        if (!spec || spec.startsWith('//') || hasUrlScheme(spec))
            continue;
        let isBare = Boolean(match[1]) || isScopedPackage(spec);
        if (isTildePackage(spec)) {
            spec = spec.slice(1);
            isBare = true;
        }
        if (isBare) {
            out.push(`import _$${i++} from '${spec}';`);
        }
        else {
            for (const s of candidates(spec))
                out.push(`import _$${i++} from '${s}';`);
        }
    }
    return out.join('\n');
};
export default { dependencies, compiler };
