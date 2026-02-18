type Props = {
  label: string;
  value: string | number;
  color?: string;
  children?: React.ReactNode;
};

export function StatCard({ label, value, color, children }: Props) {
  return (
    <div
      style={{
        padding: "10px 12px",
        background: "var(--surface)",
        borderRadius: "var(--radius)",
        border: "1px solid var(--border)",
        marginBottom: 8,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: "var(--text-secondary)",
          marginBottom: 4,
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        className="count-animate"
        key={String(value)}
        style={{
          fontSize: 20,
          fontWeight: 600,
          color: color || "var(--text-primary)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {value}
      </div>
      {children}
    </div>
  );
}
