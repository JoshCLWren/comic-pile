use tokio_postgres::NoTls;
#[tokio::main]
async fn main() {
    let url = std::env::var("RUST_ROLL_TEST_DATABASE_URL").unwrap();
    println!("url={url}");
    let (client, conn) = tokio_postgres::connect(&url, NoTls).await.expect("connect");
    tokio::spawn(async move { let _ = conn.await; });
    let row = client.query_one("SELECT 1", &[]).await.expect("query");
    println!("result={}", row.get::<_, i32>(0));
}
