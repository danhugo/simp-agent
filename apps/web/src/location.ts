/** Opt-in approximate location: only sent with new sessions when the user turns on "Share location". */
export type Loc = { lat: number; lon: number };
const KEY = "simp.location";

/** Round to 1 decimal (~10 km) so only an approximate position ever leaves the browser. */
export const approx = (lat: number, lon: number): Loc => ({ lat: Math.round(lat * 10) / 10, lon: Math.round(lon * 10) / 10 });

export function savedLocation(): Loc | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return v && typeof v.lat === "number" && typeof v.lon === "number" ? approx(v.lat, v.lon) : null;
  } catch { return null; }
}

export function saveLocation(l: Loc | null) {
  try { if (l) localStorage.setItem(KEY, JSON.stringify(l)); else localStorage.removeItem(KEY); } catch { /* storage blocked */ }
  mem = l;
}
let mem: Loc | null = null;
/** Current shared location (in-memory copy survives blocked storage for this tab). */
export const sharedLocation = (): Loc | null => mem ?? savedLocation();

export function requestLocation(): Promise<Loc> {
  return new Promise((ok, fail) => {
    if (!navigator.geolocation) return fail(new Error("Location is not available in this browser."));
    navigator.geolocation.getCurrentPosition((p) => ok(approx(p.coords.latitude, p.coords.longitude)),
      (e) => fail(new Error(e.code === 1 ? "Location permission denied." : "Location unavailable.")),
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 });
  });
}
