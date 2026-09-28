import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const front = path.join(root, "frontend");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const failures = [];

const i18n = read("frontend/lib/i18n.tsx");
const messages = read("frontend/lib/messages.ts");
const layout = read("frontend/app/layout.tsx");
const shell = read("frontend/components/site-shell.tsx");
const home = read("frontend/app/(public)/page.tsx");

for (const token of ["MutationObserver", "LocalizedContent", "localizeUiText", "uiArabic", "uiArabicNormalized"]) {
  if (i18n.includes(token)) failures.push("Retired DOM localization token remains: " + token);
}

if (!i18n.includes('from "./messages"')) failures.push("LanguageProvider is not connected to the centralized message catalog.");
if (!messages.includes('export type TranslationKey')) failures.push("Centralized message catalog is missing TranslationKey.");
if (!messages.includes('export const messages')) failures.push("Centralized message catalog is missing messages.");

function localeKeys(locale) {
  const startMarker = "  " + locale + ": {";
  const start = messages.indexOf(startMarker);
  if (start < 0) throw new Error("Missing " + locale + " catalog.");
  const endMarker = locale === "en" ? "\n  ar: {" : "\n  },\n};";
  const end = messages.indexOf(endMarker, start);
  if (end < 0) throw new Error("Malformed " + locale + " catalog.");
  const block = messages.slice(start + startMarker.length, end);
  return [...block.matchAll(/^\s*"([^"]+)"\s*:/gm)].map((m) => m[1]);
}

try {
  const en = localeKeys("en");
  const ar = localeKeys("ar");
  const missingInArabic = en.filter((key) => !ar.includes(key));
  const extraInArabic = ar.filter((key) => !en.includes(key));
  if (!en.length) failures.push("English catalog is empty.");
  if (missingInArabic.length) failures.push("Arabic catalog is missing: " + missingInArabic.join(", "));
  if (extraInArabic.length) failures.push("Arabic catalog has unknown IDs: " + extraInArabic.join(", "));
} catch (error) {
  failures.push(error instanceof Error ? error.message : String(error));
}

if (!layout.includes("cookies()")) failures.push("Root layout must resolve the persisted locale from the cookie.");
if (!layout.includes("initialLanguage={language}")) failures.push("Root layout must seed LanguageProvider with the server-resolved locale.");
if (!layout.includes("dir={direction}")) failures.push("Root layout must own document direction.");
if ((shell.match(/<LanguageSwitcher\b/g) || []).length !== 1) failures.push("SiteShell must contain exactly one language selector.");
if (!shell.includes("showLanguageSwitcher?:")) failures.push("SiteShell must expose homepage-only selector opt-in.");
if (!home.includes("<SiteShell showLanguageSwitcher>")) failures.push("Homepage must opt into the language selector.");

for (const locale of ["ar", "en", "bilingual"]) {
  if (fs.existsSync(path.join(front, "app", locale))) failures.push("Duplicate locale route tree detected: frontend/app/" + locale);
}

if (failures.length) {
  console.error("SIRALOOM i18n architecture guard FAILED:");
  for (const failure of failures) console.error("- " + failure);
  process.exit(1);
}

console.log("SIRALOOM i18n architecture guard: PASS");
