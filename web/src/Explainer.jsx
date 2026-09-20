import { useEffect, useState } from "react";
import "./Explainer.css";

const STEPS = [
  {
    title: "You ask an AI for code",
    text: "You ask an AI assistant to write a small program. It answers with code and an install command.",
  },
  {
    title: "The AI invents a package name",
    text: "Sometimes the AI makes up a package that does not exist. Researchers found that the same fake names come back again and again.",
  },
  {
    title: "An attacker registers the fake name",
    text: "Anyone can publish a package. An attacker registers the invented name and hides malware inside it. This is called slopsquatting.",
  },
  {
    title: "You run pip install",
    text: "The install command now downloads the attacker's package, and its code runs on your computer.",
  },
  {
    title: "SlopGuard checks before you install",
    text: "Paste the AI's answer into SlopGuard. It looks the package up, sees that it is missing, brand new or suspicious, and shows BLOCK before anything is installed.",
  },
];

function Scene({ step }) {
  if (step === 0) {
    return (
      <svg viewBox="0 0 360 160" role="img" aria-label="A chat where a user asks an AI to write code">
        <rect x="10" y="12" width="210" height="34" rx="10" className="sg-soft" />
        <text x="22" y="34" className="sg-t">Write code to parse JSON fast</text>
        <rect x="70" y="62" width="280" height="88" rx="10" className="sg-soft" />
        <text x="84" y="86" className="sg-mono">import fastjson_utils</text>
        <text x="84" y="108" className="sg-mono">pip install fastjson-utils-pro</text>
        <text x="84" y="134" className="sg-t sg-dim">AI answer</text>
      </svg>
    );
  }
  if (step === 1) {
    return (
      <svg viewBox="0 0 360 160" role="img" aria-label="The AI answer contains a package name that does not exist">
        <rect x="10" y="20" width="340" height="50" rx="10" className="sg-soft" />
        <text x="24" y="50" className="sg-mono">pip install fastjson-utils-pro</text>
        <rect x="10" y="90" width="340" height="52" rx="10" className="sg-bad" />
        <text x="24" y="114" className="sg-t sg-badtxt">? This package does not exist on PyPI</text>
        <text x="24" y="132" className="sg-t sg-dim">The AI made the name up.</text>
      </svg>
    );
  }
  if (step === 2) {
    return (
      <svg viewBox="0 0 360 160" role="img" aria-label="An attacker publishes a malicious package under the invented name">
        <rect x="10" y="10" width="150" height="140" rx="10" className="sg-soft" />
        <text x="24" y="34" className="sg-t">Attacker</text>
        <text x="24" y="58" className="sg-t sg-dim">Sees the fake name</text>
        <text x="24" y="78" className="sg-t sg-dim">and registers it</text>
        <text x="24" y="120" className="sg-t sg-badtxt">+ hidden malware</text>
        <path d="M168 80 L196 80" className="sg-arrow" />
        <rect x="204" y="10" width="146" height="140" rx="10" className="sg-soft" />
        <text x="216" y="34" className="sg-t">Public registry</text>
        <rect x="216" y="50" width="122" height="34" rx="8" className="sg-bad" />
        <text x="224" y="72" className="sg-mono">fastjson-utils-pro</text>
        <text x="216" y="112" className="sg-t sg-dim">Now it exists.</text>
      </svg>
    );
  }
  if (step === 3) {
    return (
      <svg viewBox="0 0 360 160" role="img" aria-label="A terminal installs the malicious package and the malware runs">
        <rect x="10" y="10" width="340" height="140" rx="10" className="sg-term" />
        <text x="24" y="38" className="sg-mono sg-termtxt">$ pip install fastjson-utils-pro</text>
        <text x="24" y="62" className="sg-mono sg-termtxt sg-dim">Downloading fastjson-utils-pro...</text>
        <text x="24" y="86" className="sg-mono sg-termtxt sg-dim">Installing collected packages...</text>
        <text x="24" y="118" className="sg-mono sg-danger">Attacker code is now running.</text>
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 360 160" role="img" aria-label="SlopGuard shows BLOCK for the fake package before install">
      <rect x="10" y="10" width="340" height="140" rx="10" className="sg-soft" />
      <text x="24" y="38" className="sg-mono">fastjson-utils-pro</text>
      <rect x="24" y="52" width="76" height="28" rx="14" className="sg-badge" />
      <text x="40" y="71" className="sg-t sg-badgetxt">BLOCK</text>
      <text x="112" y="71" className="sg-t">Risk 100/100</text>
      <text x="24" y="104" className="sg-t sg-dim">Not on the registry. Do not install it.</text>
      <text x="24" y="128" className="sg-t sg-ok">Checked before you installed.</text>
    </svg>
  );
}

export default function Explainer({ onTry }) {
  const reduce =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(!reduce);
  const last = i === STEPS.length - 1;

  useEffect(() => {
    if (!playing) return undefined;
    const id = setTimeout(() => {
      if (last) setPlaying(false);
      else setI((n) => n + 1);
    }, 5000);
    return () => clearTimeout(id);
  }, [playing, i, last]);

  const go = (n) => {
    setPlaying(false);
    setI(Math.max(0, Math.min(STEPS.length - 1, n)));
  };

  return (
    <section className="sg-explainer" aria-labelledby="sg-ex-title">
      <h2 id="sg-ex-title">How slopsquatting works</h2>
      <p className="sg-sub">Five steps, no jargon.</p>

      <ol className="sg-dots">
        {STEPS.map((s, n) => (
          <li key={s.title}>
            <button
              type="button"
              onClick={() => go(n)}
              aria-label={"Step " + (n + 1) + ": " + s.title}
              aria-current={n === i ? "step" : undefined}
              className={n === i ? "on" : ""}
            >
              {n + 1}
            </button>
          </li>
        ))}
      </ol>

      <div key={i} className="sg-scene">
        <Scene step={i} />
      </div>

      <div className="sg-copy" aria-live="polite">
        <h3>{i + 1}. {STEPS[i].title}</h3>
        <p>{STEPS[i].text}</p>
      </div>

      <div className="sg-controls">
        <button type="button" onClick={() => go(i - 1)} disabled={i === 0}>Back</button>
        <button type="button" onClick={() => setPlaying((p) => !p)} disabled={last && !playing && false}>
          {playing ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={() => go(i + 1)} disabled={last}>Next</button>
        {last && typeof onTry === "function" && (
          <button type="button" className="sg-primary" onClick={onTry}>Try it in the scanner</button>
        )}
      </div>

      <p className="sg-honest">
        Slopsquatting has been demonstrated by security researchers. We are not claiming it is happening everywhere.
      </p>
    </section>
  );
}
