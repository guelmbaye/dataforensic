"use client";

import { useEffect, useRef } from "react";

import { MILESTONE_EVENTS, PHASE_ACTIVITY, clockTime } from "@/lib/format";
import type { InvestigationEvent } from "@/lib/types";

function dotClass(event: InvestigationEvent, running: boolean, isLast: boolean): string {
  const classes = ["tl-dot"];
  if (event.level === "error") classes.push("error");
  else if (event.level === "warning") classes.push("warning");
  else if (MILESTONE_EVENTS.has(event.event)) classes.push("milestone");
  if (running && isLast) classes.push("running");
  return classes.join(" ");
}

export function InvestigationTimeline({
  events,
  running,
  phase,
}: {
  events: InvestigationEvent[];
  running: boolean;
  phase: string | null;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  // Follow the stream, but stop following the moment the reader scrolls up:
  // yanking the view away while someone is reading an event is hostile.
  useEffect(() => {
    const node = scroller.current;
    if (!node || !pinned.current) return;
    node.scrollTop = node.scrollHeight;
  }, [events.length]);

  const onScroll = () => {
    const node = scroller.current;
    if (!node) return;
    pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48;
  };

  const activity = phase ? PHASE_ACTIVITY[phase] : null;

  return (
    <div className="panel spine">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Agent activity</div>
          <h2 style={{ fontSize: 15 }}>Investigation log</h2>
        </div>
        <span className="mono small muted">{events.length} events</span>
      </div>

      <div className="timeline" ref={scroller} onScroll={onScroll}>
        {events.length === 0 ? (
          <p className="small muted" style={{ padding: "16px 0" }}>
            No activity yet. The log fills in as the agent works.
          </p>
        ) : null}

        {events.map((event, index) => {
          const isMilestone = MILESTONE_EVENTS.has(event.event);
          return (
            <div
              key={event.seq}
              className={`tl-item${isMilestone ? " milestone" : ""}`}
            >
              <div className="tl-time">{clockTime(event.created_at)}</div>
              <div className="tl-mark">
                <span
                  className={dotClass(event, running, index === events.length - 1)}
                />
              </div>
              <div className="tl-body">
                <div className="tl-event">{event.event.replace(/_/g, " ")}</div>
                <div className="tl-message">{event.message}</div>
              </div>
            </div>
          );
        })}
      </div>

      {running && activity ? (
        <div className="tl-working">
          <span className="pill accent running" style={{ padding: 0 }}>
            <span className="dot" />
          </span>
          {activity}…
        </div>
      ) : null}
    </div>
  );
}
