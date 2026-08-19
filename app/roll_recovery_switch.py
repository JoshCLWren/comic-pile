target_thread_id = target_thread.id
    target_thread_title = target_thread.title
    target_issue_id = target_issue.id
    target_issue_number = target_issue.issue_number
    # Refresh the session to ensure we have the latest state before getting the die
    await db.refresh(locked_session)
    current_die = await get_current_die_for_session(locked_session, db)
    db.add(
        Event(
            type="roll",
            session_id=locked_session.id,
            selected_thread_id=target_thread_id,
            issue_id=target_issue_id,
            issue_number=target_issue_number,
            die=current_die,
            result=0,
            selection_method="dependency_recovery",
        )
    )