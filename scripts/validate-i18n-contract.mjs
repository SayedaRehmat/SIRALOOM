import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const front = path.join(root, "frontend");
const read = (p) => fs.readFileSync(path.join(root, p), "utf8");
const fail = [];
const i18n = read("frontend/lib/i18n.tsx");
const catalog = read("frontend/lib/messages.ts");
const layout = read("frontend/app/layout.tsx");
const shell = read("frontend/components/site-shell.tsx");
const home = read("frontend/app/(public)/page.tsx");

for (const token of ["MutationObserver", "LocalizedContent", "localizeUiText", "uiArabic"]) {
  if (i18n.includes(token)) fail.push("legacy localization token: " + token);
}
if (!i18n.includes('from "./messages"')) fail.push("provider is not connected to messages");
if (!catalog.includes("export type TranslationKey")) fail.push("missing typed message IDs");
if (!catalog.includes("export const messages")) fail.push("missing message catalog");
if (!layout.includes("cookies()")) fail.push("root layout must read locale cookie");
if (!layout.includes("initialLanguage={language}")) fail.push("root layout must seed locale");
if (!layout.includes("dir={direction}")) fail.push("root layout must own direction");
if ((shell.match(/<LanguageSwitcher/g) || []).length !== 1) fail.push("selector count is not exactly one");
if (!shell.includes("showLanguageSwitcher?:")) fail.push("selector opt-in contract missing");
if (!home.includes("<SiteShell showLanguageSwitcher>")) fail.push("homepage selector opt-in missing");

function keys(locale) {
  const marker = "  " + locale + ": {";
  const start = catalog.indexOf(marker);
  const end = catalog.indexOf("\n  },", start);
  if (start < 0 || end < 0) throw new Error("malformed " + locale + " catalog");
  return catalog.slice(start + marker.length, end).split("\n")
    .map((x) => x.trim())
    .filter((x) => x.startsWith('"') && x.includes('":'))
    .map((x) => x.slice(1, x.indexOf('":')));
}

const en = keys("en");
const ar = keys("ar");
const bi = keys("bilingual");
if (!en.length) fail.push("English catalog is empty");
if (en.length !== ar.length || en.some((x) => !ar.includes(x))) fail.push("English/Arabic catalog mismatch");
if (en.length !== bi.length || en.some((x) => !bi.includes(x))) fail.push("English/bilingual catalog mismatch");

for (const locale of ["ar", "en", "bilingual"]) {
  if (fs.existsSync(path.join(front, "app", locale))) fail.push("duplicate locale route: " + locale);
}

if (fail.length) throw new Error("SIRALOOM i18n contract FAILED: " + fail.join(" | "));
console.log("SIRALOOM i18n contract: PASS");
