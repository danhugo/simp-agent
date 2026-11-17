import { useCallback, useEffect, useMemo, useState } from "react";
import { api, AuthError, type Persona as P } from "./api";
import { ModelPicker } from "./App";
import { errorText } from "./Chat";
import { Mascot3D } from "./Mascot3D";
import { compileSkin, setSkin, type Wear } from "./skin";

const FIX_TRIES = 2;  // the model gets the error back this many times before we show it
const IDEAS = ["a grumpy pirate captain", "a sleepy wizard", "a cheerful chef", "a cowboy in denim shorts"];

/** Persona: describe a character, a model writes Simp's personality and its outfit code; preview, then save. */
export function Persona({ onError, menuButton, profiles, models }: {
  onError: (e: unknown) => void; menuButton: React.ReactNode; profiles: string[]; models: Record<string, string>;
}) {
  const [saved, setSaved] = useState<P | null>(null);
  const [draft, setDraft] = useState<P>({});
  const [profile, setProfile] = useState("");
  const [busy, setBusy] = useState("");    // what is running, for the status line
  const [error, setError] = useState("");  // last code error (compile, check or draw)
  const [codeOpen, setCodeOpen] = useState(false);
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);

  useEffect(() => {
    api.persona().then((p) => { setSaved(p); setDraft(p); if (p.profile) setProfile(p.profile); }, fail);
  }, [fail]);
  useEffect(() => { if (!profile && profiles.length) setProfile(profiles[0]); }, [profiles, profile]);

  // the draft's outfit, compiled; a bad one shows its error and no outfit
  const compiled = useMemo((): { wear: Wear | null; err: string } => {
    if (!draft.code) return { wear: null, err: "" };
    try { return { wear: compileSkin(draft.code), err: "" }; } catch (e) { return { wear: null, err: (e as Error).message }; }
  }, [draft.code]);
  useEffect(() => setError(compiled.err), [compiled]);

  const generate = async (fixing?: { code: string; error: string }) => {
    const description = draft.description?.trim();
    if (!description || !profile) return;
    setError("");
    let req = { description, profile, ...fixing };
    try {
      for (let i = 0; ; i++) {
        setBusy(i || fixing ? `Fixing the outfit code (try ${i + 1})…` : "Designing…");
        const out = await api.generatePersona(req);
        try {
          compileSkin(out.code ?? "");
          setDraft((d) => ({ ...d, ...out, profile }));
          return;
        } catch (e) {
          if (i >= FIX_TRIES) { setDraft((d) => ({ ...d, ...out, profile })); return; }  // show it with its error
          req = { description, profile, code: out.code ?? "", error: (e as Error).message };
        }
      }
    } catch (e) { fail(e); } finally { setBusy(""); }
  };

  const save = async () => {
    try {
      await api.savePersona({ ...draft, profile });
      setSaved({ ...draft, profile });
      setSkin(compiled.wear);
    } catch (e) { fail(e); }
  };
  const reset = async () => {
    try { await api.savePersona({}); setSaved({}); setDraft({}); setSkin(null); } catch (e) { fail(e); }
  };
  const norm = (x: P) => JSON.stringify([x.name ?? "", x.description ?? "", x.instruction ?? "", x.code ?? ""]);
  const dirty = saved !== null && norm(saved) !== norm(draft);

  return (
    <main className="memory persona">
      <header className="home-head">{menuButton}</header>
      <div className="memory-body">
        <h1 className="page-title">Persona</h1>
        <p className="muted small">Describe a character. The model writes Simp's personality and the code for its outfit, drawn in Simp's pixel 3D style.</p>
        <div className="persona-grid">
          <section className="persona-stage" aria-label="Preview">
            <Mascot3D size={240} pixels={56} skin={compiled.wear} working={!!busy}
              onSkinError={(m) => setError(m)} />
            {draft.name && <p className="persona-name">{draft.name}</p>}
          </section>
          <section className="persona-form">
            <label className="persona-label" htmlFor="persona-desc">Character</label>
            <textarea id="persona-desc" rows={3} maxLength={1000} value={draft.description ?? ""} disabled={!!busy}
              placeholder="e.g. a sleepy wizard who loves tea, purple pointy hat with stars"
              onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) generate(); }} />
            {!draft.description && (
              <div className="persona-ideas">
                {IDEAS.map((t) => <button key={t} className="suggestion" onClick={() => setDraft((d) => ({ ...d, description: t }))}>{t}</button>)}
              </div>
            )}
            <div className="row persona-actions">
              {profiles.length > 0 && <ModelPicker value={profile} options={profiles} labels={models} onChange={setProfile} />}
              <span className="spacer" />
              <button className="primary" disabled={!!busy || !draft.description?.trim() || !profile} onClick={() => generate()}>
                {draft.code ? "Regenerate" : "Generate"}</button>
            </div>
            {busy && <p className="muted small" role="status">{busy}</p>}
            {error && !busy && (
              <div className="error persona-err" role="alert">
                <span>Outfit code error: {error}</span>
                {draft.code && <button className="ghost" onClick={() => generate({ code: draft.code!, error })}>Ask the model to fix it</button>}
              </div>
            )}

            {(draft.instruction || draft.code) && <>
              <label className="persona-label" htmlFor="persona-name">Name</label>
              <input id="persona-name" maxLength={24} value={draft.name ?? ""} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
              <label className="persona-label" htmlFor="persona-inst">Personality <span className="muted small">(tone only: it never changes what Simp may do)</span></label>
              <textarea id="persona-inst" rows={4} maxLength={800} value={draft.instruction ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, instruction: e.target.value }))} />
              <details open={codeOpen} onToggle={(e) => setCodeOpen((e.target as HTMLDetailsElement).open)}>
                <summary className="persona-label">Outfit code</summary>
                <textarea className="persona-code" rows={14} spellCheck={false} value={draft.code ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, code: e.target.value }))} aria-label="Outfit code" />
              </details>
            </>}
            <div className="row persona-actions">
              <button className="primary" disabled={!dirty || !!busy || !!compiled.err} onClick={save}>Save persona</button>
              {saved && (saved.code || saved.instruction) && <button className="ghost" onClick={reset}>Back to plain Simp</button>}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

/** At start: wear the saved outfit everywhere (a broken one is skipped). */
export async function loadSavedSkin() {
  try {
    const p = await api.persona();
    setSkin(p.code ? compileSkin(p.code) : null);
  } catch { /* no outfit */ }
}
