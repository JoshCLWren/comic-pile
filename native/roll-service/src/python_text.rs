//! Python `str()` of a value decoded by `json.loads`, computed from the raw
//! JSON text (#4835, Greptile 4636390879).
//!
//! The retired `apply_metadata_correction` stored
//! `str(metadata_json.get(field, "")) or None` as a correction's provider
//! value. Matching it byte for byte needs the original JSON text: a decoded
//! `serde_json::Value` sorts object keys, while Python dicts keep document
//! order. The converter is a small recursive-descent JSON reader that renders
//! Python's spelling directly:
//!
//! - top-level strings are the raw text (`str("x") == "x"`);
//! - `null`/`true`/`false` are `None`/`True`/`False`;
//! - integers keep their exact digits (Python ints are unbounded);
//! - floats use `repr(float)` (shortest round trip, scientific below `1e-4`
//!   and from `1e16`, `inf` on overflow);
//! - lists and dicts use `repr`, with Python's string quoting and escapes, and
//!   a repeated dict key keeps its first position with the last value.

/// Python `str(json.loads(text))`, or `None` when `text` is not one JSON value.
pub(crate) fn python_str_of_json(text: &str) -> Option<String> {
    let mut reader = Reader {
        bytes: text.as_bytes(),
        text,
        at: 0,
    };
    let value = reader.value(0)?;
    reader.skip_ws();
    if reader.at != text.len() {
        return None;
    }
    Some(match value {
        Py::Str(raw) => raw,
        other => other.repr(),
    })
}

/// Nesting bound so hostile metadata cannot overflow the stack.
const MAX_DEPTH: usize = 128;

enum Py {
    None,
    Bool(bool),
    Int(String),
    Float(f64),
    Str(String),
    List(Vec<Py>),
    Dict(Vec<(String, Py)>),
}

impl Py {
    fn repr(&self) -> String {
        match self {
            Py::None => "None".to_owned(),
            Py::Bool(true) => "True".to_owned(),
            Py::Bool(false) => "False".to_owned(),
            Py::Int(digits) => digits.clone(),
            Py::Float(value) => float_repr(*value),
            Py::Str(text) => str_repr(text),
            Py::List(items) => {
                let inner: Vec<String> = items.iter().map(Py::repr).collect();
                format!("[{}]", inner.join(", "))
            }
            Py::Dict(entries) => {
                let inner: Vec<String> = entries
                    .iter()
                    .map(|(key, value)| format!("{}: {}", str_repr(key), value.repr()))
                    .collect();
                format!("{{{}}}", inner.join(", "))
            }
        }
    }
}

/// Python `repr(float)`.
fn float_repr(value: f64) -> String {
    if value.is_nan() {
        return "nan".to_owned();
    }
    if value.is_infinite() {
        return if value > 0.0 { "inf" } else { "-inf" }.to_owned();
    }
    if value == 0.0 {
        return if value.is_sign_negative() {
            "-0.0"
        } else {
            "0.0"
        }
        .to_owned();
    }
    // `{:e}` is the shortest round-trip digit string, like Python's repr.
    let scientific = format!("{value:e}");
    let (mantissa, exponent) = scientific
        .split_once('e')
        .map(|(m, e)| (m.to_owned(), e.parse::<i32>().unwrap_or(0)))
        .unwrap_or((scientific.clone(), 0));
    if (-4..16).contains(&exponent) {
        let plain = format!("{value}");
        if plain.contains('.') {
            plain
        } else {
            format!("{plain}.0")
        }
    } else {
        let sign = if exponent < 0 { '-' } else { '+' };
        format!("{mantissa}e{sign}{:02}", exponent.unsigned_abs())
    }
}

/// Python `repr(str)`: single quotes unless the text has a `'` and no `"`.
fn str_repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(text.len() + 2);
    out.push(quote);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if !python_printable(c) => {
                let code = c as u32;
                if code <= 0xff {
                    out.push_str(&format!("\\x{code:02x}"));
                } else if code <= 0xffff {
                    out.push_str(&format!("\\u{code:04x}"));
                } else {
                    out.push_str(&format!("\\U{code:08x}"));
                }
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Python `str.isprintable()` for one character: everything except the
/// Unicode "Other" (Cc, Cf, Co, Cn) and "Separator" (Zl, Zp, Zs except the
/// ASCII space) categories. Covers the ranges ComicVine text can contain.
fn python_printable(c: char) -> bool {
    let code = c as u32;
    !(code < 0x20
        || (0x7f..=0xa0).contains(&code)
        || code == 0xad
        || code == 0x1680
        || (0x2000..=0x200f).contains(&code)
        || (0x2028..=0x202f).contains(&code)
        || (0x205f..=0x2064).contains(&code)
        || (0x2066..=0x206f).contains(&code)
        || code == 0x3000
        || (0xe000..=0xf8ff).contains(&code)
        || code == 0xfeff
        || (0xfff9..=0xfffb).contains(&code)
        || (0xf0000..=0x10ffff).contains(&code))
}

struct Reader<'a> {
    bytes: &'a [u8],
    text: &'a str,
    at: usize,
}

impl Reader<'_> {
    fn skip_ws(&mut self) {
        while self
            .bytes
            .get(self.at)
            .is_some_and(|b| matches!(b, b' ' | b'\t' | b'\n' | b'\r'))
        {
            self.at += 1;
        }
    }

    fn eat(&mut self, literal: &str) -> bool {
        if self.text[self.at..].starts_with(literal) {
            self.at += literal.len();
            true
        } else {
            false
        }
    }

    fn value(&mut self, depth: usize) -> Option<Py> {
        if depth > MAX_DEPTH {
            return None;
        }
        self.skip_ws();
        match *self.bytes.get(self.at)? {
            b'n' if self.eat("null") => Some(Py::None),
            b't' if self.eat("true") => Some(Py::Bool(true)),
            b'f' if self.eat("false") => Some(Py::Bool(false)),
            b'"' => self.string().map(Py::Str),
            b'[' => {
                self.at += 1;
                let mut items = Vec::new();
                self.skip_ws();
                if self.eat("]") {
                    return Some(Py::List(items));
                }
                loop {
                    items.push(self.value(depth + 1)?);
                    self.skip_ws();
                    if self.eat("]") {
                        return Some(Py::List(items));
                    }
                    if !self.eat(",") {
                        return None;
                    }
                }
            }
            b'{' => {
                self.at += 1;
                let mut entries: Vec<(String, Py)> = Vec::new();
                self.skip_ws();
                if self.eat("}") {
                    return Some(Py::Dict(entries));
                }
                loop {
                    self.skip_ws();
                    if self.bytes.get(self.at) != Some(&b'"') {
                        return None;
                    }
                    let key = self.string()?;
                    self.skip_ws();
                    if !self.eat(":") {
                        return None;
                    }
                    let value = self.value(depth + 1)?;
                    match entries.iter_mut().find(|(existing, _)| *existing == key) {
                        Some(entry) => entry.1 = value,
                        None => entries.push((key, value)),
                    }
                    self.skip_ws();
                    if self.eat("}") {
                        return Some(Py::Dict(entries));
                    }
                    if !self.eat(",") {
                        return None;
                    }
                }
            }
            b'-' | b'0'..=b'9' => self.number(),
            _ => None,
        }
    }

    fn number(&mut self) -> Option<Py> {
        let start = self.at;
        if self.bytes.get(self.at) == Some(&b'-') {
            self.at += 1;
        }
        let digits = |reader: &mut Self| {
            let from = reader.at;
            while reader.bytes.get(reader.at).is_some_and(u8::is_ascii_digit) {
                reader.at += 1;
            }
            reader.at > from
        };
        if !digits(self) {
            return None;
        }
        let mut is_float = false;
        if self.bytes.get(self.at) == Some(&b'.') {
            self.at += 1;
            is_float = true;
            if !digits(self) {
                return None;
            }
        }
        if matches!(self.bytes.get(self.at), Some(b'e' | b'E')) {
            self.at += 1;
            is_float = true;
            if matches!(self.bytes.get(self.at), Some(b'+' | b'-')) {
                self.at += 1;
            }
            if !digits(self) {
                return None;
            }
        }
        let token = &self.text[start..self.at];
        if is_float {
            // Rust parses an overflowing literal to +-inf, like Python's json.
            token.parse::<f64>().ok().map(Py::Float)
        } else {
            let magnitude = token.trim_start_matches('-');
            if magnitude.len() > 1 && magnitude.starts_with('0') {
                return None;
            }
            Some(Py::Int(if magnitude == "0" {
                "0".to_owned()
            } else {
                token.to_owned()
            }))
        }
    }

    fn string(&mut self) -> Option<String> {
        self.at += 1; // opening quote
        let mut out = String::new();
        loop {
            let c = self.text[self.at..].chars().next()?;
            self.at += c.len_utf8();
            match c {
                '"' => return Some(out),
                '\\' => {
                    let escape = *self.bytes.get(self.at)?;
                    self.at += 1;
                    match escape {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let high = self.hex4()?;
                            let code = if (0xd800..0xdc00).contains(&high)
                                && self.text[self.at..].starts_with("\\u")
                            {
                                let save = self.at;
                                self.at += 2;
                                let low = self.hex4()?;
                                if (0xdc00..0xe000).contains(&low) {
                                    0x10000 + ((high - 0xd800) << 10) + (low - 0xdc00)
                                } else {
                                    self.at = save;
                                    high
                                }
                            } else {
                                high
                            };
                            // A lone surrogate cannot live in a Rust string.
                            out.push(char::from_u32(code)?);
                        }
                        _ => return None,
                    }
                }
                c if (c as u32) < 0x20 => return None,
                c => out.push(c),
            }
        }
    }

    fn hex4(&mut self) -> Option<u32> {
        let hex = self.text.get(self.at..self.at + 4)?;
        self.at += 4;
        u32::from_str_radix(hex, 16).ok()
    }
}

#[cfg(test)]
mod tests {
    use super::python_str_of_json;

    /// Golden values measured with CPython 3.13:
    /// `str(json.loads(text))`.
    #[test]
    fn matches_python_str_of_json_loads() {
        for (text, python) in [
            ("null", "None"),
            ("true", "True"),
            ("false", "False"),
            ("\"\"", ""),
            ("\"2012-03-01\"", "2012-03-01"),
            ("\"it's\"", "it's"),
            ("12", "12"),
            ("-0", "0"),
            ("12345678901234567890123", "12345678901234567890123"),
            ("1.0", "1.0"),
            ("1.5", "1.5"),
            ("-0.0", "-0.0"),
            ("0.1", "0.1"),
            ("1e5", "100000.0"),
            ("1e16", "1e+16"),
            ("1.5e-5", "1.5e-05"),
            ("0.0001", "0.0001"),
            ("123456789012345.6", "123456789012345.6"),
            ("1e400", "inf"),
            ("[]", "[]"),
            ("{}", "{}"),
            ("[1, \"a\", null, true, 2.5]", "[1, 'a', None, True, 2.5]"),
            (
                "{\"name\": \"Saga\", \"id\": 9, \"api\": null}",
                "{'name': 'Saga', 'id': 9, 'api': None}",
            ),
            ("{\"b\": 1, \"a\": 2, \"b\": 3}", "{'b': 3, 'a': 2}"),
            ("[\"it's\"]", "[\"it's\"]"),
            ("[\"say \\\"hi\\\" it's\"]", "['say \"hi\" it\\'s']"),
            ("[\"a\\nb\\\\c\\u0001\"]", "['a\\nb\\\\c\\x01']"),
            ("[\"caf\\u00e9 \\u00a0 \\u200b\"]", "['café \\xa0 \\u200b']"),
            ("[\"\\ud83d\\ude00\"]", "['😀']"),
            (" {\"x\" : [ {\"y\":[]} ] } ", "{'x': [{'y': []}]}"),
        ] {
            assert_eq!(python_str_of_json(text).as_deref(), Some(python), "{text}");
        }
    }

    #[test]
    fn rejects_text_that_is_not_one_json_value() {
        for text in ["", "nul", "01", "1.", "[1,]", "{\"a\" 1}", "1 2", "\"open"] {
            assert_eq!(python_str_of_json(text), None, "{text}");
        }
        let deep = "[".repeat(200) + &"]".repeat(200);
        assert_eq!(python_str_of_json(&deep), None);
    }
}
