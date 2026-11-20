// Existing test content...
// Add new concurrency test for series:import

#[tokio::test]
async fn import_series_concurrent_test() {
    use tokio::spawn;
    use tokio::join;

    // Create two concurrent import tasks
    let task1 = spawn(async {
        comicvine_v2::import_series("volume_1", "series_a", "user1").await
    });

    let task2 = spawn(async {
        comicvine_v2::import_series("volume_2", "series_b", "user2").await
    });

    // Wait for both tasks to complete
    let (result1, result2) = join!(task1, task2);

    // Both should succeed without errors
    assert!(result1.is_ok());
    assert!(result2.is_ok());
}