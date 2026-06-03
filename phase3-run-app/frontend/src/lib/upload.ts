// Bounded-concurrency task pool with per-task retry, for parallel browser->GCS uploads.
export async function runPool<T>(
  tasks: Array<() => Promise<T>>,
  concurrency = 10,
  retries = 3,
): Promise<T[]> {
  const results: T[] = new Array(tasks.length);
  let next = 0;
  async function worker() {
    while (next < tasks.length) {
      const i = next++;
      let attempt = 0;
      for (;;) {
        try {
          results[i] = await tasks[i]();
          break;
        } catch (e) {
          if (++attempt >= retries) throw e;
          await new Promise((r) => setTimeout(r, 300 * attempt));
        }
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(concurrency, tasks.length) }, worker),
  );
  return results;
}

// Upload one file to its signed PUT URL.
export async function putFile(url: string, file: File, f: typeof fetch = fetch.bind(globalThis)): Promise<void> {
  const r = await f(url, { method: "PUT", body: file });
  if (!r.ok) throw new Error(`PUT ${r.status}`);
}
