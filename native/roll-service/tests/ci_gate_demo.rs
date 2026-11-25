//! Temporary deliberately-failing test for the #5678 blocked-then-green gate demo.
//! It must fail only in `cargo test`; the UI audit builds binaries, not tests.

#[test]
fn intentional_red_evidence_for_ci_gate_demo() {
    panic!("intentional red Native Rust Roll evidence for #5678 / #5785");
}
