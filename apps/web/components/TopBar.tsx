"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { DataHubStatus } from "@/lib/types";
import { ContextSourceBadge } from "./Primitives";

export function TopBar() {
  const [status, setStatus] = useState<DataHubStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    const load = () => {
      api
        .datahubStatus()
        .then((next) => {
          if (!active) return;
          setStatus(next);
          setUnreachable(false);
        })
        .catch(() => active && setUnreachable(true));
    };
    load();
    const timer = setInterval(load, 20000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <header className="topbar">
      <div className="shell topbar-inner">
        {/* The dark variant of the lockup: the neutral half of the wordmark is
            white so it survives the ink bar, while the blue and orange stay
            exactly as designed. */}
        <Link href="/" className="wordmark" aria-label="DATAFORENSIC AI — home">
          <Image
            src="/logo-dark.png"
            alt="DATAFORENSIC AI"
            width={960}
            height={240}
            priority
            className="wordmark-logo"
          />
        </Link>

        <span className="wordmark-tagline">investigate · resolve · remember</span>

        <nav className="topnav">
          <Link href="/">Incidents</Link>
          <Link href="/patterns">Memory</Link>
        </nav>

        <div className="topbar-spacer" />

        {unreachable ? (
          <span className="source-badge unknown">
            <span className="source-dot" />
            API unreachable
          </span>
        ) : (
          <ContextSourceBadge
            mode={status?.source_mode}
            detail={status?.detail || status?.datahub_url || undefined}
          />
        )}
      </div>
    </header>
  );
}
