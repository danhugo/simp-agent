// App icons: Lucide (lucide-react), wrapped so call sites keep using Icon* with a `size` prop.
// Soft 1.5px strokes, currentColor, decorative by default (give the button an aria-label or text).
import type { LucideIcon, LucideProps } from "lucide-react";
import {
  ArrowDown, ArrowUp, Bell, Brain, Check, ChevronRight, Copy, Download, Ellipsis, Eye, EyeOff, FileText, Folder, Link, LogOut, Menu, Moon,
  PanelLeft, Plus, RefreshCw, Shrink, Square, SquarePen, Sun, Trash, Upload, X,
} from "lucide-react";

type P = LucideProps & { size?: number };
const wrap = (I: LucideIcon, extra: LucideProps = {}) => ({ size = 16, ...rest }: P) => (
  <I size={size} strokeWidth={1.5} aria-hidden focusable={false} {...extra} {...rest} />
);

export const IconPlus = wrap(Plus);
export const IconCompose = wrap(SquarePen);
export const IconMenu = wrap(Menu);
export const IconSidebar = wrap(PanelLeft);
export const IconMore = wrap(Ellipsis);
export const IconTrash = wrap(Trash);
export const IconSun = wrap(Sun);
export const IconMoon = wrap(Moon);
export const IconLogout = wrap(LogOut);
export const IconArrowUp = wrap(ArrowUp);
export const IconArrowDown = wrap(ArrowDown);
export const IconStop = wrap(Square, { fill: "currentColor" });
export const IconCopy = wrap(Copy);
export const IconCheck = wrap(Check);
export const IconFolder = wrap(Folder);
export const IconFile = wrap(FileText);
export const IconUpload = wrap(Upload);
export const IconDownload = wrap(Download);
export const IconRefresh = wrap(RefreshCw);
export const IconBell = wrap(Bell);
export const IconClose = wrap(X);
export const IconChevron = wrap(ChevronRight);
export const IconCompact = wrap(Shrink);
export const IconEye = wrap(Eye);
export const IconEyeOff = wrap(EyeOff);
export const IconMemory = wrap(Brain);
export const IconLink = wrap(Link);
