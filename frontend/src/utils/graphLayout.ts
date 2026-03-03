/**
 * Graph layout algorithm for dependency flowchart visualization.
 *
 * Uses topological sorting with layer assignment (Sugiyama-style)
 * to position nodes in a directed acyclic graph. No external dependencies.
 */

import type { Thread, FlowchartDependency, GraphLayout, FlowchartNode, FlowchartEdge } from '../types'

/** Width of each thread node rectangle in the flowchart */
const NODE_WIDTH = 160
/** Height of each thread node rectangle in the flowchart */
const NODE_HEIGHT = 56
/** Width of each issue node rectangle */
const ISSUE_NODE_WIDTH = 130
/** Height of each issue node rectangle */
const ISSUE_NODE_HEIGHT = 40
/** Horizontal gap between nodes in the same layer */
const HORIZONTAL_GAP = 60
/** Vertical gap between layers */
const VERTICAL_GAP = 100
/** Padding around the entire layout */
const PADDING = 40

/** Return the width/height for a given node based on whether it's an issue node */
function nodeDimensions(node: FlowchartNode): { w: number; h: number } {
    return node.isIssueNode
        ? { w: ISSUE_NODE_WIDTH, h: ISSUE_NODE_HEIGHT }
        : { w: NODE_WIDTH, h: NODE_HEIGHT }
}

/**
 * Build an adjacency list from dependencies.
 */
function buildAdjacencyList(
    nodeIds: Set<number>,
    dependencies: FlowchartDependency[],
): Map<number, number[]> {
    const adjacency = new Map<number, number[]>()
    for (const id of nodeIds) {
        adjacency.set(id, [])
    }
    for (const dep of dependencies) {
        if (nodeIds.has(dep.source_thread_id) && nodeIds.has(dep.target_thread_id)) {
            adjacency.get(dep.source_thread_id)!.push(dep.target_thread_id)
        }
    }
    return adjacency
}

/**
 * Compute in-degree counts for each node.
 */
function computeInDegrees(
    nodeIds: Set<number>,
    adjacency: Map<number, number[]>,
): Map<number, number> {
    const inDegree = new Map<number, number>()
    for (const id of nodeIds) {
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
 */
function assignLayers(
    nodeIds: Set<number>,
    adjacency: Map<number, number[]>,
): Map<number, number> {
    const inDegree = computeInDegrees(nodeIds, adjacency)
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

    // Handle any remaining nodes (cycles — shouldn't happen, but be safe)
    for (const id of nodeIds) {
        if (!layers.has(id)) {
            layers.set(id, 0)
        }
    }

    return layers
}

/**
 * Group node IDs by their assigned layer.
 */
function groupByLayer(layers: Map<number, number>): number[][] {
    const maxLayer = Math.max(0, ...layers.values())
    const groups: number[][] = Array.from({ length: maxLayer + 1 }, () => [])
    for (const [id, layer] of layers) {
        groups[layer].push(id)
    }
    for (const group of groups) {
        group.sort((a, b) => a - b)
    }
    return groups
}

/**
 * Compute an SVG cubic Bézier path between two node attachment points.
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
 * @param threads - Array of threads to include as thread-level nodes
 * @param dependencies - Array of dependency relationships
 * @param blockedIds - Set of thread IDs that are currently blocked
 * @param issueNodes - Pre-built issue-level nodes to include in the layout
 * @returns Graph layout with positioned nodes and edge paths
 */
export function layoutGraph(
    threads: Thread[],
    dependencies: FlowchartDependency[],
    blockedIds: Set<number>,
    issueNodes: FlowchartNode[] = [],
): GraphLayout {
    if (threads.length === 0 && issueNodes.length === 0) {
        return { nodes: [], edges: [], width: 0, height: 0 }
    }

    // Build a map of all nodes: thread nodes + pre-built issue nodes
    const allPreNodes = new Map<number, FlowchartNode>()
    const threadMap = new Map(threads.map((t) => [t.id, t]))

    // Thread nodes (will be positioned below)
    for (const t of threads) {
        allPreNodes.set(t.id, {
            id: t.id,
            title: t.title,
            x: 0, y: 0,
            isBlocked: blockedIds.has(t.id),
        })
    }

    // Issue nodes (pre-built, will be positioned below)
    for (const issueNode of issueNodes) {
        allPreNodes.set(issueNode.id, issueNode)
    }

    const allNodeIds = new Set(allPreNodes.keys())
    const adjacency = buildAdjacencyList(allNodeIds, dependencies)
    const layers = assignLayers(allNodeIds, adjacency)
    const layerGroups = groupByLayer(layers)

    // Position nodes — use max node width per layer for centering
    const nodes: FlowchartNode[] = []

    // Compute the max layer width for centering
    const layerWidths = layerGroups.map((group) => {
        let width = 0
        for (let i = 0; i < group.length; i++) {
            const preNode = allPreNodes.get(group[i])
            const nodeW = preNode?.isIssueNode ? ISSUE_NODE_WIDTH : NODE_WIDTH
            width += nodeW
            if (i < group.length - 1) width += HORIZONTAL_GAP
        }
        return width
    })
    const totalMaxWidth = Math.max(0, ...layerWidths)

    for (let layerIndex = 0; layerIndex < layerGroups.length; layerIndex++) {
        const group = layerGroups[layerIndex]
        const layerWidth = layerWidths[layerIndex]
        const offsetX = (totalMaxWidth - layerWidth) / 2

        let cursor = 0
        for (let nodeIndex = 0; nodeIndex < group.length; nodeIndex++) {
            const nodeId = group[nodeIndex]
            const preNode = allPreNodes.get(nodeId)
            if (!preNode) continue

            const { w: nodeW, h: nodeH } = nodeDimensions(preNode)
            const thread = threadMap.get(nodeId)

            nodes.push({
                id: nodeId,
                title: preNode.title ?? thread?.title ?? `Node ${nodeId}`,
                x: PADDING + offsetX + cursor,
                y: PADDING + layerIndex * (NODE_HEIGHT + VERTICAL_GAP) + (NODE_HEIGHT - nodeH) / 2,
                isBlocked: preNode.isBlocked,
                isIssueNode: preNode.isIssueNode,
                parentThreadId: preNode.parentThreadId,
            })

            cursor += nodeW + HORIZONTAL_GAP
        }
    }

    // Build a position lookup for edge computation
    const nodePositions = new Map(nodes.map((n) => [n.id, n]))

    // Compute edges with per-node dimensions
    const edges: FlowchartEdge[] = []
    for (const dep of dependencies) {
        const source = nodePositions.get(dep.source_thread_id)
        const target = nodePositions.get(dep.target_thread_id)
        if (!source || !target) continue

        const { w: srcW, h: srcH } = nodeDimensions(source)
        const { w: tgtW } = nodeDimensions(target)

        const sourceCenterX = source.x + srcW / 2
        const sourceBottomY = source.y + srcH
        const targetCenterX = target.x + tgtW / 2
        const targetTopY = target.y

        edges.push({
            id: `edge-${dep.id}`,
            sourceId: dep.source_thread_id,
            targetId: dep.target_thread_id,
            path: computeEdgePath(sourceCenterX, sourceBottomY, targetCenterX, targetTopY),
            isBlocking: blockedIds.has(dep.target_thread_id),
            isIssueLevel: dep.is_issue_level ?? false,
        })
    }

    // Compute total dimensions using per-node dimensions
    const maxX = Math.max(0, ...nodes.map((n) => n.x + nodeDimensions(n).w)) + PADDING
    const maxY = Math.max(0, ...nodes.map((n) => n.y + nodeDimensions(n).h)) + PADDING

    return { nodes, edges, width: maxX, height: maxY }
}

export { NODE_WIDTH, NODE_HEIGHT, ISSUE_NODE_WIDTH, ISSUE_NODE_HEIGHT }
