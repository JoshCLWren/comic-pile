use comicpile_roll_service::config::Config;
fn main() {
    let c = Config::from_env().unwrap();
    println!("options={:?}", c.database.get_options());
    println!("dbname={:?}", c.database.get_dbname());
}
