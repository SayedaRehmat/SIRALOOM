#!/usr/bin/env node

/**
 * SIRALOOM i18n architecture guard.
 *
 * Validates message catalogs and integration points. It intentionally does not
 * scan arbitrary JSX text: scientific identifiers and source-code fragments
 * must never be classified as translatable UI by a regex.
 */

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
  if (!fs.existsSync(file)) failures.push(`Missing i18n contract file: ${name} (${path.relative(root, file)}).`);
}

function catalogKeys(source, locale) {
  const match = source.match(new RegExp(`\\b${locale}\\s*:\\s*\\{([\\s\\S]*?)\\n\\s*\\},`));
  if (!match) throw new Error(`Missing ${locale} catalog`);
  return [...match[1].matchAll(/^\\s*"([^"]+)"\\s*:/gm)].map((m) => m[1]);
}

function unique(values) {
  return [...new Set(values)];
}

function equalSets(a, b) {
  return a.length === b.length && a.every((value) => b.includes(value));
}

if (!failures.length) {
  const i18n = read(files.i18n);
  const messages = read(files.messages);
  const layout = read(files.layout);
  const shell = read(files.shell);
  const home = read(files.home);

  if (/MutationObserver|LocalizedContent|localizeUiText|uiArabicNormalized|\\buiArabic\\b/.test(i18n)) {
    failures.push("Legacy DOM/text localization code remains in frontend/lib/i18n.tsx.");
  }
  if (!/from "\\.\\/messages"/.test(i18n)) {
    failures.push("frontend/lib/i18n.tsx must consume the centralized messages catalog.");
  }
  if (!/export type TranslationKey/.test(messages) || !/export const messages/.test(messages)) {
    failures.push("frontend/lib/messages.ts must export TranslationKey and messages.");
  }

  try {
    const en = unique(catalogKeys(messages, "en"));
    const ar = unique(catalogKeys(messages, "ar"));
    const bilingual = unique(catalogKeys(messages, "bilingual"));
    if (!en.length) failures.push("English catalog is empty.");
    if (!equalSets(en, ar)) failures.push("English and Arabic message IDs differ.");
    if (!equalSets(en, bilingual)) failures.push("English and bilingual message IDs differ.");
  } catch (error) {
    failures.push(error instanceof Error ? error.message : String(error));
  }

  if (!/cookies\(\)/.test(layout) || !/siraloom\\.language/.test(layout)) {
    failures.push("Root layout must resolve the persisted locale from the server cookie.");
  }
  if (!/<LanguageProvider initialLanguage=\\{language\\}>/.test(layout)) {
    failures.push("Root layout must pass the resolved locale into LanguageProvider.");
  }
  if (!/<html lang=\\{[^}]+\\} dir=\\{[^}]+\\}>/.test(layout)) {
    failures.push("Root layout must own document lang and dir.");
  }

  if ((shell.match(/<LanguageSwitcher\\b/g) || []).length !== 1) {
    failures.push("SiteShell must render exactly one LanguageSwitcher.");
  }
  if (!/showLanguageSwitcher\\s*\\??:/.test(shell)) {
    failures.push("SiteShell must expose homepage-only language-switcher opt-in.");
  }
  if (!/<SiteShell\\s+showLanguageSwitcher\\b/.test(home)) {
    failures.push("Only the public homepage should opt into the language selector.");
  }

  for (const candidate of ["ar", "en", "bilingual"]) {
    const routeTree = path.join(frontend, "app", candidate);
    if (fs.existsSync(routeTree)) failures.push(`Duplicate locale route tree detected: frontend/app/${candidate}`);
  }

  const sourceFiles = [];
  function walk(dir) {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === ".next" || entry.name.startsWith(".")) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\\.(ts|tsx)$/.test(entry.name)) sourceFiles.push(full);
    }
  }
  walk(path.join(frontend, "app"));
  walk(path.join(frontend, "components"));

  const keys = new Set(catalogKeys(messages, "en"));
  for (const file of sourceFiles) {
    const source = read(file);
    for (const match of source.matchAll(/\\bt\\(\\s*["']([^"']+)["']/g)) {
      if (!keys.has(match[1])) failures.push(`${path.relative(root, file)} uses unknown translation key "${match[1]}".`);
    }
    if (file !== files.layout && /document\\.documentElement\\.(lang|dir)/.test(source)) {
      failures.push(`${path.relative(root, file)} directly controls document language/direction.`);
    }
    if (/MutationObserver|LocalizedContent|localizeUiText|uiArabicNormalized/.test(source)) {
      failures.push(`${path.relative(root, file)} still references the retired DOM localization API.`);
    }
  }
}

if (failures.length) {
  console.error("\\nSIRALOOM i18n architecture guard FAILED:\\n");
  for (const failure of failures) console.error("- " + failure);
  process.exit(1);
}

console.log("SIRALOOM i18n architecture guard: PASS");
