// Optional navigation/status surface. Cannot upload or authorize paid calls.
export function registerWorkspaceTools(
  navigate: (page: "inspect" | "experiments" | "history") => void,
) {
  const context = (
    document as Document & {
      modelContext?: {
        registerTool: (tool: unknown, options: unknown) => Promise<void> | void;
      };
    }
  ).modelContext;
  if (!context) return () => {};
  const controller = new AbortController();
  const tools = [
    {
      name: "inspectmate_read_status",
      title: "검사 환경 상태 읽기",
      description: "Read local model/data readiness. Makes no model calls.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true },
      execute: async (input: unknown) => {
        if (!input || typeof input !== "object" || Object.keys(input).length)
          throw new Error("Expected empty object");
        const response = await fetch("/api/status");
        if (!response.ok) throw new Error("Status unavailable");
        return response.json();
      },
    },
    {
      name: "inspectmate_open_view",
      title: "검사 작업 화면 열기",
      description: "Navigate only. Does not execute inspections.",
      inputSchema: {
        type: "object",
        properties: {
          view: { type: "string", enum: ["inspect", "experiments", "history"] },
        },
        required: ["view"],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false },
      execute: async (input: unknown) => {
        if (
          !input ||
          typeof input !== "object" ||
          Object.keys(input).length !== 1 ||
          !("view" in input) ||
          !["inspect", "experiments", "history"].includes(String(input.view))
        )
          throw new Error("Invalid view");
        const view = input.view as "inspect" | "experiments" | "history";
        navigate(view);
        return { opened: view };
      },
    },
  ];
  for (const tool of tools)
    try {
      Promise.resolve(
        context.registerTool(tool, { signal: controller.signal }),
      ).catch(() => {});
    } catch {
      /* Unsupported browsers do not affect the app. */
    }
  return () => controller.abort();
}
