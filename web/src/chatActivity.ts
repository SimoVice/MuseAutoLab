export type RequestActivity = { title: string; detail: string };

const stages: Record<string, RequestActivity> = {
  waiting: { title: 'Request received', detail: 'Waiting for this project’s current operation.' },
  interpreting: { title: 'Interpreting your request', detail: 'Reviewing the message and current project with the assistant.' },
  applying: { title: 'Applying your request', detail: 'Running the requested project actions and checking the result.' },
  sourcing: { title: 'Sourcing components', detail: 'Checking the reviewed platform catalogues for current price observations.' },
  assembling: { title: 'Assembling the 3D design', detail: 'Preparing the layout and checking the requested changes.' },
};

/** Poll only while the corresponding POST is pending. No invented stage sequence. */
export function watchChatActivity(projectId: string, requestId: string, signal: AbortSignal,
  onActivity: (activity: RequestActivity) => void): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const pollController = new AbortController();
  const stop = () => {
    stopped = true;
    clearTimeout(timer);
    pollController.abort();
    signal.removeEventListener('abort', stop);
  };
  const poll = async () => {
    if (stopped || signal.aborted) return;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/activity/${encodeURIComponent(requestId)}`,
        { signal: pollController.signal, cache: 'no-store' });
      if (response.ok) {
        const data = await response.json() as { active: boolean; stage: string };
        if (!stopped && !signal.aborted && data.active && stages[data.stage]) onActivity(stages[data.stage]);
        if (!data.active) { stop(); return; }
      }
    } catch { /* The POST remains authoritative; polling failure must not fail a turn. */ }
    if (!stopped && !signal.aborted) timer = setTimeout(() => void poll(), 650);
  };
  signal.addEventListener('abort', stop, { once: true });
  void poll();
  return stop;
}
