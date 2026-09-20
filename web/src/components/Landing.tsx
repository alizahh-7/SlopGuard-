import { useEffect, useMemo, useState, type CSSProperties } from "react";
import AnimatedGradient from "./ui/animated-gradient";

interface LandingProps {
  onScan?: () => void;
  onLearn?: () => void;
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

const MASK =
  "linear-gradient(to bottom, transparent 0%, #000 16%, #000 60%, transparent 100%), linear-gradient(to right, transparent 0%, #000 12%, #000 88%, transparent 100%)";

// Fades all four edges so the gradient melts into the page background.
const fadeMask: CSSProperties = {
  maskImage: MASK,
  WebkitMaskImage: MASK,
  maskComposite: "intersect",
  WebkitMaskComposite: "source-in",
};

export default function Landing({ onScan, onLearn }: LandingProps) {
  const reduced = usePrefersReducedMotion();

  const gradient = useMemo(
    () => ({ preset: "Oceanic" as const, speed: reduced ? 0 : 10 }),
    [reduced]
  );

  const goScan = onScan ?? (() => { window.location.hash = "scanner"; });
  const goLearn = onLearn ?? (() => { window.location.hash = "learn"; });

  return (
    <section className="relative isolate flex min-h-[calc(100svh-74px)] w-full items-center overflow-hidden text-white">
      <div className="absolute inset-0 -z-10" aria-hidden="true" style={fadeMask}>
        <AnimatedGradient config={gradient} noise={{ opacity: 0.15 }} />
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(to right, rgba(0,8,20,0.8) 0%, rgba(0,8,20,0.45) 50%, rgba(0,8,20,0.05) 100%)",
          }}
        />
      </div>

      <style>{`
        @keyframes sg-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        .sg-line { opacity: 0; animation: sg-reveal 450ms ease-out forwards; }
        @media (prefers-reduced-motion: reduce) { .sg-line { opacity: 1; animation: none; } }
      `}</style>

      <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[1.1fr_0.9fr] lg:py-24">
        <div>
          <h1 className="text-6xl tracking-tight sm:text-7xl lg:text-8xl">
            <span className="font-light">Slop</span>
            <span className="font-semibold">Guard</span>
          </h1>

          <p className="mt-6 max-w-xl text-2xl font-medium leading-snug text-white/90 sm:text-3xl">
            AI can invent packages. Attackers can register them. Check before you install.
          </p>

          <p className="mt-5 max-w-lg text-base leading-relaxed text-white/70">
            Paste AI-generated code or a dependency file. SlopGuard checks every package
            against PyPI and npm before you run the install command.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={goScan}
              className="rounded-lg bg-cyan-300 px-5 py-3 text-sm font-semibold text-[#00202b] transition hover:bg-cyan-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            >
              Scan your dependencies
            </button>
            <button
              type="button"
              onClick={goLearn}
              className="rounded-lg border border-white/25 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            >
              See how it works
            </button>
          </div>

          <ul className="mt-10 flex flex-wrap gap-x-8 gap-y-2 text-sm text-white/65">
            <li>Checks PyPI and npm</li>
            <li>Read-only: nothing is installed or run</li>
            <li>Same input, same score</li>
          </ul>
        </div>

        <figure
          className="rounded-xl border border-white/15 bg-[#000814]/80 p-5 font-mono text-sm shadow-2xl backdrop-blur"
          aria-label="Example scan: a real package passes, an invented package is blocked"
        >
          <figcaption className="mb-4 font-sans text-xs text-white/55">Example scan</figcaption>

          <p className="sg-line break-all text-cyan-200" style={{ animationDelay: "300ms" }}>
            $ pip install requests slopguard-demo-phantom-pkg-93817
          </p>

          <div className="sg-line mt-5 flex items-center justify-between gap-4 border-t border-white/10 pt-4" style={{ animationDelay: "1000ms" }}>
            <span>requests</span>
            <span className="flex items-center gap-3 whitespace-nowrap">
              <span className="text-white/55">Risk 0/100</span>
              <span className="rounded bg-emerald-400/15 px-2 py-0.5 font-semibold text-emerald-300">OK</span>
            </span>
          </div>

          <div className="sg-line mt-4 border-t border-white/10 pt-4" style={{ animationDelay: "1700ms" }}>
            <div className="flex items-start justify-between gap-4">
              <span className="break-all">slopguard-demo-phantom-pkg-93817</span>
              <span className="flex items-center gap-3 whitespace-nowrap">
                <span className="text-white/55">Risk 100/100</span>
                <span className="rounded bg-red-500/20 px-2 py-0.5 font-semibold text-red-300">BLOCK</span>
              </span>
            </div>
            <p className="mt-2 font-sans text-white/75">
              Not found on PyPI. An AI may have invented this name, and an attacker could register it.
            </p>
          </div>

          <p className="sg-line mt-5 font-sans text-xs text-white/55" style={{ animationDelay: "2400ms" }}>
            Nothing was installed.
          </p>
        </figure>
      </div>
    </section>
  );
}