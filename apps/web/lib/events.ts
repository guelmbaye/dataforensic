"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { streamUrl } from "./api";
import type { InvestigationEvent } from "./types";

const TERMINAL = new Set([
  "investigation_completed",
  "investigation_failed",
  "investigation_blocked",
]);

interface StreamState {
  events: InvestigationEvent[];
  live: boolean;
  finished: boolean;
}

/**
 * Subscribes to the investigation timeline.
 *
 * The API replays everything above `lastEventId` before switching to live
 * delivery, and every event carries a sequence number, so a reconnect resumes
 * exactly where it stopped and duplicates are dropped here rather than shown.
 */
export function useInvestigationStream(
  investigationId: string | null,
  enabled: boolean,
): StreamState & { reset: () => void } {
  const [events, setEvents] = useState<InvestigationEvent[]>([]);
  const [live, setLive] = useState(false);
  const [finished, setFinished] = useState(false);
  const seen = useRef<Set<number>>(new Set());
  const highest = useRef(0);

  const reset = useCallback(() => {
    seen.current = new Set();
    highest.current = 0;
    setEvents([]);
    setFinished(false);
  }, []);

  useEffect(() => {
    if (!investigationId || !enabled) return;

    const source = new EventSource(streamUrl(investigationId, highest.current));
    let closed = false;

    const ingest = (raw: string) => {
      let parsed: InvestigationEvent;
      try {
        parsed = JSON.parse(raw) as InvestigationEvent;
      } catch {
        return;
      }
      if (typeof parsed.seq !== "number" || seen.current.has(parsed.seq)) return;
      seen.current.add(parsed.seq);
      highest.current = Math.max(highest.current, parsed.seq);
      setEvents((current) => [...current, parsed].sort((a, b) => a.seq - b.seq));
      if (TERMINAL.has(parsed.event)) {
        setFinished(true);
      }
    };

    source.onopen = () => setLive(true);
    // Data frames arrive unnamed on purpose, so this single handler sees all of
    // them. EventSource has no wildcard listener: a frame sent as
    // `event: evidence_found` would only reach a listener registered for that
    // exact name, and any event type added later would silently disappear.
    source.onmessage = (message) => ingest(message.data);
    source.addEventListener("stream_closed", () => {
      closed = true;
      setFinished(true);
      setLive(false);
      source.close();
    });
    source.onerror = () => {
      setLive(false);
      if (closed) source.close();
    };

    return () => {
      closed = true;
      source.close();
      setLive(false);
    };
  }, [investigationId, enabled]);

  return { events, live, finished, reset };
}
