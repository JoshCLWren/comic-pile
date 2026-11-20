#[test]
fn issue_candidate_handles_null_value() {
    let null_value = json!({});
    let candidate = issue_candidate(&null_value);
    assert_eq!(candidate, None);
}