let editingThreadId = null;
let positionThreadId = null;

function calculateStaleness(lastActivityAt) {
    if (!lastActivityAt) return { days: null, badge: null };

    const now = new Date();
    const lastActivity = new Date(lastActivityAt);
    const diffMs = now - lastActivity;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    let badge;
    if (diffDays < 7) {
        badge = `<span class="inline-flex items-center px-2 py-1 bg-green-500/20 text-green-400 rounded-full text-[10px] font-bold uppercase tracking-wider">✅ ${diffDays}d</span>`;
    } else if (diffDays <= 14) {
        badge = `<span class="inline-flex items-center px-2 py-1 bg-yellow-500/20 text-yellow-400 rounded-full text-[10px] font-bold uppercase tracking-wider">⚠️ ${diffDays}d</span>`;
    } else {
        badge = `<span class="inline-flex items-center px-2 py-1 bg-red-500/20 text-red-400 rounded-full text-[10px] font-bold uppercase tracking-wider">❌ ${diffDays}d</span>`;
    }

    return { days: diffDays, badge };
}

function loadQueue() {
    fetch('/threads/')
        .then(response => response.json())
        .then(threads => {
            const threadList = document.getElementById('thread-list');

            if (threads.length === 0) {
                threadList.innerHTML = `
                    <div class="glass-card p-8 text-center border-white/5">
                        <p class="text-slate-500 font-medium uppercase tracking-widest text-xs">No comics in queue</p>
                        <p class="text-slate-600 text-sm mt-2">Add your first comic to get started</p>
                    </div>
                `;
                return;
            }

            threadList.innerHTML = threads.map((thread, index) => {
                const position = index + 1;
                const staleness = calculateStaleness(thread.last_activity_at || thread.created_at);

                return `
                    <div class="glass-card border-white/10 p-4 rounded-xl transition-all hover:border-white/20"
                         data-thread-id="${thread.id}"
                         data-position="${position}">
                        <div class="flex items-start gap-3">
                            <div class="cursor-move text-slate-400 hover:text-slate-200 touch-manipulation flex items-center justify-center pt-1">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8h16M4 16h16" />
                                </svg>
                            </div>
                            <div class="flex-1 min-w-0">
                                <div class="flex items-start justify-between gap-2">
                                    <div class="min-w-0 flex-1">
                                        <h3 class="text-base font-bold text-slate-100 truncate">${thread.title}</h3>
                                        <div class="flex items-center gap-2 mt-1.5 flex-wrap">
                                            <span class="px-2 py-0.5 bg-white/10 text-slate-300 rounded text-[10px] font-bold uppercase tracking-wider">
                                                ${thread.format}
                                            </span>
                                            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                                                ${thread.issues_remaining} issues
                                            </span>
                                        </div>
                                    </div>
                                    <div class="flex flex-col items-end gap-1.5 flex-shrink-0">
                                        <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">#${position}</span>
                                        ${staleness.badge || ''}
                                    </div>
                                </div>
                                <div class="flex items-center gap-2 mt-3 pt-3 border-t border-white/5">
                                    <button onclick="moveThread(${thread.id}, 'up')"
                                        class="px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:bg-white/10 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-all active:scale-95">
                                        ↑ Up
                                    </button>
                                    <button onclick="moveThread(${thread.id}, 'down')"
                                        class="px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:bg-white/10 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-all active:scale-95">
                                        ↓ Down
                                    </button>
                                    <button onclick="openPositionModal(${thread.id}, ${position}, ${threads.length})"
                                        class="px-3 py-1.5 bg-purple-500/10 border border-purple-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider text-purple-400 hover:bg-purple-500/20 transition-all active:scale-95">
                                        # Jump
                                    </button>
                                    <button onclick="openEditModal(${thread.id})"
                                        class="px-3 py-1.5 bg-teal-500/10 border border-teal-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider text-teal-400 hover:bg-teal-500/20 transition-all active:scale-95">
                                        Edit
                                    </button>
                                    <button onclick="deleteThread(${thread.id})"
                                        class="px-3 py-1.5 bg-red-500/10 border border-red-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider text-red-400 hover:bg-red-500/20 transition-all active:scale-95 ml-auto">
                                        Remove
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            initializeSortable();
        })
        .catch(error => {
            console.error('Error loading threads:', error);
            document.getElementById('thread-list').innerHTML = `
                <div class="glass-card p-8 text-center border-red-500/20">
                    <p class="text-red-400 font-medium uppercase tracking-widest text-xs">Failed to load threads</p>
                </div>
            `;
        });
}

function initializeSortable() {
    const threadList = document.getElementById('thread-list');

    if (window.sortableInstance) {
        window.sortableInstance.destroy();
    }

    window.sortableInstance = new Sortable(threadList, {
        animation: 150,
        handle: '.cursor-move',
        ghostClass: 'bg-white/10',
        chosenClass: 'ring-2 ring-teal-500',
        dragClass: 'opacity-50',
        onEnd: function(evt) {
            const threadId = evt.item.dataset.threadId;
            const newPosition = evt.newIndex + 1;

            updateThreadPosition(threadId, newPosition);
        }
    });
}

function updateThreadPosition(threadId, newPosition) {
    fetch(`/threads/${threadId}/position/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_position: newPosition })
    })
    .then(response => response.json())
    .then(() => loadQueue())
    .catch(error => {
        console.error('Error updating position:', error);
        loadQueue();
    });
}

function openPositionModal(threadId, currentPosition, maxPosition) {
    positionThreadId = threadId;
    document.getElementById('position-thread-id').value = threadId;
    document.getElementById('current-position').textContent = currentPosition;
    document.getElementById('new-position').value = '';
    document.getElementById('new-position').max = maxPosition;
    document.getElementById('new-position').min = 1;
    document.getElementById('position-modal').classList.remove('hidden');
    document.getElementById('new-position').focus();
}

function closePositionModal() {
    document.getElementById('position-modal').classList.add('hidden');
    document.getElementById('position-form').reset();
    positionThreadId = null;
}

function moveToPosition(e) {
    e.preventDefault();
    const newPosition = parseInt(document.getElementById('new-position').value);
    if (newPosition && newPosition >= 1 && positionThreadId) {
        updateThreadPosition(positionThreadId, newPosition);
        closePositionModal();
    }
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        const positionModal = document.getElementById('position-modal');
        const editModal = document.getElementById('edit-thread-modal');
        if (positionModal && !positionModal.classList.contains('hidden')) {
            closePositionModal();
        } else if (editModal && !editModal.classList.contains('hidden')) {
            closeEditModal();
        }
    }
});

function moveThread(threadId, direction) {
    const threadEl = document.querySelector(`[data-thread-id="${threadId}"]`);
    if (!threadEl) return;

    const currentPosition = parseInt(threadEl.dataset.position);
    let newPosition;

    if (direction === 'up') {
        newPosition = currentPosition - 1;
    } else if (direction === 'down') {
        newPosition = currentPosition + 1;
    }

    if (newPosition && newPosition > 0) {
        updateThreadPosition(threadId, newPosition);
    }
}

function openEditModal(threadId) {
    fetch(`/threads/${threadId}`)
        .then(response => response.json())
        .then(thread => {
            document.getElementById('edit-thread-id').value = thread.id;
            document.getElementById('edit-title').value = thread.title;
            document.getElementById('edit-format').value = thread.format;
            document.getElementById('edit-issues').value = thread.issues_remaining;
            editingThreadId = threadId;
            document.getElementById('edit-thread-modal').classList.remove('hidden');
        })
        .catch(error => {
            console.error('Error loading thread:', error);
        });
}

function closeEditModal() {
    document.getElementById('edit-thread-modal').classList.add('hidden');
    document.getElementById('edit-thread-form').reset();
    editingThreadId = null;
}

async function deleteThread(threadId) {
    try {
        const res = await fetch('/sessions/current/');
        const session = await res.json();

        if (!session.has_restore_point) {
            const confirmed = confirm('⚠️ No restore point available!\n\nYou are about to delete this thread permanently. This action cannot be undone. Continue anyway?');
            if (!confirmed) {
                return;
            }
        }
    } catch (e) {
        console.error('Failed to check restore point:', e);
    }

    if (!confirm('Are you sure you want to remove this comic from the queue?')) {
        return;
    }

    fetch(`/threads/${threadId}`, { method: 'DELETE' })
        .then(() => loadQueue())
        .catch(error => {
            console.error('Error deleting thread:', error);
            loadQueue();
        });
}

document.addEventListener('DOMContentLoaded', function() {
    loadQueue();

    document.getElementById('edit-thread-form').addEventListener('submit', function(e) {
        e.preventDefault();

        const threadId = editingThreadId;
        const title = document.getElementById('edit-title').value;
        const format = document.getElementById('edit-format').value;
        const issuesRemaining = parseInt(document.getElementById('edit-issues').value);

        fetch(`/threads/${threadId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title,
                format: format,
                issues_remaining: issuesRemaining
            })
        })
        .then(response => response.json())
        .then(() => {
            closeEditModal();
            loadQueue();
        })
        .catch(error => {
            console.error('Error updating thread:', error);
        });
    });

    document.getElementById('position-form').addEventListener('submit', moveToPosition);
});

document.addEventListener('htmx:afterRequest', function(evt) {
    if (evt.detail.pathInfo.requestPath.startsWith('/threads/')) {
        loadQueue();
    }
});
