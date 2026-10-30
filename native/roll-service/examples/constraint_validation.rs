//! Offline parity runner: sanitized scalar JSON on stdin, no database or auth.
use comicpile_roll_service::reading_constraints::{validate, Snapshot};
use serde_json::json;
use std::io::{self, BufRead};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    for line in io::stdin().lock().lines() {
        let snapshot: Snapshot = serde_json::from_str(&line?)?;
        let result = match validate(&snapshot) {
            Ok(order) => json!({"order": order}),
            Err(error) => serde_json::to_value(error)?,
        };
        println!("{}", serde_json::to_string(&result)?);
    }
    Ok(())
}
