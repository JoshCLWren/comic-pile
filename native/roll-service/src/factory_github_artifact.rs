//! Reads the single JSON file from a Rotisserie operator artifact archive.
//!
//! `actions/upload-artifact` writes streaming archives whose local headers can
//! carry zero sizes, so sizes and offsets come from the central directory.
#![forbid(unsafe_code)]

use std::fmt;

const LOCAL_HEADER: u32 = 0x0403_4b50;
const CENTRAL_HEADER: u32 = 0x0201_4b50;
const END_OF_DIRECTORY: u32 = 0x0605_4b50;
const END_OF_DIRECTORY_LEN: usize = 22;
const MAX_COMMENT_LEN: usize = u16::MAX as usize;

#[derive(Debug, PartialEq, Eq)]
pub enum ArtifactError {
    Malformed,
    TooLarge,
    Unsupported,
    MultipleFiles,
}

impl fmt::Display for ArtifactError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            ArtifactError::Malformed => "Factory result archive is malformed",
            ArtifactError::TooLarge => "Factory result is larger than 1 MB",
            ArtifactError::Unsupported => "Factory result archive format is unsupported",
            ArtifactError::MultipleFiles => "Factory result archive holds more than one file",
        })
    }
}

fn u16_at(bytes: &[u8], offset: usize) -> Result<u16, ArtifactError> {
    bytes
        .get(offset..offset + 2)
        .map(|slice| u16::from_le_bytes([slice[0], slice[1]]))
        .ok_or(ArtifactError::Malformed)
}

fn u32_at(bytes: &[u8], offset: usize) -> Result<u32, ArtifactError> {
    bytes
        .get(offset..offset + 4)
        .map(|slice| u32::from_le_bytes([slice[0], slice[1], slice[2], slice[3]]))
        .ok_or(ArtifactError::Malformed)
}

fn end_of_directory(bytes: &[u8]) -> Result<usize, ArtifactError> {
    if bytes.len() < END_OF_DIRECTORY_LEN {
        return Err(ArtifactError::Malformed);
    }
    let last = bytes.len() - END_OF_DIRECTORY_LEN;
    let first = last.saturating_sub(MAX_COMMENT_LEN);
    (first..=last)
        .rev()
        .find(|&offset| u32_at(bytes, offset) == Ok(END_OF_DIRECTORY))
        .ok_or(ArtifactError::Malformed)
}

struct Entry {
    method: u16,
    compressed: usize,
    uncompressed: usize,
    local_offset: usize,
}

/// Returns the one file in `archive`, or `None` when it holds no file.
/// `limit` caps both the stored and the inflated size.
pub fn single_file(archive: &[u8], limit: usize) -> Result<Option<Vec<u8>>, ArtifactError> {
    let end = end_of_directory(archive)?;
    let entries = u16_at(archive, end + 10)?;
    let directory_offset = u32_at(archive, end + 16)?;
    if entries == u16::MAX || directory_offset == u32::MAX {
        return Err(ArtifactError::Unsupported);
    }
    let mut cursor = directory_offset as usize;
    let mut found: Option<Entry> = None;
    for _ in 0..entries {
        if u32_at(archive, cursor)? != CENTRAL_HEADER {
            return Err(ArtifactError::Malformed);
        }
        let flags = u16_at(archive, cursor + 8)?;
        let method = u16_at(archive, cursor + 10)?;
        let compressed = u32_at(archive, cursor + 20)?;
        let uncompressed = u32_at(archive, cursor + 24)?;
        let name_len = u16_at(archive, cursor + 28)? as usize;
        let extra_len = u16_at(archive, cursor + 30)? as usize;
        let comment_len = u16_at(archive, cursor + 32)? as usize;
        let local_offset = u32_at(archive, cursor + 42)?;
        let name = archive
            .get(cursor + 46..cursor + 46 + name_len)
            .ok_or(ArtifactError::Malformed)?;
        cursor += 46 + name_len + extra_len + comment_len;
        if name.ends_with(b"/") {
            continue;
        }
        if flags & 1 != 0 || [compressed, uncompressed, local_offset].contains(&u32::MAX) {
            return Err(ArtifactError::Unsupported);
        }
        if found.is_some() {
            return Err(ArtifactError::MultipleFiles);
        }
        found = Some(Entry {
            method,
            compressed: compressed as usize,
            uncompressed: uncompressed as usize,
            local_offset: local_offset as usize,
        });
    }
    let Some(entry) = found else {
        return Ok(None);
    };
    if entry.compressed > limit || entry.uncompressed > limit {
        return Err(ArtifactError::TooLarge);
    }
    if u32_at(archive, entry.local_offset)? != LOCAL_HEADER {
        return Err(ArtifactError::Malformed);
    }
    let local_name = u16_at(archive, entry.local_offset + 26)? as usize;
    let local_extra = u16_at(archive, entry.local_offset + 28)? as usize;
    let start = entry.local_offset + 30 + local_name + local_extra;
    let data = archive
        .get(start..start + entry.compressed)
        .ok_or(ArtifactError::Malformed)?;
    let content = match entry.method {
        0 => data.to_vec(),
        8 => miniz_oxide::inflate::decompress_to_vec_with_limit(data, limit).map_err(|error| {
            match error.status {
                miniz_oxide::inflate::TINFLStatus::HasMoreOutput => ArtifactError::TooLarge,
                _ => ArtifactError::Malformed,
            }
        })?,
        _ => return Err(ArtifactError::Unsupported),
    };
    if content.len() != entry.uncompressed {
        return Err(ArtifactError::Malformed);
    }
    Ok(Some(content))
}

#[cfg(test)]
mod tests {
    use super::{single_file, ArtifactError};

    fn archive(files: &[(&str, &[u8])], deflate: bool, descriptor: bool) -> Vec<u8> {
        let mut out = Vec::new();
        let mut central = Vec::new();
        for (name, content) in files {
            let data = if deflate {
                miniz_oxide::deflate::compress_to_vec(content, 6)
            } else {
                content.to_vec()
            };
            let method: u16 = if deflate { 8 } else { 0 };
            let flags: u16 = if descriptor { 8 } else { 0 };
            let offset = out.len() as u32;
            let (local_compressed, local_size) = if descriptor {
                (0, 0)
            } else {
                (data.len() as u32, content.len() as u32)
            };
            out.extend_from_slice(&0x0403_4b50u32.to_le_bytes());
            out.extend_from_slice(&20u16.to_le_bytes());
            out.extend_from_slice(&flags.to_le_bytes());
            out.extend_from_slice(&method.to_le_bytes());
            out.extend_from_slice(&[0; 8]);
            out.extend_from_slice(&local_compressed.to_le_bytes());
            out.extend_from_slice(&local_size.to_le_bytes());
            out.extend_from_slice(&(name.len() as u16).to_le_bytes());
            out.extend_from_slice(&0u16.to_le_bytes());
            out.extend_from_slice(name.as_bytes());
            out.extend_from_slice(&data);
            if descriptor {
                out.extend_from_slice(&0x0807_4b50u32.to_le_bytes());
                out.extend_from_slice(&[0; 4]);
                out.extend_from_slice(&(data.len() as u32).to_le_bytes());
                out.extend_from_slice(&(content.len() as u32).to_le_bytes());
            }
            central.extend_from_slice(&0x0201_4b50u32.to_le_bytes());
            central.extend_from_slice(&20u16.to_le_bytes());
            central.extend_from_slice(&20u16.to_le_bytes());
            central.extend_from_slice(&flags.to_le_bytes());
            central.extend_from_slice(&method.to_le_bytes());
            central.extend_from_slice(&[0; 8]);
            central.extend_from_slice(&(data.len() as u32).to_le_bytes());
            central.extend_from_slice(&(content.len() as u32).to_le_bytes());
            central.extend_from_slice(&(name.len() as u16).to_le_bytes());
            central.extend_from_slice(&[0; 12]);
            central.extend_from_slice(&offset.to_le_bytes());
            central.extend_from_slice(name.as_bytes());
        }
        let directory_offset = out.len() as u32;
        out.extend_from_slice(&central);
        out.extend_from_slice(&0x0605_4b50u32.to_le_bytes());
        out.extend_from_slice(&[0; 4]);
        out.extend_from_slice(&(files.len() as u16).to_le_bytes());
        out.extend_from_slice(&(files.len() as u16).to_le_bytes());
        out.extend_from_slice(&(central.len() as u32).to_le_bytes());
        out.extend_from_slice(&directory_offset.to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes());
        out
    }

    #[test]
    fn reads_streamed_deflate_and_stored_single_files() {
        let json = br#"{"request_id":"r-1","exit_code":0}"#;
        for (deflate, descriptor) in [(true, true), (true, false), (false, false)] {
            let zip = archive(&[("rotisserie-result.json", json)], deflate, descriptor);
            assert_eq!(single_file(&zip, 1024).unwrap().unwrap(), json.to_vec());
        }
    }

    #[test]
    fn refuses_oversized_multiple_and_malformed_archives() {
        let big = vec![b' '; 2048];
        let zip = archive(&[("result.json", &big)], true, true);
        assert_eq!(single_file(&zip, 1024), Err(ArtifactError::TooLarge));
        let two = archive(&[("a.json", b"{}"), ("b.json", b"{}")], true, false);
        assert_eq!(single_file(&two, 1024), Err(ArtifactError::MultipleFiles));
        assert_eq!(single_file(&archive(&[], true, false), 1024), Ok(None));
        assert_eq!(
            single_file(b"not a zip", 1024),
            Err(ArtifactError::Malformed)
        );
    }

    #[test]
    fn inflate_limit_does_not_trust_declared_sizes() {
        let big = vec![b' '; 4096];
        let mut zip = archive(&[("result.json", &big)], true, false);
        let directory = zip.len() - 22 - 46 - "result.json".len();
        zip[directory + 24..directory + 28].copy_from_slice(&10u32.to_le_bytes());
        assert_eq!(single_file(&zip, 1024), Err(ArtifactError::TooLarge));
    }
}
