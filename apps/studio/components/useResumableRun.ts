"use client";

import { useEffect, useRef, useState } from "react";

import { attachTaskStream, listTasks, type CveRunEvent } from "../lib/api";

// On mount, find a still-running task for this theme whose kind is one this page handles,
// and re-attach to it (replay what was missed, then tail live) by feeding its events into
// the page's existing handler. Lets an admin leave a long Gemini run and resume its live
// progress on return. Returns whether such a run is currently attached.
//
// A listed kind also matches sub-kinds (e.g. "financials-research" matches the per-company
// "financials-research:INTC"), so scoped runs resume too.
export function useResumableRun(
  themeId: string,
  kinds: string[],
  onEvent: (event: CveRunEvent) => void,
): { resuming: boolean } {
  const [resuming, setResuming] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const kindsKey = kinds.join(",");

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    void (async () => {
      let tasks;
      try {
        tasks = await listTasks(themeId);
      } catch {
        return;
      }
      const matches = (kind: string) =>
        kinds.some((k) => kind === k || kind.startsWith(`${k}:`));
      const task = tasks.find((t) => t.status === "running" && matches(t.kind));
      if (!task || !alive) return;
      setResuming(true);
      try {
        await attachTaskStream(
          task.id,
          (e) => onEventRef.current(e),
          controller.signal,
        );
      } catch {
        /* stream aborted or failed — ignore */
      } finally {
        if (alive) setResuming(false);
      }
    })();
    return () => {
      alive = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeId, kindsKey]);

  return { resuming };
}
