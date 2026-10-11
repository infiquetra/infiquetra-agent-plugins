// One writer for every pane tool's answer (issue #218): the session
// validates a `tool.call` hook's answer against the tool's output schema,
// which for a registered tool admits a string, an array of content blocks,
// or nothing — never an object. Each pane keeps its documented status object
// and sends it as compact JSON text, which the caller parses back.

/** The status object as the session accepts it: compact JSON text. */
export function paneResult(outcome: unknown): string {
  return JSON.stringify(outcome)
}
