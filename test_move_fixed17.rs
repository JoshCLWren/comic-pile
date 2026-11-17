struct ActivityRawRow {
    issue_command_key: Option<bool>,
    issue_number: Option<String>,
    dice_command_key: Option<String>,
}

fn coalescible_rate_pair(first: &ActivityRawRow, second: &ActivityRawRow) -> bool {
    // Move the values directly since we own them
    let first_owned = first.clone();
    let second_owned = second.clone();
    
    let (issue_receipt, dice_receipt) = match (
        first_owned.issue_command_key.is_some(),
        second_owned.issue_command_key.is_some(),
    ) {
        (true, false) => (first_owned, second_owned),
        (false, true) => (second_owned, first_owned),
        _ => return false,
    };
    
    // Now we can move the values since we own them
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
    let first = ActivityRawRow {
        issue_command_key: Some(true),
        issue_number: Some("first".to_string()),
        dice_command_key: Some("dice1".to_string()),
    };
    
    let second = ActivityRawRow {
        issue_command_key: Some(false),
        issue_number: Some("second".to_string()),
        dice_command_key: Some("dice2".to_string()),
    };
    
    coalescible_rate_pair(&first, &second);
}
