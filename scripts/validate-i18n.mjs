#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const frontend = path.join(root, "frontend");
const files = {
  i18n: path.join(frontend, "lib", "i18n.tsx"),
  messages: path.join(frontend, "lib", "messages.ts"),
  layout: path.join(frontend, "app", "layout.tsx"),
  shell: path.join(frontend, "components", "site-shell.tsx"),
  home: path.join(frontend, "app", "(public)", "page.tsx"),
};
const failures = [];
const read = (file) => fs.readFileSync(file, "utf8");

for (const [name, file] of Object.entries(files)) {
  if (!fs.existsSync(file)) failures.push("Missing i18n contract file: " + name);
}

function catalogKeys(source, locale) {
  const marker = "  " + locale + ": {";
  const start = source.indexOf(marker);
  if (start < 0) throw new Error("Missing " + locale + " catalog");
  const end = source.indexOf("\n  },", start);
  if (end < 0) throw new Error("Malformed " + locale + " catalog");
  return source.slice(start + marker.length, end)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith('"') && line.includes('":'))
    .map((line) => line.slice(1, line.indexOf('":')));
}

function sameSet(a, b) {
  return a.length === b.length && a.every((value) => b.includes(value));
}

if (!failures.length) {
  const i18n = read(files.i18n);
  const messages = read(files.messages);
  const layout = read(files.layout);
  const shell = read(files.shell);
  const home = read(files.home);

  for (const token of ["MutationObserver", "LocalizedContent", "localizeUiText", "uiArabicNormalized", "uiArabic"]) {
    if (i18n.includes(token)) failures.push("Retired DOM localization token remains in lib/i18n.tsx: " + token);
  }
  if (!i18n.includes('from "./messages"')) failures.push("lib/i18n.tsx must import the centralized messages catalog.");
  if (!messages.includes("export type TranslationKey")) failures.push("messages.ts must export TranslationKey.");
  if (!messages.includes("export const messages")) failures.push("messages.ts must export messages.");

  try {
    const en = catalogKeys(messages, "en");
    const ar = catalogKeys(messages, "ar");
    const bilingual = catalogKeys(messages, "bilingual");
    if (!en.length) failures.push("English catalog is empty.");
    if (!sameSet(en, ar)) failures.push("English and Arabic message IDs differ.");
    if (!sameSet(en, bilingual)) failures.push("English and bilingual message IDs differ.");
  } catch (error) {
    failures.push(error instanceof Error ? error.message : String(error));
  }

  if (!layout.includes("cookies()") || !layout.includes("siraloom.language")) failures.push("Root layout must resolve locale from the persisted cookie.");
  if (!layout.includes("<LanguageProvider initialLanguage={language}>")) failures.push("Root layout must pass the resolved locale into LanguageProvider.");
  if (!layout.includes('<html lang={language === "ar" ? "ar" : "en"} dir={direction}>')) failures.push("Root layout must own document lang and dir.");

  if ((shell.match(/<LanguageSwitcher/g) || []).length !== 1) failures.push("SiteShell must render exactly one LanguageSwitcher.");
  if (!shell.includes("showLanguageSwitcher?:")) failures.push("SiteShell must expose homepage-only language-switcher opt-in.");
  if (!home.includes("<SiteShell showLanguageSwitcher>")) failures.push("The public homepage must opt into the language selector.");

  for (const locale of ["ar", "en", "bilingual"]) {
    if (fs.existsSync(path.join(frontend, "app", locale))) failures.push("Duplicate locale route tree detected: frontend/app/" + locale);
  }

  const sourceFiles = [];
  function walk(dir) {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === ".next" || entry.name.startsWith(".")) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (full.endsWith(".ts") || full.endsWith(".tsx")) sourceFiles.push(full);
    }
  }
  walk(path.join(frontend, "app"));
  walk(path.join(frontend, "components"));

  const keySet = new Set(catalogKeys(messages, "en"));
  for (const file of sourceFiles) {
    const source = read(file);
    for (const match of source.matchAll(/t\(\s*["']([^"']+)["']/g)) {
      if (!keySet.has(match[1])) failures.push(path.relative(root, file) + " uses unknown translation key " + match[1]);
    }
    if (file !== files.layout && source.includes("document.documentElement.lang")) failures.push(path.relative(root, file) + " directly controls document language.");
    if (file !== files.layout && source.includes("document.documentElement.dir")) failures.push(path.relative(root, file) + " directly controls document direction.");
    for (const token of ["MutationObserver", "LocalizedContent", "localizeUiText", "uiArabicNormalized"]) {
      if (source.includes(token)) failures.push(path.relative(root, file) + " references retired localization token " + token);
    }
  }
}

if (failures.length) {
  console.error("\nSIRALOOM i18n architecture guard FAILED:\n");
  failures.forEach((failure) => console.error("- " + failure));
  process.exit(1);
}
console.log("SIRALOOM i18n architecture guard: PASS");
