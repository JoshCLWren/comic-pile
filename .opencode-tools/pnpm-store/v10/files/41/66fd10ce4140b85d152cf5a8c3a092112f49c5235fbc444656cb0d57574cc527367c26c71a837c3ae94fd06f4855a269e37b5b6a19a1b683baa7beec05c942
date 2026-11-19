const isRegexLikeMatch = /[*+\\(|{^$]/;
const isRegexLike = (value) => isRegexLikeMatch.test(value);
export const toRegexOrString = (value) => {
    if (typeof value !== 'string' || !isRegexLike(value))
        return value;
    try {
        return new RegExp(value);
    }
    catch {
        return value;
    }
};
export const findMatch = (haystack, needle) => haystack.find(n => (typeof n === 'string' ? n === needle : n.test(needle)));
