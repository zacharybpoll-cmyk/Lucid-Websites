import { useRef, useEffect } from "react";

type Props = {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
};

export function Sparkline({
  data,
  width = 200,
  height = 40,
  color = "var(--accent)",
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    const max = Math.max(...data, 1);
    const padding = 2;
    const w = width - padding * 2;
    const h = height - padding * 2;

    // Draw filled area
    ctx.beginPath();
    ctx.moveTo(padding, height - padding);

    data.forEach((val, i) => {
      const x = padding + (i / (data.length - 1)) * w;
      const y = padding + h - (val / max) * h;
      ctx.lineTo(x, y);
    });

    ctx.lineTo(padding + w, height - padding);
    ctx.closePath();

    // Resolve CSS variable to actual color
    const tempEl = document.createElement("div");
    tempEl.style.color = color;
    document.body.appendChild(tempEl);
    const resolved = getComputedStyle(tempEl).color;
    document.body.removeChild(tempEl);

    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, resolved.replace(")", ", 0.3)").replace("rgb", "rgba"));
    gradient.addColorStop(1, resolved.replace(")", ", 0.02)").replace("rgb", "rgba"));
    ctx.fillStyle = gradient;
    ctx.fill();

    // Draw line
    ctx.beginPath();
    data.forEach((val, i) => {
      const x = padding + (i / (data.length - 1)) * w;
      const y = padding + h - (val / max) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    ctx.strokeStyle = resolved;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";
    ctx.stroke();

    // Current value dot
    if (data.length > 0) {
      const lastVal = data[data.length - 1];
      const x = padding + w;
      const y = padding + h - (lastVal / max) * h;
      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = resolved;
      ctx.fill();
    }
  }, [data, width, height, color]);

  if (data.length < 2) {
    return (
      <div
        style={{
          width,
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-secondary)",
          fontSize: 10,
        }}
      >
        Collecting data...
      </div>
    );
  }

  return (
    <canvas
      ref={canvasRef}
      style={{
        width,
        height,
        display: "block",
      }}
    />
  );
}
