export const TOOL_COLOR_MAP: Record<string, string> = {
  Read: "var(--blue)",
  Grep: "var(--blue)",
  Glob: "var(--blue)",
  Edit: "var(--green)",
  Write: "var(--green)",
  NotebookEdit: "var(--green)",
  Bash: "var(--orange)",
  Task: "var(--purple)",
  WebFetch: "var(--cyan)",
  WebSearch: "var(--cyan)",
  AskUserQuestion: "var(--text-secondary)",
  EnterPlanMode: "var(--text-secondary)",
  ExitPlanMode: "var(--text-secondary)",
};

export function getToolColor(tool: string): string {
  return TOOL_COLOR_MAP[tool] || "var(--text-secondary)";
}

export const TOOL_ICON_MAP: Record<string, string> = {
  Read: "R",
  Grep: "G",
  Glob: "F",
  Edit: "E",
  Write: "W",
  NotebookEdit: "N",
  Bash: "$",
  Task: "T",
  WebFetch: "W",
  WebSearch: "S",
};

export function getToolIcon(tool: string): string {
  return TOOL_ICON_MAP[tool] || "?";
}
