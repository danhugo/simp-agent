import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AuthError, type Persona as P } from "./api";
import { ModelPicker } from "./App";
import { errorText } from "./Chat";
import { IconCheck } from "./icons";
import { Mascot3D } from "./Mascot3D";
import { combine, compileSkin, setSkin, type Slot, type Wear } from "./skin";

const SLOTS: { slot: Slot; label: string }[] = [{ slot: "hat", label: "Hat" }, { slot: "bottom", label: "Pants / skirt" }];
const FIX_TRIES = 3;  // the model gets the check's error (with what it measured) back this many times
const IDEAS = ["a grumpy pirate captain", "a sleepy wizard", "a cheerful chef", "a cowboy in denim shorts"];

type Step = { state: "waiting" | "designing" | "checking" | "fixing" | "done" | "failed"; note?: string; tries?: number };
const STATE_TEXT: Record<Step["state"], string> = {
  waiting: "Waiting", designing: "Designing…", checking: "Checking…", fixing: "Fixing…", done: "Done", failed: "Failed",
};

function tryCompile(code: string | undefined, slot: Slot): { wear: Wear | null; err: string } {
  if (!code) return { wear: null, err: "" };
  try { return { wear: compileSkin(code, slot), err: "" }; } catch (e) { return { wear: null, err: (e as Error).message }; }
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

  const hat = useMemo(() => tryCompile(draft.hat, "hat"), [draft.hat]);
  const bottom = useMemo(() => tryCompile(draft.bottom, "bottom"), [draft.bottom]);
  const compiled = { hat, bottom };
  const wear = useMemo(() => combine([hat.wear, bottom.wear]), [hat.wear, bottom.wear]);

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
      const { err } = tryCompile(last, slot);
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
              <button className="primary" disabled={!dirty || busy || !!hat.err || !!bottom.err} onClick={save}>Save persona</button>
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
