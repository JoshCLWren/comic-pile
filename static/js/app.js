let currentDie = 6;

function calculateStaleness(lastActivityAt) {
    if (!lastActivityAt) return { days: null, badge: null };

    const now = new Date();
    const lastActivity = new Date(lastActivityAt);
    const diffMs = now - lastActivity;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    let badge;
    if (diffDays < 7) {
        badge = `<span class="inline-flex items-center px-2 py-1 bg-green-500 text-white rounded-full text-xs font-medium shadow-sm">✅ ${diffDays}d</span>`;
    } else if (diffDays <= 14) {
        badge = `<span class="inline-flex items-center px-2 py-1 bg-yellow-500 text-white rounded-full text-xs font-medium shadow-sm">⚠️ ${diffDays}d</span>`;
    } else {
        badge = `<span class="inline-flex items-center px-2 py-1 bg-red-500 text-white rounded-full text-xs font-medium shadow-sm">❌ ${diffDays}d</span>`;
    }

    return { days: diffDays, badge };
}

function loadQueue() {
    fetch('/threads/')
        .then(response => response.json())
        .then(threads => {
            const threadList = document.getElementById('thread-list');

                fetch('/sessions/current/')
                .then(response => response.json())
                .then(sessionData => {
                    currentDie = sessionData.current_die || 6;
                    document.getElementById('current-die').textContent = `d${currentDie}`;
                    document.getElementById('pool-size').textContent = currentDie;

                    threadList.innerHTML = threads.map((thread, index) => {
                        const position = index + 1;
                        const inRollPool = position <= currentDie;
                        const staleness = calculateStaleness(thread.last_activity_at || thread.created_at);

                        const bgClass = inRollPool ? 'bg-indigo-50 border-indigo-200' : 'bg-white border-gray-200';
                        const highlightClass = inRollPool ? 'border-l-4 border-l-indigo-500' : '';

                        return `
                            <div
                                class="thread-item ${bgClass} ${highlightClass} border rounded-lg p-3 sm:p-4 transition-all"
                                data-thread-id="${thread.id}"
                                data-position="${position}"
                            >
                                <div class="flex items-start space-x-3">
                                    <div class="cursor-move text-gray-400 hover:text-gray-600 touch-manipulation flex items-center justify-center min-h-12 min-w-12">
                                        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 sm:h-8 sm:w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8h16M4 16h16" />
                                        </svg>
                                    </div>
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-start justify-between">
                                            <div class="min-w-0">
                                                <h3 class="text-base sm:text-lg font-semibold text-gray-800 truncate">
                                                    ${thread.title}
                                                </h3>
                                                <div class="flex flex-wrap items-center gap-2 mt-1">
                                                    <span class="inline-flex items-center px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-xs font-medium">
                                                        ${thread.format}
                                                    </span>
                                                    <span class="text-xs sm:text-sm text-gray-600">
                                                        Issues: ${thread.issues_remaining}
                                                    </span>
                                                    ${inRollPool ? '<span class="inline-flex items-center px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded text-xs font-medium">In Roll Pool</span>' : ''}
                                                </div>
                                            </div>
                                            <div class="flex flex-col items-end gap-1 ml-2 flex-shrink-0">
                                                <span class="text-xs text-gray-400">#${position}</span>
                                                ${staleness.badge || ''}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join('');

                    initializeSortable();
                })
                .catch(error => {
                    console.error('Error loading session:', error);
                    document.getElementById('current-die').textContent = 'd6';
                    document.getElementById('pool-size').textContent = '6';
                });
        })
        .catch(error => {
            console.error('Error loading threads:', error);
            document.getElementById('thread-list').innerHTML = `
                <div class="text-center text-red-500 py-8">
                    Failed to load threads
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
        ghostClass: 'bg-indigo-100',
        chosenClass: 'ring-2 ring-indigo-500',
        dragClass: 'opacity-50',
        onEnd: function(evt) {
            const threadId = evt.item.dataset.threadId;
            const newPosition = evt.newIndex + 1;

            updateThreadPosition(threadId, newPosition);
        }
    });
}

function updateThreadPosition(threadId, newPosition) {
    const indicator = document.querySelector('#thread-list .htmx-indicator');
    if (indicator) {
        indicator.classList.remove('hidden');
    }

    htmx.ajax('PUT', `/threads/${threadId}/position/`, {
        values: { new_position: newPosition },
        swap: 'none',
        handler: function(elt, info) {
            console.log('Position updated');
            if (indicator) {
                indicator.classList.add('hidden');
            }
            loadQueue();
        },
        error: function(elt, info) {
            console.error('Error updating position:', info);
            if (indicator) {
                indicator.classList.add('hidden');
            }
            loadQueue();
        }
    });
}

document.addEventListener('DOMContentLoaded', loadQueue);

document.addEventListener('htmx:afterRequest', function(evt) {
    if (evt.detail.pathInfo.requestPath.startsWith('/threads/')) {
        loadQueue();
    }
});
