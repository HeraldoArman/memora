"use client";

import dynamic from "next/dynamic";
import { forceX, forceY } from "d3-force";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type GraphData } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ponytail: react-force-graph-2d uses canvas + d3 — must be client-only, no SSR.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const NODE_COLORS: Record<string, string> = {
  Person: "#5038bc",
  User: "#5038bc",
  Organization: "#6248dc",
  Place: "#7c5cf0",
  Object: "#a78bfa",
  Food: "#c9cefc",
  Event: "#a855f7",
  Preference: "#22d3ee",
  Reminder: "#d946ef",
};

export default function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [selected, setSelected] = useState<{ id: string; label: string; type: string } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [dims, setDims] = useState({ w: 800, h: 600 });
  const GRAPH_W = Math.min(dims.w, 960);
  const GRAPH_H = dims.h;

  useEffect(() => {
    api
      .graph()
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDims({ w: Math.max(width, 300), h: Math.max(height, 300) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    // Dedupe nodes by name, map edges to node refs.
    const nodeMap = new Map<string, { id: string; label: string; type: string }>();
    for (const n of data.nodes) {
      if (!nodeMap.has(n.name)) {
        nodeMap.set(n.name, { id: n.name, label: n.name, type: n.label });
      }
    }
    const links = data.edges
      .filter((e) => nodeMap.has(e.from) && nodeMap.has(e.to))
      .map((e, i) => ({
        source: e.from,
        target: e.to,
        label: e.type,
        id: `${e.from}-${e.type}-${e.to}-${i}`,
      }));
    return { nodes: Array.from(nodeMap.values()), links };
  }, [data]);

  // Cap graph width at 960 so forceX/Y center is tight (full-width viewport made
  // orphan nodes scatter across a huge area). Weaken charge so 190 orphan nodes
  // don't fly apart, and strengthen center pull to overpower charge.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    // Match the basic D3 force model from the reference.
    fg.d3Force("link");
    fg.d3Force("charge");
    fg.d3Force("x", forceX());
    fg.d3Force("y", forceY());

    // No collision force.
    fg.d3Force("collide", null);
  }, [graphData]);

  // Reheat only when new data arrives (fresh layout), never on resize — re-arming
  // the sim on every ResizeObserver tick is what made a static node-hold push the
  // rest of the graph away (dragstart pins a node, an alive charge force shoves
  // others to a new equilibrium).
  useEffect(() => {
    fgRef.current?.d3ReheatSimulation();
  }, [graphData]);

  const nodeTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    graphData.nodes.forEach((n) => {
      counts[n.type] = (counts[n.type] ?? 0) + 1;
    });
    return counts;
  }, [graphData.nodes]);

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-neutral-900">Knowledge Graph</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Neo4j semantic memory — entities and their relationships.
        </p>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* Graph canvas */}
        <div
          ref={containerRef}
          className="relative flex flex-1 items-center justify-center overflow-hidden rounded-xl border border-accent-500/20 bg-gradient-to-br from-accent-500/5 to-ink-900"
        >
          {error ? (
            <div className="flex h-full items-center justify-center">
              <p className="font-mono text-sm text-crit-400">{error}</p>
            </div>
          ) : !data ? (
            <div className="flex h-full items-center justify-center">
              <p className="font-mono text-sm text-ink-500">Loading graph…</p>
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center">
              <p className="font-mono text-sm text-ink-500">No data in the knowledge graph yet.</p>
            </div>
          ) : (
            <ForceGraph2D
              ref={fgRef}
              graphData={graphData}
              width={GRAPH_W}
              height={GRAPH_H}
              nodeLabel="label"
              nodeColor={(node: any) => NODE_COLORS[node.type] ?? "#9aa0ae"}
              nodeRelSize={10}
              linkLabel="label"
              linkColor={() => "#c9cefc"}
              linkWidth={5}

              linkDirectionalArrowLength={10}
              linkDirectionalArrowRelPos={1}
              onNodeClick={(node: any) => setSelected(node)}
              cooldownTicks={1000}
            />
          )}
        </div>

        {/* Side panel */}
        <div className="w-72 shrink-0 space-y-4 overflow-y-auto scrollbar-thin">
          {/* Legend */}
          <Card>
            <CardHeader title="Legend" />
            <CardBody className="space-y-2">
              {Object.entries(NODE_COLORS)
                .filter(([t]) => nodeTypeCounts[t])
                .map(([type, color]) => (
                  <div key={type} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="size-3 rounded-full" style={{ background: color }} />
                      <span className="text-sm text-neutral-700">{type}</span>
                    </div>
                    <span className="font-mono text-xs text-ink-500">
                      {nodeTypeCounts[type] ?? 0}
                    </span>
                  </div>
                ))}
              <div className="border-t border-ink-700 pt-2">
                <p className="font-mono text-xs text-ink-500">
                  {graphData.nodes.length} nodes · {graphData.links.length} edges
                </p>
              </div>
            </CardBody>
          </Card>

          {/* Selected node detail */}
          {selected && (
            <Card>
              <CardHeader title="Selected Node" />
              <CardBody className="space-y-3">
                <div>
                  <p className="font-mono text-xs uppercase tracking-widest text-ink-500">Name</p>
                  <p className="text-sm text-neutral-800">{selected.label}</p>
                </div>
                <div>
                  <p className="font-mono text-xs uppercase tracking-widest text-ink-500">Type</p>
                  <Badge>{selected.type}</Badge>
                </div>
                {/* Show connected edges */}
                <div>
                  <p className="mb-1 font-mono text-xs uppercase tracking-widest text-ink-500">
                    Relationships
                  </p>
                  <ul className="space-y-1">
                    {graphData.links
                      .filter((l: any) => {
                        // d3-force resolves link source/target to node objects
                        // after the simulation runs, so compare via .id (string both
                        // before + after resolution).
                        const s = typeof l.source === "object" ? l.source.id : l.source;
                        const t = typeof l.target === "object" ? l.target.id : l.target;
                        return s === selected.id || t === selected.id;
                      })
                      .map((l: any) => {
                        const s = typeof l.source === "object" ? l.source.id : l.source;
                        const t = typeof l.target === "object" ? l.target.id : l.target;
                        const outgoing = s === selected.id;
                        return (
                          <li
                            key={l.id}
                            className="rounded bg-ink-800 px-2 py-1 font-mono text-xs text-neutral-600"
                          >
                            {outgoing ? "→" : "←"} {l.label} {outgoing ? t : s}
                          </li>
                        );
                      })}
                  </ul>
                </div>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
