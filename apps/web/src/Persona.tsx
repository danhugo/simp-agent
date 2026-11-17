import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AuthError, type Outfit, type Persona as P } from "./api";
import { ModelPicker } from "./App";
import { errorText } from "./Chat";
import { IconBookmark, IconBookmarked, IconCheck, IconRedo, IconStop, IconTrash, IconWand, IconX } from "./icons";
import { Mascot3D, readPal, render, SKIN_VIEW } from "./Mascot3D";
import { combine, compileSkin, getSkin, item, setSkin, type Slot, type Wear } from "./skin";

const SLOTS: { slot: Slot; label: string }[] = [{ slot: "hat", label: "Hat" }, { slot: "bottom", label: "Bottom" }];
const FIX_TRIES = 3;  // the model gets the check's error (with what it measured) back this many times
const IDEAS = ["a grumpy pirate captain", "a sleepy wizard", "a cheerful chef", "a cowboy in denim shorts"];

type Step = { state: "waiting" | "designing" | "checking" | "fixing" | "done" | "failed"; note?: string; tries?: number };

/** A slot's code as a standalone object (checked + baked into its own grid), or its error. */
function tryCompile(code: string | undefined, slot: Slot): { wear: Wear | null; err: string } {
  if (!code) return { wear: null, err: "" };
  try { return { wear: item(code, slot), err: "" }; } catch (e) { return { wear: null, err: (e as Error).message }; }
}
const check = (code: string, slot: Slot) => { try { compileSkin(code, slot); return ""; } catch (e) { return (e as Error).message; } };

/** value, but only after it stopped changing for ms (hand edits in a code box rebake once, not per keystroke) */
function useSettled<T>(value: T, ms = 500): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    if (!v || !value) { setV(value); return; }  // appearing or clearing: at once; only edits to existing code wait
    const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t);
  }, [value, ms]);  // eslint-disable-line react-hooks/exhaustive-deps
  return v;
}

/** Camera for one piece shown alone: centered on its box, zoomed so it fills the frame while turning. */
function framing(wear: Wear): { view: number; cy: number } {
  const b = wear.boxes!, lo = [0, 1, 2].map((k) => Math.min(...b.map((x) => x.lo[k]))), hi = [0, 1, 2].map((k) => Math.max(...b.map((x) => x.hi[k])));
  // boxes carry 0.2 of padding per side (for safe marching): take it off to frame what is really drawn
  const pad = 0.18, w = Math.max(...[0, 2].map((k) => Math.max(Math.abs(lo[k] + pad), Math.abs(hi[k] - pad)))), h = (hi[1] - lo[1]) / 2 - pad;
  return { cy: (lo[1] + hi[1]) / 2, view: Math.max(0.35, Math.min(2, Math.max(w, h) * 1.08)) };  // w: the farthest it reaches while turning
}
const MAX_OUTFITS = 10;  // per kind (outfits, hats, bottoms); matches the server
const KINDS = [["all", "All"], ["outfit", "Outfits"], ["hat", "Hats"], ["bottom", "Bottoms"]] as const;
const NOUN: Record<Slot, string> = { hat: "hat", bottom: "bottom" };
/** faint outline of what goes in an empty slot */
function SlotShape({ slot }: { slot: Slot }) {
  return (
    <svg width="48" height="40" viewBox="0 0 48 40" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
      {slot === "hat" ? <><path d="M14 26c0-9 4.5-16 10-16s10 7 10 16" /><path d="M6 27c4 3 32 3 36 0" /></>
        : <path d="M15 8h18l7 24c-10 3-22 3-32 0z" />}
    </svg>
  );
}
const KIND_ONE: Record<Outfit["kind"], string> = { outfit: "Outfit", hat: "Hat", bottom: "Bottom" };
const sameAs = (o: Outfit, d: P) => o.kind === "hat" ? o.hat === (d.hat ?? "") : o.kind === "bottom" ? o.bottom === (d.bottom ?? "")
  : o.hat === (d.hat ?? "") && o.bottom === (d.bottom ?? "");

/** A collection card's picture: Simp wearing that outfit, drawn once (no animation, baked lazily when visible). */
function OutfitThumb({ o }: { o: Outfit }) {
  const cv = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = cv.current, ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    const draw = () => {
      if (o.kind === "hat" || o.kind === "bottom") {  // a single piece: shown alone, like on the stage
        const w = tryCompile(o.kind === "hat" ? o.hat : o.bottom, o.kind).wear;
        if (w) { const f = framing(w); render(ctx, 96, readPal(), 0.5, 0.35, 0, 0, 0, {}, w, true, f.view, f.cy); }
        return;
      }
      const w = combine([tryCompile(o.hat, "hat").wear, tryCompile(o.bottom, "bottom").wear]);
      render(ctx, 96, readPal(), 0.35, 0.15, 0, 0, 0, {}, w);
    };
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); setTimeout(draw, 0); } });
    io.observe(c);
    return () => io.disconnect();
  }, [o]);
  return <canvas ref={cv} width={96} height={96} aria-hidden="true" />;
}

/** One outfit object on its own (no head), slowly turning, in the same pixel style. */
function ItemView({ wear }: { wear: Wear }) {
  const cv = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = cv.current?.getContext("2d");
    if (!ctx) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches, pal = readPal(), N = 64;
    // frame the object itself: centered on its box, zoomed so its widest extent fits while it turns
    const { view, cy } = framing(wear);
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
    <canvas className="persona-item" ref={cv} width={64} height={64} aria-hidden="true" />
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
  const abort = useRef<AbortController | null>(null);
  const stopNow = () => abort.current?.abort();
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);

  useEffect(() => {
    api.persona().then((p) => { setSaved(p); setDraft(p); if (p.profile) setProfile(p.profile); }, fail);
  }, [fail]);
  useEffect(() => { if (!profile && profiles.length) setProfile(profiles[0]); }, [profiles, profile]);
  useEffect(() => () => abort.current?.abort(), []);

  // each slot is its own object (baked alone); "assemble" then merges them into one grid Simp wears
  // removing a piece shows at once; only edits to existing code wait to settle
  const hatSettled = useSettled(draft.hat), bottomSettled = useSettled(draft.bottom);
  const hatCode = draft.hat ? hatSettled : "", bottomCode = draft.bottom ? bottomSettled : "";
  const hat = useMemo(() => tryCompile(hatCode, "hat"), [hatCode]);
  const bottom = useMemo(() => tryCompile(bottomCode, "bottom"), [bottomCode]);
  const compiled = { hat, bottom };
  const [wear, setWear] = useState<Wear | null>(null);
  const [assembling, setAssembling] = useState(false);
  const shown = saved === null || (!wear && assembling && (draft.hat || draft.bottom)) ? getSkin() : wear;  // until the persona loads: what Simp already wears in the app
  useEffect(() => {
    setAssembling(true);
    const t = setTimeout(() => { { const w = combine([hat.wear, bottom.wear]); setWear(() => w); }; setAssembling(false); }, 30);  // let "Assembling…" paint
    return () => clearTimeout(t);
  }, [hat.wear, bottom.wear]);

  // the collection: saved outfits to pick from
  const [outfits, setOutfits] = useState<Outfit[] | null>(null);
  const [confirmDel, setConfirmDel] = useState("");
  useEffect(() => { api.outfits().then(setOutfits, fail); }, [fail]);
  const [kind, setKind] = useState<(typeof KINDS)[number][0]>("all");
  const [drawer, setDrawer] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const openDrawer = (k: (typeof KINDS)[number][0]) => { setPicker(null); setFullNote(null); setKind(k); setDrawer(true); };
  // quick picker on a piece card: saved pieces of that slot (alone or from a saved outfit), one per distinct code
  const [picker, setPicker] = useState<Slot | null>(null);
  const pieces = (slot: Slot): Outfit[] => {
    const seen = new Set<string>();
    return (outfits ?? []).filter((o) => (o.kind === slot || o.kind === "outfit") && o[slot]).filter((o) => !seen.has(o[slot]!) && !!seen.add(o[slot]!))
      .map((o) => ({ ...o, kind: slot, hat: slot === "hat" ? o.hat : "", bottom: slot === "bottom" ? o.bottom : "" }));
  };
  useEffect(() => {
    if (!picker) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !(e.target as Element).closest?.(".persona-picker, .persona-piece-pic")) setPicker(null);
    };
    addEventListener("keydown", close); addEventListener("pointerdown", close);
    return () => { removeEventListener("keydown", close); removeEventListener("pointerdown", close); };
  }, [picker]);
  useEffect(() => {
    if (!drawer) return;
    closeRef.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); };
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [drawer]);
  const has = (k: Outfit["kind"]) => !!outfits?.some((o) => o.kind === k && sameAs(o, draft));
  const inCollection = has("outfit");
  const count = (k: Outfit["kind"]) => (outfits ?? []).filter((o) => o.kind === k).length;
  const full = (k: Outfit["kind"]) => count(k) >= MAX_OUTFITS;
  // a piece that can't be saved because its kind is full: the drawer opens on that kind and says why
  const [fullNote, setFullNote] = useState<Slot | null>(null);
  useEffect(() => { if (fullNote && !full(fullNote)) setFullNote(null); });  // room was made: drop the note
  /** save the whole outfit, or one piece of it (hat / bottom) on its own */
  const keep = async (k: Outfit["kind"] = "outfit") => {
    try {
      const base = draft.name || draft.description?.slice(0, 30) || "Outfit";
      const o = { kind: k, name: k === "outfit" ? base.slice(0, 40) : `${base.slice(0, 30)} ${k === "hat" ? "hat" : "bottom"}`,
        description: draft.description ?? "", hat: k === "bottom" ? "" : draft.hat ?? "", bottom: k === "hat" ? "" : draft.bottom ?? "" };
      const { id } = await api.addOutfit(o);
      setOutfits((xs) => [{ ...o, id, created: Date.now() / 1000 }, ...(xs ?? [])]);
    } catch (e) { fail(e); }
  };
  // an outfit replaces both slots; a piece replaces only its own, so pieces mix and match
  const wearOutfit = (o: Outfit) => {
    setDraft((d) => o.kind === "hat" ? { ...d, hat: o.hat } : o.kind === "bottom" ? { ...d, bottom: o.bottom }
      : { ...d, description: o.description, hat: o.hat, bottom: o.bottom });
    setSteps((x) => (o.kind === "outfit" ? {} : { ...x, [o.kind]: undefined }));
  };
  const removeOutfit = async (id: string) => {
    if (confirmDel !== id) return setConfirmDel(id);
    setConfirmDel("");
    try { await api.deleteOutfit(id); setOutfits((xs) => (xs ?? []).filter((o) => o.id !== id)); } catch (e) { fail(e); }
  };

  const setStep = (slot: Slot, s: Step) => setSteps((x) => ({ ...x, [slot]: s }));

  /** Design one slot: ask, check in the page, send problems back, until it passes or tries run out. */
  const design = async (slot: Slot, other: string, signal: AbortSignal): Promise<string> => {
    const description = draft.description!.trim();
    let req: { code?: string; error?: string } = {};
    let last = "";
    for (let i = 0; i <= FIX_TRIES; i++) {
      setStep(slot, { state: i ? "fixing" : "designing", tries: i, note: req.error });
      const { code } = await api.generatePersona({ description, profile, slot, other, ...req }, signal);
      if (signal.aborted) throw new DOMException("stopped", "AbortError");
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
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    const todo = only ? [only] : SLOTS.map((s) => s.slot);
    setSteps((x) => ({ ...x, ...Object.fromEntries(todo.map((s) => [s, { state: "waiting" } as Step])) }));
    try {
      let hatCode = only === "bottom" ? draft.hat ?? "" : "";
      for (const slot of todo) {  // one after the other: the bottom sees the hat, to match it
        const code = await design(slot, slot === "bottom" ? hatCode : only === "hat" ? draft.bottom ?? "" : "", ctl.signal);
        if (slot === "hat") hatCode = code;
      }
    } catch (e) {
      if (ctl.signal.aborted) {  // stopped by the user: slots not finished go back to how they were, no error shown
        setSteps((x) => Object.fromEntries(Object.entries(x).map(([k, s]) => [k, s && !["done", "failed"].includes(s.state) ? undefined : s])));
        return;
      }
      fail(e);
      setSteps((x) => Object.fromEntries(Object.entries(x).map(([k, s]) => [k, s && !["done", "failed"].includes(s.state) ? { state: "failed", note: errorText(e) } : s])));
    }
  };

  // the button shows the state: "Saved" while nothing changed, "Save persona" after a change, "Saving…" in between
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const p = { ...draft, profile };
      await api.savePersona(p);
      setSaved(p);
      setSkin(wear);
    } catch (e) { fail(e); }
    setSaving(false);
  };
  // what Simp is (name, personality, outfit pieces); the outfit prompt is only a tool to make pieces, so typing it is not a change
  const norm = (x: P) => JSON.stringify([x.name ?? "", x.instruction ?? "", x.hat ?? "", x.bottom ?? ""]);
  const dirty = saved !== null && norm(saved) !== norm(draft);
  const set = (k: keyof P) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  const canSave = !busy && !assembling && !hat.err && !bottom.err;
  const clearSlot = (slot: Slot) => { setDraft((d) => ({ ...d, [slot]: "" })); setSteps((x) => ({ ...x, [slot]: undefined })); };

  return (
    <main className="memory persona">
      <header className="home-head">{menuButton}</header>
      <div className="memory-body">
        <h1 className="page-title">Persona</h1>
        <div className="persona-lede-row">
          <p className="muted persona-lede">Choose Simp's personality and how it looks.</p>
          <button className={`primary persona-save-btn ${dirty ? "" : "saved"}`} disabled={!dirty || !canSave || saving} onClick={save} aria-live="polite">
            {saving ? "Saving…" : dirty ? "Save persona" : "Saved"}</button>
        </div>
        <div className="persona-grid">
          <div className="persona-side">
          <section className="persona-stage" aria-label="Preview">
            {/* fit backs the camera off SKIN_VIEW times when dressed: bare, draw at 1/SKIN_VIEW the size so the head stays the same */}
            <div className="persona-simp"><Mascot3D size={shown ? 240 : 240 / SKIN_VIEW} pixels={56} fit skin={shown} working={busy} onSkinError={(m) => setError(m)} /></div>
            <p className="persona-name">{draft.name || "Simp"}</p>
            <ul className="persona-items" aria-label="What Simp is wearing">
              {SLOTS.map(({ slot, label }) => {
                const st = steps[slot], c = compiled[slot], code = draft[slot];
                const state = st?.state ?? (code ? (c.err ? "failed" : "done") : undefined);
                const working = !!state && !["done", "failed"].includes(state);
                const note = st?.note || (state === "failed" ? c.err : "");
                return (
                  <li key={slot} className={`persona-piece ${state ?? "empty"}`}>
                    {outfits && <span className={`persona-count ${full(slot) ? "full" : ""}`} title={`${count(slot)} of ${MAX_OUTFITS} ${NOUN[slot]}s saved`}>{count(slot)}/{MAX_OUTFITS}</span>}
                    <button className="ghost persona-piece-pic" disabled={working} aria-label={`Change ${label}`} title="Change from collection"
                      aria-expanded={picker === slot} aria-haspopup="dialog" onClick={() => setPicker((x) => (x === slot ? null : slot))}>
                      {c.wear ? <ItemView wear={c.wear} /> : <span className="persona-piece-empty" aria-hidden="true">{working ? <span className="persona-dot" /> : <SlotShape slot={slot} />}</span>}
                    </button>
                    {picker === slot && (
                      <div className="persona-picker" role="dialog" aria-label={`Choose a ${NOUN[slot]}`}>
                        <button className="ghost persona-picker-design" disabled={busy || !profile} onClick={() => {
                          setPicker(null);
                          if (draft.description?.trim()) generate(slot); else document.getElementById("persona-desc")?.focus();
                        }}>{code ? `Redesign the ${NOUN[slot]}` : `Design a ${NOUN[slot]}`}<span className="muted small">{draft.description?.trim() ? "from your description" : "describe it in Outfit first"}</span></button>
                        <button className="ghost small persona-picker-all" onClick={() => openDrawer(slot)}>See all in collection</button>
                        {pieces(slot).length === 0
                          ? <p className="muted small">Saved {NOUN[slot]}s show up here.</p>
                          : <ul>{pieces(slot).map((o) => {
                              const on = (draft[slot] ?? "") === o[slot];
                              return (
                                <li key={o.id}>
                                  <button className={`ghost ${on ? "on" : ""}`} aria-pressed={on} title={o.name} disabled={busy}
                                    onClick={() => { wearOutfit(o); setPicker(null); }}><OutfitThumb o={o} /></button>
                                </li>
                              );
                            })}</ul>}
                      </div>
                    )}
                    <b className="small persona-piece-label">{label}</b>
                    {working ? <span className="muted small" role="status">{st?.tries ? `Fixing (${st.tries}/${FIX_TRIES})…` : "Drawing…"}</span>
                      : state === "failed" ? <span className="persona-note small" role="status" title={note}>Couldn't draw</span>
                      : !code ? <span className="muted small">No {NOUN[slot]} yet</span> : null}
                    {!busy && (
                      <span className="persona-piece-acts">
                        {code && draft.description?.trim() && <button className="ghost icon" aria-label={`Redo ${label}`} title="Redo" onClick={() => generate(slot)}><IconRedo size={15} /></button>}
                        {code && <button className="ghost icon" aria-label={`Remove ${label}`} title="Remove" onClick={() => clearSlot(slot)}><IconTrash size={15} /></button>}
                        {c.wear && <button className="ghost icon" aria-label={has(slot) ? `${label} saved to collection` : `Save ${label} to collection`}
                          title={has(slot) ? "Saved to collection" : "Save to collection"} aria-pressed={has(slot)} disabled={has(slot)} onClick={() => full(slot) ? (openDrawer(slot), setFullNote(slot)) : keep(slot)}>
                          {has(slot) ? <IconBookmarked size={15} /> : <IconBookmark size={15} />}</button>}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
            <button className="ghost bordered persona-keep" onClick={() => openDrawer("all")} aria-expanded={drawer} aria-controls="persona-drawer">
              Browse collection</button>
          </section>
          </div>

          <div className="persona-form">
            <section aria-labelledby="persona-who" className="persona-part">
              <h2 id="persona-who">Personality</h2>
              <label className="persona-label" htmlFor="persona-name">Name</label>
              <input id="persona-name" maxLength={24} value={draft.name ?? ""} onChange={set("name")} placeholder="Simp" />
              <label className="persona-label" htmlFor="persona-inst">How Simp talks</label>
              <textarea id="persona-inst" rows={3} maxLength={800} value={draft.instruction ?? ""} onChange={set("instruction")} aria-describedby="persona-inst-note"
                placeholder="Like a sleepy old wizard: slow, cozy, a little forgetful." />
              <p id="persona-inst-note" className="muted small persona-note-inline">Only changes the tone. What Simp can do stays the same.</p>
            </section>

            <section aria-labelledby="persona-look" className="persona-part">
              <h2 id="persona-look">Outfit</h2>
              <div className="persona-ideas" aria-label="Ideas">
                {IDEAS.map((t) => <button key={t} className="suggestion" disabled={busy} onClick={() => setDraft((d) => ({ ...d, description: t }))}>{t}</button>)}
              </div>
              <div className="composer persona-composer">
                <div className="composer-card expanded" onClick={(e) => { if (e.target === e.currentTarget) (e.currentTarget.querySelector("textarea") as HTMLTextAreaElement | null)?.focus(); }}>
                  <textarea id="persona-desc" aria-labelledby="persona-look" rows={2} maxLength={1000} value={draft.description ?? ""} disabled={busy} onChange={set("description")}
                    placeholder="A purple pointy wizard hat with yellow stars and a blue skirt"
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); generate(); } }} />
                  <div className="composer-bar">
                    {profiles.length > 0 && <ModelPicker value={profile} options={profiles} labels={models} onChange={setProfile} />}
                    <span className="spacer" />
                    {busy ? <button className="persona-go stop" aria-label="Stop" title="Stop" onClick={stopNow}><IconStop size={16} /></button>
                      : <button className="persona-go" disabled={!draft.description?.trim() || !profile} onClick={() => generate()}
                          aria-label={draft.hat || draft.bottom ? "Redesign outfit" : "Design outfit"} title={`${draft.hat || draft.bottom ? "Redesign outfit" : "Design outfit"} (Enter)`}>
                          <IconWand size={18} /></button>}
                  </div>
                </div>
              </div>
              {error && (
                <div className="persona-error" role="alert">
                  <p>Couldn't draw the outfit: {error}. Try again, or pick another model.</p>
                  {!busy && draft.description?.trim() && <button className="ghost small" onClick={() => generate()}>Try again</button>}
                </div>
              )}
            </section>
          </div>
        </div>

      </div>

      {drawer && <div className="persona-scrim" aria-hidden="true" onClick={() => setDrawer(false)} />}
      {drawer && (
            <aside id="persona-drawer" className="persona-drawer" role="dialog" aria-modal="false" aria-labelledby="persona-coll">
              <div className="persona-coll-head">
                <h2 id="persona-coll">Collection</h2>
                {outfits && kind !== "all" && <span className="muted small">{count(kind)}/{MAX_OUTFITS}</span>}
                <span className="spacer" />
                <button ref={closeRef} className="ghost icon" aria-label="Close collection" title="Close (Esc)" onClick={() => setDrawer(false)}><IconX size={16} /></button>
              </div>
              {fullNote && (
                <p className="persona-full small" role="alert">You have {MAX_OUTFITS} {NOUN[fullNote]}s saved. Delete one below to save this {NOUN[fullNote]}.</p>
              )}
              {(hat.wear || bottom.wear) && (
                <button className="ghost bordered persona-keep" disabled={busy || assembling || inCollection || full("outfit") || !!hat.err || !!bottom.err} onClick={() => keep()}>
                  {inCollection ? <><IconCheck size={14} /> Current outfit saved</> : full("outfit") ? `${MAX_OUTFITS} outfits saved. Delete one to save this.` : "Save current outfit"}</button>
              )}
              <div>
                {outfits && outfits.length > 0 && (
                  <div className="tabs persona-kinds" role="tablist" aria-label="Show">
                    {KINDS.map(([k, label]) => (
                      <button key={k} role="tab" aria-selected={kind === k} className="tab" onClick={() => setKind(k)}>{label}</button>
                    ))}
                  </div>
                )}
              </div>
              {outfits === null ? <p className="muted small">Loading…</p>
                : outfits.length === 0 ? <p className="muted small">Outfits and pieces you save show up here. Pick a hat from one look and a bottom from another.</p>
                : !outfits.some((o) => kind === "all" || o.kind === kind) ? <p className="muted small">Nothing saved here yet.</p>
                : <ul className="outfit-grid">
                    {outfits.filter((o) => kind === "all" || o.kind === kind).map((o) => {
                      const worn = sameAs(o, draft);
                      return (
                        <li key={o.id} className={`outfit-card ${worn ? "worn" : ""}`}>
                          <button className="ghost outfit-pick" disabled={busy} onClick={() => wearOutfit(o)} title={o.description} aria-pressed={worn}>
                            <OutfitThumb o={o} />
                            <span className="outfit-name">{o.name}</span>
                            <span className="muted small">{KIND_ONE[o.kind]}{worn ? " · wearing" : ""}</span>
                          </button>
                          <button className={`ghost del ${confirmDel === o.id ? "confirm" : "icon"}`} aria-label={`Delete outfit ${o.name}`}
                            onClick={() => removeOutfit(o.id)} onBlur={() => setConfirmDel("")}>
                            {confirmDel === o.id ? "Delete?" : <IconTrash size={14} />}
                          </button>
                        </li>
                      );
                    })}
                  </ul>}
            </aside>
      )}
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
