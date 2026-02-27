/**
 * Graph layout algorithm for dependency flowchart visualization.
 *
 * Uses topological sorting with layer assignment (Sugiyama-style)
 * to position nodes in a directed acyclic graph. No external dependencies.
 */

import type { Thread, Dependency, GraphLayout, FlowchartNode, FlowchartEdge } from '../types'

/** Width of each node rectangle in the flowchart */
const NODE_WIDTH = 160
/** Height of each node rectangle in the flowchart */
const NODE_HEIGHT = 56
/** Horizontal gap between nodes in the same layer */
const HORIZONTAL_GAP = 60
/** Vertical gap between layers */
const VERTICAL_GAP = 100
/** Padding around the entire layout */
const PADDING = 40

/**
 * Build an adjacency list from dependencies.
 *
 * @param threadIds - Set of valid thread IDs to include
 * @param dependencies - Array of dependency records
 * @returns Map from source thread ID to array of target thread IDs
 */
function buildAdjacencyList(
    threadIds: Set<number>,
    dependencies: Dependency[],
): Map<number, number[]> {
    const adjacency = new Map<number, number[]>()
    for (const id of threadIds) {
        adjacency.set(id, [])
    }
    for (const dep of dependencies) {
        if (threadIds.has(dep.source_thread_id) && threadIds.has(dep.target_thread_id)) {
            adjacency.get(dep.source_thread_id)!.push(dep.target_thread_id)
        }
    }
    return adjacency
}

/**
 * Compute in-degree counts for each node.
 *
 * @param threadIds - Set of valid thread IDs
 * @param adjacency - Adjacency list
 * @returns Map from thread ID to number of incoming edges
 */
function computeInDegrees(
    threadIds: Set<number>,
    adjacency: Map<number, number[]>,
): Map<number, number> {
    const inDegree = new Map<number, number>()
    for (const id of threadIds) {
        inDegree.set(id, 0)
    }
    for (const targets of adjacency.values()) {
        for (const target of targets) {
            inDegree.set(target, (inDegree.get(target) ?? 0) + 1)
        }
    }
    return inDegree
}

/**
 * Assign each node to a layer using topological sort (Kahn's algorithm).
 * Nodes with no incoming edges are in layer 0, their dependents in layer 1, etc.
 *
 * @param threadIds - Set of valid thread IDs
 * @param adjacency - Adjacency list
 * @returns Map from thread ID to layer index
 */
function assignLayers(
    threadIds: Set<number>,
    adjacency: Map<number, number[]>,
): Map<number, number> {
    const inDegree = computeInDegrees(threadIds, adjacency)
    const layers = new Map<number, number>()

    const queue: number[] = []
    for (const [id, degree] of inDegree) {
        if (degree === 0) {
            queue.push(id)
            layers.set(id, 0)
        }
    }

    let head = 0
    while (head < queue.length) {
        const current = queue[head++]
        const currentLayer = layers.get(current) ?? 0
        for (const target of adjacency.get(current) ?? []) {
            const newDegree = (inDegree.get(target) ?? 1) - 1
            inDegree.set(target, newDegree)
            const existingLayer = layers.get(target)
            const candidateLayer = currentLayer + 1
            if (existingLayer === undefined || candidateLayer > existingLayer) {
                layers.set(target, candidateLayer)
            }
            if (newDegree === 0) {
                queue.push(target)
            }
        }
    }

    // Handle any remaining nodes (cycles — shouldn't happen with circular detection, but be safe)
    for (const id of threadIds) {
        if (!layers.has(id)) {
            layers.set(id, 0)
        }
    }

    return layers
}

/**
 * Group thread IDs by their assigned layer.
 *
 * @param layers - Map from thread ID to layer index
 * @returns Array of arrays, where index is the layer and values are thread IDs
 */
function groupByLayer(layers: Map<number, number>): number[][] {
    const maxLayer = Math.max(0, ...layers.values())
    const groups: number[][] = Array.from({ length: maxLayer + 1 }, () => [])
    for (const [id, layer] of layers) {
        groups[layer].push(id)
    }
    // Sort within each layer for deterministic output
    for (const group of groups) {
        group.sort((a, b) => a - b)
    }
    return groups
}

/**
 * Compute an SVG cubic Bézier path between two node centers.
 *
 * @param sourceX - Source node center X
 * @param sourceY - Source node bottom Y
 * @param targetX - Target node center X
 * @param targetY - Target node top Y
 * @returns SVG path data string
 */
function computeEdgePath(
    sourceX: number,
    sourceY: number,
    targetX: number,
    targetY: number,
): string {
    const midY = (sourceY + targetY) / 2
    return `M ${sourceX} ${sourceY} C ${sourceX} ${midY}, ${targetX} ${midY}, ${targetX} ${targetY}`
}

/**
 * Lay out a dependency graph for SVG rendering.
 *
 * Threads are arranged in layers based on their dependency order.
 * Layer 0 contains threads with no prerequisites (sources),
 * and each subsequent layer contains threads that depend on the previous layer.
 *
 * @param threads - Array of threads to include in the graph
 * @param dependencies - Array of dependency relationships between threads
 * @param blockedIds - Set of thread IDs that are currently blocked
 * @returns Graph layout with positioned nodes and edge paths
 */
export function layoutGraph(
    threads: Thread[],
    dependencies: Dependency[],
    blockedIds: Set<number>,
): GraphLayout {
    if (threads.length === 0) {
        return { nodes: [], edges: [], width: 0, height: 0 }
    }

    const threadMap = new Map(threads.map((t) => [t.id, t]))
    const threadIds = new Set(threads.map((t) => t.id))
    const adjacency = buildAdjacencyList(threadIds, dependencies)
    const layers = assignLayers(threadIds, adjacency)
    const layerGroups = groupByLayer(layers)

    // Position nodes
    const nodes: FlowchartNode[] = []
    for (let layerIndex = 0; layerIndex < layerGroups.length; layerIndex++) {
        const group = layerGroups[layerIndex]
        const layerWidth = group.length * NODE_WIDTH + (group.length - 1) * HORIZONTAL_GAP
        const startX = PADDING + (group.length > 1 ? 0 : 0)

        for (let nodeIndex = 0; nodeIndex < group.length; nodeIndex++) {
            const threadId = group[nodeIndex]
            const thread = threadMap.get(threadId)
            if (!thread) continue

            // Center the layer horizontally
            const totalMaxWidth = Math.max(
                ...layerGroups.map((g) => g.length * NODE_WIDTH + (g.length - 1) * HORIZONTAL_GAP),
            )
            const offsetX = (totalMaxWidth - layerWidth) / 2

            nodes.push({
                id: threadId,
                title: thread.title,
                x: PADDING + offsetX + nodeIndex * (NODE_WIDTH + HORIZONTAL_GAP),
                y: PADDING + layerIndex * (NODE_HEIGHT + VERTICAL_GAP),
                isBlocked: blockedIds.has(threadId),
            })
        }
    }

    // Build a position lookup for edge computation
    const nodePositions = new Map(nodes.map((n) => [n.id, n]))

    // Compute edges
    const edges: FlowchartEdge[] = []
    for (const dep of dependencies) {
        const source = nodePositions.get(dep.source_thread_id)
        const target = nodePositions.get(dep.target_thread_id)
        if (!source || !target) continue

        const sourceCenterX = source.x + NODE_WIDTH / 2
        const sourceBottomY = source.y + NODE_HEIGHT
        const targetCenterX = target.x + NODE_WIDTH / 2
        const targetTopY = target.y

        edges.push({
            id: `edge-${dep.id}`,
            sourceId: dep.source_thread_id,
            targetId: dep.target_thread_id,
            path: computeEdgePath(sourceCenterX, sourceBottomY, targetCenterX, targetTopY),
            isBlocking: blockedIds.has(dep.target_thread_id),
        })
    }

    // Compute total dimensions
    const maxX = Math.max(0, ...nodes.map((n) => n.x + NODE_WIDTH)) + PADDING
    const maxY = Math.max(0, ...nodes.map((n) => n.y + NODE_HEIGHT)) + PADDING

    return { nodes, edges, width: maxX, height: maxY }
}

export { NODE_WIDTH, NODE_HEIGHT }
