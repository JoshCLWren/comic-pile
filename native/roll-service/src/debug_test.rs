#[tokio::test]
async fn debug_conn() {
    let url = std::env::var("RUST_ROLL_TEST_DATABASE_URL").unwrap();
    let schema = "debugschema";
    let admin_url = url.clone();
    let (admin, connection) = tokio_postgres::connect(&admin_url, tokio_postgres::NoTls).await.unwrap();
    tokio::spawn(async move { let _ = connection.await; });
    admin.batch_execute(&format!("DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema}; CREATE TABLE {schema}.users (id int primary key); INSERT INTO {schema}.users VALUES (1);")).await.unwrap();
    let u = format!("{url}?options=-csearch_path%3D{schema}");
    println!("URL={u}");
    let config = crate::config::Config::from_lookup(|key| match key {
        "RUST_ROLL_DATABASE_URL" => Some(u.clone()),
        "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
        "RUST_ROLL_POOL_SIZE" => Some("1".into()),
        _ => None,
    }).unwrap();
    let state = crate::AppState::new(config).unwrap();
    let conn = crate::db::checkout(&state).await.unwrap();
    let row = conn.query_one("SELECT count(*) FROM users", &[]).await.unwrap();
    let c: i64 = row.get(0);
    println!("COUNT={c}");
}
