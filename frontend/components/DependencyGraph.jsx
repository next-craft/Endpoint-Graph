'use client'
import { useMemo } from 'react'
import { ReactFlow, Background, Controls, MiniMap, BaseEdge, getSmoothStepPath } from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import '@xyflow/react/dist/style.css'

const LEAF_WIDTH = 220
const LEAF_HEIGHT = 56
const LEAF_GAP = 10
const FILE_HEADER = 28
const FILE_PADDING = 16
const FILE_GAP = 20
const SERVICE_PADDING = 24
const SERVICE_HEADER = 32
const SERVICE_COL_GAP = 60
const TIER_ROW_GAP = 220

const SERVICE_GROUP_STYLE = {
  background: 'rgba(20, 33, 61, 0.35)',
  border: '1px solid #29447e',
  borderRadius: '10px',
}
const FILE_GROUP_STYLE = {
  background: 'rgba(12, 20, 37, 0.6)',
  border: '1px dashed #3e67bf',
  borderRadius: '6px',
}
const ENDPOINT_LEAF_STYLE = {
  background: '#0c1425', border: '1.5px solid #fca311', borderColor: '#fca311',
  color: '#e5e5e5', borderRadius: '6px', fontSize: '12px',
  fontFamily: 'ui-monospace, SFMono-Regular, monospace', padding: '8px 12px',
  whiteSpace: 'pre-line',
}
const CALLER_LEAF_STYLE = {
  background: '#14213d', border: '1px solid #29447e', borderColor: '#29447e',
  color: '#e5e5e5', borderRadius: '6px', fontSize: '12px',
  fontFamily: 'ui-monospace, SFMono-Regular, monospace', padding: '8px 12px',
}

const defaultEdgeOptions = {
  type: 'fanned',
  style: { stroke: '#29447e', strokeWidth: 1.5 },
  labelStyle: { fill: '#8a8a8a', fontSize: 10, fontFamily: 'ui-monospace, SFMono-Regular, monospace' },
  labelBgStyle: { fill: '#000000', fillOpacity: 0.85 },
  labelBgPadding: [5, 3],
}

// Per-caller stroke colors so each origin is identifiable even where fanned
// paths cross near a shared endpoint.
const EDGE_PALETTE = [
  '#fca311', '#4cc9f0', '#80ed99', '#f72585', '#b5179e',
  '#4361ee', '#ffd166', '#06d6a0', '#ef476f', '#c77dff',
]

function hashToIndex(str, mod) {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) | 0
  }
  return Math.abs(hash) % mod
}

function colorForCaller(callerId) {
  return EDGE_PALETTE[hashToIndex(callerId, EDGE_PALETTE.length)]
}

// Max horizontal shift for a fanned connection point, kept inside the leaf
// node's own width so the line still visibly emerges from within the node.
const FAN_SPACING = 26
const FAN_MAX = LEAF_WIDTH / 2 - 24

// Custom edge: same smoothstep routing as the default, but the source/target
// connection point is nudged sideways per leaf index so edges between two
// X-aligned, vertically-stacked columns fan out instead of overlapping.
function FannedEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  style, markerEnd, label, labelStyle, labelBgStyle, labelBgPadding, data,
}) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX: sourceX + (data?.sourceOffset ?? 0),
    sourceY,
    sourcePosition,
    targetX: targetX + (data?.targetOffset ?? 0),
    targetY,
    targetPosition,
    borderRadius: 8,
  })
  return (
    <BaseEdge
      id={id}
      path={path}
      markerEnd={markerEnd}
      style={style}
      label={label}
      labelX={labelX}
      labelY={labelY}
      labelStyle={labelStyle}
      labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding}
    />
  )
}

const edgeTypes = { fanned: FannedEdge }

function buildElements(nodes, edges) {
  const byService = new Map()
  for (const n of nodes) {
    if (!byService.has(n.service_name)) {
      byService.set(n.service_name, { serviceId: n.service_id, files: new Map() })
    }
    const svc = byService.get(n.service_name)
    const fileKey = n.file_path ?? '(unknown)'
    if (!svc.files.has(fileKey)) svc.files.set(fileKey, [])
    svc.files.get(fileKey).push(n)
  }

  const providerServices = new Set(nodes.filter((n) => n.node_type === 'endpoint').map((n) => n.service_name))
  const callerServices = new Set(nodes.filter((n) => n.node_type === 'caller').map((n) => n.service_name))
  function tierOf(serviceName) {
    const isProvider = providerServices.has(serviceName)
    const isCaller = callerServices.has(serviceName)
    if (isCaller && !isProvider) return 0
    if (isCaller && isProvider) return 1
    return 2
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]))
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: SERVICE_COL_GAP, ranksep: TIER_ROW_GAP })
  g.setDefaultEdgeLabel(() => ({}))
  for (const serviceName of byService.keys()) g.setNode(serviceName, { width: 1, height: 1 })
  const seenServiceEdges = new Set()
  for (const e of edges) {
    const caller = nodeById.get(e.source)
    const target = nodeById.get(e.target)
    if (!caller || !target || caller.service_name === target.service_name) continue
    const key = `${caller.service_name}->${target.service_name}`
    if (!seenServiceEdges.has(key)) {
      seenServiceEdges.add(key)
      g.setEdge(caller.service_name, target.service_name)
    }
  }
  dagre.layout(g)

  const tiers = [[], [], []]
  for (const serviceName of byService.keys()) tiers[tierOf(serviceName)].push(serviceName)
  for (const tier of tiers) tier.sort((a, b) => g.node(a).x - g.node(b).x)

  const rfNodes = []
  const leafPosInGroup = new Map() // leaf id -> { index, count } within its file group
  tiers.forEach((tierServices, tierIndex) => {
    let cursorX = 0
    const tierY = tierIndex * TIER_ROW_GAP
    for (const serviceName of tierServices) {
      const { files } = byService.get(serviceName)
      let fileCursorX = SERVICE_PADDING
      let serviceHeight = SERVICE_HEADER
      const fileLayouts = []
      for (const [filePath, leaves] of files) {
        const fileWidth = LEAF_WIDTH + FILE_PADDING * 2
        const fileHeight = FILE_HEADER + leaves.length * (LEAF_HEIGHT + LEAF_GAP) + FILE_PADDING
        fileLayouts.push({ filePath, leaves, x: fileCursorX, width: fileWidth, height: fileHeight })
        fileCursorX += fileWidth + FILE_GAP
        serviceHeight = Math.max(serviceHeight, SERVICE_HEADER + fileHeight + SERVICE_PADDING)
      }
      const serviceWidth = fileCursorX - FILE_GAP + SERVICE_PADDING

      rfNodes.push({
        id: serviceName, type: 'group',
        position: { x: cursorX, y: tierY },
        style: { width: serviceWidth, height: serviceHeight, ...SERVICE_GROUP_STYLE },
        data: { label: serviceName },
      })

      for (const fl of fileLayouts) {
        const fileGroupId = `${serviceName}:${fl.filePath}`
        rfNodes.push({
          id: fileGroupId, type: 'group', parentId: serviceName, extent: 'parent',
          position: { x: fl.x, y: SERVICE_HEADER },
          style: { width: fl.width, height: fl.height, ...FILE_GROUP_STYLE },
          data: { label: fl.filePath },
        })
        fl.leaves.forEach((leaf, i) => {
          rfNodes.push({
            id: leaf.id, parentId: fileGroupId, extent: 'parent',
            position: { x: FILE_PADDING, y: FILE_HEADER + i * (LEAF_HEIGHT + LEAF_GAP) },
            data: { label: leaf.label, ...leaf },
            style: leaf.node_type === 'endpoint' ? ENDPOINT_LEAF_STYLE : CALLER_LEAF_STYLE,
          })
          leafPosInGroup.set(leaf.id, { index: i, count: fl.leaves.length })
        })
      }
      cursorX += serviceWidth + SERVICE_COL_GAP
    }
  })

  function fanOffset(leafId) {
    const info = leafPosInGroup.get(leafId)
    if (!info || info.count <= 1) return 0
    const centered = info.index - (info.count - 1) / 2
    return Math.max(-FAN_MAX, Math.min(FAN_MAX, centered * FAN_SPACING))
  }

  const rfEdges = edges.map((e) => {
    const color = colorForCaller(e.source)
    return {
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      label: `×${e.call_count}`,
      type: 'fanned',
      style: { stroke: color, strokeWidth: 1.5 },
      data: {
        sourceOffset: fanOffset(e.source),
        targetOffset: fanOffset(e.target),
      },
    }
  })

  return { rfNodes, rfEdges }
}

export default function DependencyGraph({ nodes, edges, onNodeClick }) {
  const { rfNodes, rfEdges } = useMemo(() => buildElements(nodes, edges), [nodes, edges])

  return (
    <div style={{ width: '100%', height: '100%', background: '#000000' }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background color="#29447e" gap={28} size={1} variant="dots" />
        <Controls />
        <MiniMap
          nodeColor={(node) => (node.data?.node_type === 'endpoint' ? '#fca311' : '#29447e')}
          maskColor="rgba(0,0,0,0.7)"
        />
      </ReactFlow>
    </div>
  )
}
