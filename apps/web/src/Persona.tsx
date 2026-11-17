import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AuthError, type Persona as P } from "./api";
import { ModelPicker } from "./App";
import { errorText } from "./Chat";
import { IconCheck } from "./icons";
import { Mascot3D, readPal, render } from "./Mascot3D";
import { combine, compileSkin, item, setSkin, type Slot, type Wear } from "./skin";

const SLOTS: { slot: Slot; label: string }[] = [{ slot: "hat", label: "Hat" }, { slot: "bottom", label: "Pants / skirt" }];
const FIX_TRIES = 3;  // the model gets the check's error (with what it measured) back this many times
const IDEAS = ["a grumpy pirate captain", "a sleepy wizard", "a cheerful chef", "a cowboy in denim shorts"];

type Step = { state: "waiting" | "designing" | "checking" | "fixing" | "done" | "failed"; note?: string; tries?: number };
const STATE_TEXT: Record<Step["state"], string> = {
  waiting: "Waiting", designing: "Designing…", checking: "Checking…", fixing: "Fixing…", done: "Done", failed: "Failed",
};

/** A slot's code as a standalone object (checked + baked into its own grid), or its error. */
function tryCompile(code: string | undefined, slot: Slot): { wear: Wear | null; err: string } {
  if (!code) return { wear: null, err: "" };
  try { return { wear: item(code, slot), err: "" }; } catch (e) { return { wear: null, err: (e as Error).message }; }
}
const check = (code: string, slot: Slot) => { try { compileSkin(code, slot); return ""; } catch (e) { return (e as Error).message; } };

/** value, but only after it stopped changing for ms (hand edits in a code box rebake once, not per keystroke) */
function useSettled<T>(value: T, ms = 500): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/** One outfit object on its own (no head), slowly turning, in the same pixel style. */
function ItemView({ wear, label }: { wear: Wear; label: string }) {
  const cv = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = cv.current?.getContext("2d");
    if (!ctx) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches, pal = readPal(), N = 64;
    // frame the object itself: centered on its box, zoomed so its widest extent fits while it turns
    const b = wear.boxes!, lo = [0, 1, 2].map((k) => Math.min(...b.map((x) => x.lo[k]))), hi = [0, 1, 2].map((k) => Math.max(...b.map((x) => x.hi[k])));
    const cy = (lo[1] + hi[1]) / 2, half = Math.max(hi[1] - lo[1], Math.hypot(hi[0] - lo[0], hi[2] - lo[2])) / 2, view = Math.min(2, half * 1.15);
    let raf = 0, last = -1;
    const frame = (t: number) => {
      const yaw = reduce ? 0.5 : Math.round((t / 1000) * 0.8 * 40) / 40;  // turn in small steps: re-render ~20x/s
      if (yaw !== last) { last = yaw; render(ctx, N, pal, yaw, 0.35, 0, 0, 0, {}, wear, true, view, cy); }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [wear]);
  return (
    <figure className="persona-item">
      <canvas ref={cv} width={64} height={64} aria-hidden="true" />
      <figcaption className="muted small">{label}</figcaption>
    </figure>
  );
}

/** Persona: the user writes the personality; a model draws the outfit one slot at a time (hat, then bottom). */
export function Persona({ onError, menuButton, profiles, models }: {
  onError: (e: unknown) => void; menuButton: React.ReactNode; profiles: string[]; models: Record<string, string>;
}) {
  const [saved, setSaved] = useState<P | null>(null);
  const [draft, setDraft] = useState<P>({});
  const [profile, setProfile] = useState("");
  const [steps, setSteps] = useState<Partial<Record<Slot, Step>>>({});
  const [error, setError] = useState("");
  const busy = Object.values(steps).some((s) => s && !["done", "failed"].includes(s.state));
  const stop = useRef(false);
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);

  useEffect(() => {
    api.persona().then((p) => { setSaved(p); setDraft(p); if (p.profile) setProfile(p.profile); }, fail);
  }, [fail]);
  useEffect(() => { if (!profile && profiles.length) setProfile(profiles[0]); }, [profiles, profile]);
  useEffect(() => () => { stop.current = true; }, []);

  // each slot is its own object (baked alone); "assemble" then merges them into one grid Simp wears
  const hatCode = useSettled(draft.hat), bottomCode = useSettled(draft.bottom);
  const hat = useMemo(() => tryCompile(hatCode, "hat"), [hatCode]);
  const bottom = useMemo(() => tryCompile(bottomCode, "bottom"), [bottomCode]);
  const compiled = { hat, bottom };
  const [wear, setWear] = useState<Wear | null>(null);
  const [assembling, setAssembling] = useState(false);
  useEffect(() => {
    setAssembling(true);
    const t = setTimeout(() => { { const w = combine([hat.wear, bottom.wear]); setWear(() => w); }; setAssembling(false); }, 30);  // let "Assembling…" paint
    return () => clearTimeout(t);
  }, [hat.wear, bottom.wear]);

  const setStep = (slot: Slot, s: Step) => setSteps((x) => ({ ...x, [slot]: s }));

  /** Design one slot: ask, check in the page, send problems back, until it passes or tries run out. */
  const design = async (slot: Slot, other: string): Promise<string> => {
    const description = draft.description!.trim();
    let req: { code?: string; error?: string } = {};
    let last = "";
    for (let i = 0; i <= FIX_TRIES && !stop.current; i++) {
      setStep(slot, { state: i ? "fixing" : "designing", tries: i, note: req.error });
      const { code } = await api.generatePersona({ description, profile, slot, other, ...req });
      last = code ?? "";
      setDraft((d) => ({ ...d, [slot]: last }));  // show every attempt in the preview, good or not
      setStep(slot, { state: "checking", tries: i });
      const err = check(last, slot);
      if (!err) { setStep(slot, { state: "done", tries: i }); return last; }
      req = { code: last, error: err };
    }
    setStep(slot, { state: "failed", note: req.error });
    return last;
  };

  const generate = async (only?: Slot) => {
    if (!draft.description?.trim() || !profile) return;
    setError("");
    stop.current = false;
    const todo = only ? [only] : SLOTS.map((s) => s.slot);
    setSteps((x) => ({ ...x, ...Object.fromEntries(todo.map((s) => [s, { state: "waiting" } as Step])) }));
    try {
      let hatCode = only === "bottom" ? draft.hat ?? "" : "";
      for (const slot of todo) {  // one after the other: the bottom sees the hat, to match it
        const code = await design(slot, slot === "bottom" ? hatCode : only === "hat" ? draft.bottom ?? "" : "");
        if (slot === "hat") hatCode = code;
      }
    } catch (e) {
      fail(e);
      setSteps((x) => Object.fromEntries(Object.entries(x).map(([k, s]) => [k, s && !["done", "failed"].includes(s.state) ? { state: "failed", note: errorText(e) } : s])));
    }
  };

  const save = async () => {
    try {
      const p = { ...draft, profile };
      await api.savePersona(p);
      setSaved(p);
      setSkin(wear);
    } catch (e) { fail(e); }
  };
  const reset = async () => {
    try { await api.savePersona({}); setSaved({}); setDraft({}); setSteps({}); setSkin(null); } catch (e) { fail(e); }
  };
  const norm = (x: P) => JSON.stringify([x.name ?? "", x.description ?? "", x.instruction ?? "", x.hat ?? "", x.bottom ?? ""]);
  const dirty = saved !== null && norm(saved) !== norm(draft);
  const set = (k: keyof P) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  return (
    <main className="memory persona">
      <header className="home-head">{menuButton}</header>
      <div className="memory-body">
        <h1 className="page-title">Persona</h1>
        <p className="muted small">Give Simp a name and a personality, then describe a look: a model designs the hat, then the pants, in Simp's pixel 3D style.</p>
        <div className="persona-grid">
          <section className="persona-stage" aria-label="Preview">
            <Mascot3D size={240} pixels={56} skin={wear} working={busy} onSkinError={(m) => setError(m)} />
            {draft.name && <p className="persona-name">{draft.name}</p>}
            {(hat.wear || bottom.wear) && (
              <div className="persona-items" aria-label="Outfit objects">
                {hat.wear && <ItemView wear={hat.wear} label="Hat" />}
                {bottom.wear && <ItemView wear={bottom.wear} label="Pants / skirt" />}
              </div>
            )}
            {(hat.wear || bottom.wear) && (
              <p className="muted small persona-assembled" role="status">
                {assembling ? "Assembling into one object…" : wear?.grid ? `Assembled: one ${wear.grid.join("×")} grid` : ""}
              </p>
            )}
          </section>
          <section className="persona-form">
            <label className="persona-label" htmlFor="persona-name">Name</label>
            <input id="persona-name" maxLength={24} value={draft.name ?? ""} onChange={set("name")} placeholder="Simp" />
            <label className="persona-label" htmlFor="persona-inst">Personality <span className="muted small">(tone only: it never changes what Simp may do)</span></label>
            <textarea id="persona-inst" rows={3} maxLength={800} value={draft.instruction ?? ""} onChange={set("instruction")}
              placeholder="e.g. You talk like a sleepy old wizard: slow, cozy, a little forgetful." />

            <label className="persona-label" htmlFor="persona-desc">Look</label>
            <textarea id="persona-desc" rows={2} maxLength={1000} value={draft.description ?? ""} disabled={busy} onChange={set("description")}
              placeholder="e.g. purple pointy wizard hat with yellow stars, blue skirt"
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) generate(); }} />
            {!draft.description && (
              <div className="persona-ideas">
                {IDEAS.map((t) => <button key={t} className="suggestion" onClick={() => setDraft((d) => ({ ...d, description: t }))}>{t}</button>)}
              </div>
            )}
            <div className="row persona-actions">
              {profiles.length > 0 && <ModelPicker value={profile} options={profiles} labels={models} onChange={setProfile} />}
              <span className="spacer" />
              {busy ? <button className="ghost" onClick={() => { stop.current = true; }}>Stop</button>
                : <button className="primary" disabled={!draft.description?.trim() || !profile} onClick={() => generate()}>
                    {draft.hat || draft.bottom ? "Redesign outfit" : "Design outfit"}</button>}
            </div>
            {error && <p className="error" role="alert">{error}</p>}

            <ol className="persona-steps" aria-label="Outfit">
              {SLOTS.map(({ slot, label }) => {
                const st = steps[slot], c = compiled[slot], code = draft[slot];
                const state = st?.state ?? (code ? (c.err ? "failed" : "done") : undefined);
                return (
                  <li key={slot} className={`persona-step ${state ?? "empty"}`}>
                    <div className="persona-step-head">
                      <span className="persona-dot" aria-hidden="true">{state === "done" ? <IconCheck size={14} /> : null}</span>
                      <b>{label}</b>
                      <span className="muted small" role="status">
                        {state ? STATE_TEXT[state] : "Not designed"}{st?.tries ? ` (fix ${st.tries}/${FIX_TRIES})` : ""}
                      </span>
                      <span className="spacer" />
                      {!busy && draft.description?.trim() && <button className="ghost small" onClick={() => generate(slot)}>{code ? "Redo" : "Design"}</button>}
                      {!busy && code && <button className="ghost small" onClick={() => { setDraft((d) => ({ ...d, [slot]: "" })); setSteps((x) => ({ ...x, [slot]: undefined })); }}>Remove</button>}
                    </div>
                    {(st?.note || (state === "failed" && c.err)) && <p className="persona-note small">{st?.state === "failed" || !st ? "Problem: " : "Fixing: "}{st?.note || c.err}</p>}
                    {code && (
                      <details>
                        <summary className="muted small">Code</summary>
                        <textarea className="persona-code" rows={10} spellCheck={false} value={code} onChange={set(slot)} aria-label={`${label} code`} />
                        {!busy && c.err && <button className="ghost small" onClick={() => generate(slot)}>Ask the model to fix it</button>}
                      </details>
                    )}
                  </li>
                );
              })}
            </ol>

            <div className="row persona-actions">
              <button className="primary" disabled={!dirty || busy || assembling || !!hat.err || !!bottom.err} onClick={save}>Save persona</button>
              {saved && (saved.hat || saved.bottom || saved.instruction) && <button className="ghost" onClick={reset}>Back to plain Simp</button>}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

/** At start: wear the saved outfit everywhere (a broken slot is skipped). */
export async function loadSavedSkin() {
  try {
    const p = await api.persona();
    setSkin(combine([tryCompile(p.hat, "hat").wear, tryCompile(p.bottom, "bottom").wear]));
  } catch { /* no outfit */ }
}
