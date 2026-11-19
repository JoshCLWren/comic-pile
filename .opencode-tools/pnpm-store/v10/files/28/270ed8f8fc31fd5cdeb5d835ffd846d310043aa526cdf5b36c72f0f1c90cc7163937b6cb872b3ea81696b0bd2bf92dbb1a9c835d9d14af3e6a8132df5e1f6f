export class PackagePeeker {
    manifestStr;
    constructor(manifestStr) {
        this.manifestStr = manifestStr;
    }
    getCatalogReferenceLocation(packageName, catalogName) {
        const property = `"${packageName}"`;
        const value = `"catalog:${catalogName === 'default' ? '' : catalogName}"`;
        let propertyPos = this.manifestStr.indexOf(property);
        while (propertyPos !== -1) {
            const colonPos = this.manifestStr.indexOf(':', propertyPos + property.length);
            let valuePos = colonPos + 1;
            while (valuePos > 0 && this.manifestStr[valuePos]?.trim() === '')
                valuePos++;
            if (colonPos !== -1 && this.manifestStr.startsWith(value, valuePos))
                return this.toLocation(propertyPos + 1);
            propertyPos = this.manifestStr.indexOf(property, propertyPos + property.length);
        }
    }
    getPropertyLocation(section, property) {
        const str = this.manifestStr;
        let depth = 0;
        let isInSection = false;
        for (let i = 0; i < str.length; i++) {
            const ch = str[i];
            if (ch === '"') {
                const start = i + 1;
                let end = start;
                while (end < str.length && str[end] !== '"')
                    end += str[end] === '\\' ? 2 : 1;
                let next = end + 1;
                while (str.charCodeAt(next) <= 32)
                    next++;
                if (str[next] === ':') {
                    const key = str.slice(start, end);
                    if (depth === 1) {
                        isInSection = key === section;
                        if (isInSection && property === undefined)
                            return this.toLocation(start);
                    }
                    else if (depth === 2 && isInSection && key === property)
                        return this.toLocation(start);
                }
                i = end;
            }
            else if (ch === '{' || ch === '[')
                depth++;
            else if (ch === '}' || ch === ']')
                depth--;
        }
    }
    toLocation(pos) {
        let line = 1;
        let lineStart = 0;
        for (let index = 0; index < pos; index++) {
            if (this.manifestStr[index] === '\n') {
                line++;
                lineStart = index + 1;
            }
        }
        return { line, col: pos - lineStart + 1, pos };
    }
}
