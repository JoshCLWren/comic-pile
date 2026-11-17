struct ActivityRawRow {
    issue_command_key: Option<bool>,
    issue_number: Option<String>,
}

fn coalescible_rate_pair(first: &ActivityRawRow, second: &ActivityRawRow) -> bool {
    let (issue_receipt, dice_receipt) = match (
        first.issue_command_key.is_some(),
        second.issue_command_key.is_some(),
    ) {
        (true, false) => (first, second),
        (false, true) => (second, first),
        _ => return false,
    };
    
    issue_receipt.issue_number = dice_receipt.issue_number;
    
    if timestamp_key(&dice_receipt) > timestamp_key(&issue_receipt) {
        // ...
    }
    
    true
}

fn timestamp_key(row: &ActivityRawRow) -> (i64, f64) {
    (0, 0.0)
}

fn main() {
    let first = ActivityRawRow { issue_command_key: Some(true), issue_number: Some("first".to_string()) };
    let second = ActivityRawRow { issue_command_key: Some(false), issue_number: Some("second".to_string()) };
    
    coalescible_rate_pair(&first, &second);
}
