use serde_json::Value;

/// Returns the issue candidate ID from a JSON value, or None if the value is null/empty.
///
/// This function is used to extract issue IDs from JSON payloads, handling the case
/// where the JSON value is null (representing an empty or missing issue).
pub fn issue_candidate(value: &Value) -> Option<i64> {
    // Handle null values (empty JSON objects) by returning None
    if value.is_null() {
        return None;
    }

    // Attempt to extract a numeric ID from the value.
    // This is a simplified example; actual implementation may vary.
    if let Some(num) = value.as_i64() {
        return Some(num);
    }

    // If the value is an object but has no valid ID field, return None.
    if let Some(obj) = value.as_object() {
        // Example: look for a field named "id"
        if let Some(id_val) = obj.get("id") {
            if let Some(id_num) = id_val.as_i64() {
                return Some(id_num);
            }
        }
    }

    None
}