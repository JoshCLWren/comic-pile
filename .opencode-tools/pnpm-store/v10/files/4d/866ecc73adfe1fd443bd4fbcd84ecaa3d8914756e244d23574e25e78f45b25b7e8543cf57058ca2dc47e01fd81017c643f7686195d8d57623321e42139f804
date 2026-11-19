const location = (path, key) => (path ? `${path}.${key}` : String(key));
export const invalid = (path, errors, expected, key) => {
    const details = [];
    if (path)
        details.push(`location: ${path}`);
    if (expected)
        details.push(`expected: ${expected}`);
    if (key !== undefined)
        details.push(`unrecognized_keys: ${key}`);
    errors.push(`Invalid input${details.length ? ` (${details.join(', ')})` : ''}`);
    return false;
};
export const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isRecord = (value) => {
    if (!isObject(value))
        return false;
    const constructor = value.constructor;
    return typeof constructor !== 'function' || Object.hasOwn(constructor.prototype ?? {}, 'isPrototypeOf');
};
export const checkString = (value, path, errors) => typeof value === 'string' || invalid(path, errors, 'string');
export const checkBoolean = (value, path, errors) => typeof value === 'boolean' || invalid(path, errors, 'boolean');
export const checkArray = (check) => (value, path, errors) => {
    if (!Array.isArray(value))
        return invalid(path, errors, 'array');
    const count = errors.length;
    for (let i = 0; i < value.length; i++)
        check(value[i], location(path, i), errors);
    return errors.length === count;
};
export const checkRecord = (check, isKey) => (value, path, errors) => {
    if (!isRecord(value))
        return invalid(path, errors, 'record');
    const count = errors.length;
    for (const key of Reflect.ownKeys(value)) {
        if (!Object.prototype.propertyIsEnumerable.call(value, key))
            continue;
        if (typeof key !== 'string')
            invalid(location(path, String(key)), errors);
        else if (isKey && !isKey(key))
            invalid(path, errors, undefined, key);
        else
            check(value[key], location(path, key), errors);
    }
    return errors.length === count;
};
export const checkObject = (value, path, errors, fields, extraFields = 'reject') => {
    if (!isObject(value))
        return invalid(path, errors, 'object');
    const count = errors.length;
    let unknownKeys;
    for (const key in value) {
        const check = Object.hasOwn(fields, key)
            ? fields[key]
            : typeof extraFields === 'function'
                ? extraFields(key)
                : undefined;
        if (check) {
            const item = value[key];
            if (item !== undefined)
                check(item, location(path, key), errors);
        }
        else if (extraFields !== 'ignore')
            unknownKeys = unknownKeys === undefined ? key : `${unknownKeys}, ${key}`;
    }
    if (unknownKeys !== undefined)
        invalid(path, errors, undefined, unknownKeys);
    return errors.length === count;
};
