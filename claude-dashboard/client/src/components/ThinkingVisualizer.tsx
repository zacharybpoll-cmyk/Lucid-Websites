import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";

type Particle = {
  id: number;
  x: number;
  y: number;
  angle: number;
  speed: number;
  radius: number;
  opacity: number;
  color: string;
  born: number;
  lifespan: number;
};

const PHASE_CONFIG = {
  connecting: {
    label: "Connecting",
    colors: ["var(--accent)", "var(--purple)"],
    particleCount: 6,
    speed: 0.8,
  },
  loading_context: {
    label: "Loading Context",
    colors: ["var(--blue)", "var(--cyan)"],
    particleCount: 10,
    speed: 1.2,
  },
  reasoning: {
    label: "Reasoning",
    colors: ["var(--accent)", "var(--blue)", "var(--purple)"],
    particleCount: 14,
    speed: 1.5,
  },
  generating: {
    label: "Generating",
    colors: ["var(--green)", "var(--cyan)", "var(--accent)"],
    particleCount: 12,
    speed: 2.0,
  },
};

export function ThinkingVisualizer() {
  const thinkingPhase = useStore((s) => s.thinkingPhase);
  const thinkingDetail = useStore((s) => s.thinkingDetail);
  const status = useStore((s) => s.status);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const frameRef = useRef<number>(0);
  const nextIdRef = useRef(0);
  const [resolvedColors, setResolvedColors] = useState<Map<string, string>>(new Map());

  const isActive = status !== "idle" && thinkingPhase !== null;

  // Resolve CSS variables to actual colors
  useEffect(() => {
    const allVars = new Set<string>();
    Object.values(PHASE_CONFIG).forEach((c) => c.colors.forEach((v) => allVars.add(v)));

    const map = new Map<string, string>();
    const el = document.createElement("div");
    document.body.appendChild(el);

    allVars.forEach((v) => {
      el.style.color = v;
      const computed = getComputedStyle(el).color;
      map.set(v, computed);
    });

    document.body.removeChild(el);
    setResolvedColors(map);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !isActive) {
      particlesRef.current = [];
      return;
    }

    const config = thinkingPhase ? PHASE_CONFIG[thinkingPhase] : PHASE_CONFIG.connecting;
    const dpr = window.devicePixelRatio || 1;

    function resize() {
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
    }
    resize();

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let running = true;

    function spawnParticle() {
      if (!canvas) return;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      const cx = w / 2;
      const cy = h / 2;
      const angle = Math.random() * Math.PI * 2;
      const color = config.colors[Math.floor(Math.random() * config.colors.length)];

      particlesRef.current.push({
        id: nextIdRef.current++,
        x: cx + (Math.random() - 0.5) * 20,
        y: cy + (Math.random() - 0.5) * 20,
        angle,
        speed: config.speed * (0.5 + Math.random()),
        radius: 2 + Math.random() * 4,
        opacity: 0.8,
        color,
        born: Date.now(),
        lifespan: 2000 + Math.random() * 2000,
      });
    }

    function animate() {
      if (!running || !ctx || !canvas) return;

      const w = canvas.width / dpr;
      const h = canvas.height / dpr;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const now = Date.now();

      // Spawn new particles
      if (particlesRef.current.length < config.particleCount) {
        spawnParticle();
      }

      // Draw center glow
      const cx = w / 2;
      const cy = h / 2;
      const pulseSize = 20 + Math.sin(now / 500) * 8;
      const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, pulseSize);
      const mainColor = resolvedColors.get(config.colors[0]) || "rgb(124, 90, 255)";
      gradient.addColorStop(0, mainColor.replace(")", ", 0.3)").replace("rgb", "rgba"));
      gradient.addColorStop(0.5, mainColor.replace(")", ", 0.1)").replace("rgb", "rgba"));
      gradient.addColorStop(1, "transparent");
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(cx, cy, pulseSize, 0, Math.PI * 2);
      ctx.fill();

      // Center dot
      ctx.fillStyle = mainColor.replace(")", ", 0.8)").replace("rgb", "rgba");
      ctx.beginPath();
      ctx.arc(cx, cy, 4 + Math.sin(now / 300) * 1, 0, Math.PI * 2);
      ctx.fill();

      // Update and draw particles
      particlesRef.current = particlesRef.current.filter((p) => {
        const age = now - p.born;
        if (age > p.lifespan) return false;

        const progress = age / p.lifespan;

        // Move outward in a spiral
        p.x += Math.cos(p.angle + progress * 2) * p.speed;
        p.y += Math.sin(p.angle + progress * 2) * p.speed;

        // Fade out
        p.opacity = Math.max(0, 0.8 * (1 - progress));

        const resolved = resolvedColors.get(p.color) || "rgb(124, 90, 255)";
        const r = p.radius * (1 - progress * 0.5);

        // Glow
        const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3);
        glow.addColorStop(0, resolved.replace(")", `, ${p.opacity * 0.3})`).replace("rgb", "rgba"));
        glow.addColorStop(1, "transparent");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 3, 0, Math.PI * 2);
        ctx.fill();

        // Core dot
        ctx.fillStyle = resolved.replace(")", `, ${p.opacity})`).replace("rgb", "rgba");
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();

        // Trail line back toward center
        if (progress < 0.5) {
          ctx.strokeStyle = resolved.replace(")", `, ${p.opacity * 0.2})`).replace("rgb", "rgba");
          ctx.lineWidth = 0.5;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(p.x, p.y);
          ctx.stroke();
        }

        return true;
      });

      // Orbiting ring
      const ringRadius = 35 + Math.sin(now / 800) * 5;
      ctx.strokeStyle = mainColor.replace(")", ", 0.08)").replace("rgb", "rgba");
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, ringRadius, 0, Math.PI * 2);
      ctx.stroke();

      // Orbiting dot on ring
      const orbitAngle = (now / 1000) * 2;
      const ox = cx + Math.cos(orbitAngle) * ringRadius;
      const oy = cy + Math.sin(orbitAngle) * ringRadius;
      ctx.fillStyle = mainColor.replace(")", ", 0.5)").replace("rgb", "rgba");
      ctx.beginPath();
      ctx.arc(ox, oy, 2, 0, Math.PI * 2);
      ctx.fill();

      frameRef.current = requestAnimationFrame(animate);
    }

    animate();

    return () => {
      running = false;
      cancelAnimationFrame(frameRef.current);
    };
  }, [isActive, thinkingPhase, resolvedColors]);

  if (!isActive) return null;

  const config = thinkingPhase ? PHASE_CONFIG[thinkingPhase] : PHASE_CONFIG.connecting;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 20px",
        gap: 16,
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          width: 200,
          height: 200,
          display: "block",
        }}
      />

      <div style={{ textAlign: "center" }}>
        <div
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "var(--text-primary)",
            marginBottom: 4,
          }}
        >
          {config.label}
          <span className="thinking-dot" style={{ marginLeft: 4 }} />
          <span className="thinking-dot" />
          <span className="thinking-dot" />
        </div>
        {thinkingDetail && (
          <div
            className="fade-in"
            style={{
              fontSize: 12,
              color: "var(--text-secondary)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {thinkingDetail}
          </div>
        )}
      </div>
    </div>
  );
}
