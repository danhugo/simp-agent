// App icons: Lucide (lucide-react), wrapped so call sites keep using Icon* with a `size` prop.
// Soft 1.5px strokes, currentColor, decorative by default (give the button an aria-label or text).
import type { LucideIcon, LucideProps } from "lucide-react";
import {
  ArrowDown, ArrowUp, Bell, Brain, CalendarDays, ChartColumn, Check, ChevronRight, Copy, Download, Ellipsis, Eye, File, FileCode, FileImage, FileSpreadsheet, FileText, FileType, Globe, Folder, LayoutGrid, LogOut, Menu, Moon,
  PanelLeft, Pencil, Plus, Search, RefreshCw, Shrink, Square, SquarePen, Sun, Trash, Upload, X,
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
export const IconEdit = wrap(Pencil);
export const IconCalendar = wrap(CalendarDays);
export const IconChart = wrap(ChartColumn);
export const IconSearch = wrap(Search);
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
// one icon per preview kind (fileKind.ts)
export const KindIcons = {
  code: wrap(FileCode), markdown: wrap(FileText), image: wrap(FileImage), sheet: wrap(FileSpreadsheet),
  office: wrap(FileType), html: wrap(Globe), pdf: wrap(FileText), info: wrap(File),
};
export const IconEye = wrap(Eye);
export const IconUpload = wrap(Upload);
export const IconDownload = wrap(Download);
export const IconRefresh = wrap(RefreshCw);
export const IconBell = wrap(Bell);
export const IconClose = wrap(X);
export const IconChevron = wrap(ChevronRight);
export const IconCompact = wrap(Shrink);
export const IconMemory = wrap(Brain);
export const IconApps = wrap(LayoutGrid);
