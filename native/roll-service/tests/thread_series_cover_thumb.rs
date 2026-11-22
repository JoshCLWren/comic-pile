#[tokio::test]
async fn series_cover_uses_thumb_url_fallback() {
    let ctx = setup("sc-thumb-fallback").await;
    let thread_id = seed_thread(&ctx, ctx.user_id, "Thumb Fallback", "active", 1).await;
    let issue = seed_issue(&ctx, thread_id, "1", 1, "unread").await;
    set_frontier(&ctx, thread_id, Some(issue)).await;

    let metadata = json!({
        "image": {
            "thumb_url": "https://cv.example/thumb.jpg"
        }
    });

    let identity: i32 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', 'thumb-id', $1, NOW(), NOW()) RETURNING id",
            &[&metadata],
        )
        .await
        .unwrap()
        .get(0);

    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
             created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
            &[&issue, &identity],
        )
        .await
        .unwrap();

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        thread_cover(&body, "Thumb Fallback"),
        Some("https://cv.example/thumb.jpg".to_owned())
    );
}
