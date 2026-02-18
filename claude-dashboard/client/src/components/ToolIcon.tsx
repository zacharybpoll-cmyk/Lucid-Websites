import { getToolColor, getToolIcon } from "../lib/colors";

type Props = {
  tool: string;
  size?: number;
  active?: boolean;
};

export function ToolIcon({ tool, size = 24, active }: Props) {
  const color = getToolColor(tool);
  const icon = getToolIcon(tool);

  return (
    <div
      className={active ? "pulse-glow" : ""}
      style={{
        width: size,
        height: size,
        borderRadius: "var(--radius-sm)",
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
        color,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.45,
        fontFamily: "var(--font-mono)",
        fontWeight: 600,
        flexShrink: 0,
      }}
    >
      {icon}
    </div>
  );
}
