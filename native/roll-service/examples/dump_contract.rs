use std::fs;
fn main() {
    let generated = comicpile_roll_service::same_path_openapi::same_path_openapi()
        .to_pretty_json()
        .expect("serializable contract");
    fs::write("native/contracts/same-path-runtime.openapi.json", generated).expect("write");
}
