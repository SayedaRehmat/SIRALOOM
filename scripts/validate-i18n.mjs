#!/usr/bin/env node
/**
 * SIRALOOM localization architecture guard.
 *
 * This is intentionally a static contract check. It does not attempt to
 * translate arbitrary scientific/user data. It protects the application-level
 * i18n architecture from regressions that previously caused production
 * failures or silent localization bypasses.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..");
const frontend = path.join(root, "frontend");
const i18nPath = path.join(frontend, "lib", "i18n.tsx");
const layoutPath = path.join(frontend, "app", "layout.tsx");

const failures = [];

function read(file) {
  return fs.readFileSync(file, "utf8");
}

function walk(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name.startsWith(".")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walk(full));
    else files.push(full);
  }
  return files;
}

function requireText(file, text, reason) {
  const content = read(file);
  if (!content.includes(text)) failures.push(reason);
}

if (!fs.existsSync(i18nPath)) failures.push("Missing frontend/lib/i18n.tsx.");
if (!fs.existsSync(layoutPath)) failures.push("Missing frontend/app/layout.tsx.");

if (failures.length === 0) {
  const i18n = read(i18nPath);
  const layout = read(layoutPath);

  requireText(i18nPath, 'export type AppLanguage = "en" | "ar" | "bilingual";',
    "AppLanguage must remain the single en/ar/bilingual locale contract.");
  requireText(i18nPath, "MutationObserver",
    "Global DOM localization must remain enabled so component-boundary and dynamically rendered UI is covered.");
  requireText(i18nPath, "ignoredTextTags",
    "Editable/code/script text protection must remain part of the DOM localization walker.");
  requireText(i18nPath, "translatableAttributes",
    "Controlled localization of placeholder/title/aria-label must remain enabled.");
  requireText(i18nPath, "uiArabicNormalized",
    "Case-normalized controlled UI translation lookup must remain enabled.");
  requireText(i18nPath, 'storageKey = "siraloom.language"',
    "The application locale must remain centrally persisted.");
  requireText(layoutPath, "<LanguageProvider>",
    "The root application layout must own the LanguageProvider.");
  requireText(layoutPath, "../lib/i18n",
    "The root layout must import the central i18n provider.");

  if (/\bignoredTags\b/.test(i18n)) {
    failures.push("Stale identifier 'ignoredTags' detected in i18n.tsx; use the current ignoredTextTags contract.");
  }

  if (/google\s*\.\s*translate|translate\.google|googtrans/i.test(i18n)) {
    failures.push("Runtime Google/browser translation must not be introduced into the clinical/scientific UI.");
  }

  for (const candidate of [
    path.join(frontend, "app", "ar"),
    path.join(frontend, "app", "en"),
    path.join(frontend, "app", "bilingual"),
  ]) {
    if (fs.existsSync(candidate)) {
      failures.push(`Duplicate locale route tree detected: ${path.relative(root, candidate)}. Use one shared page tree with centralized locale state.`);
    }
  }

  const sourceFiles = walk(path.join(frontend, "app"))
    .concat(walk(path.join(frontend, "components")))
    .filter((file) => /\.(tsx|ts)$/.test(file))
    .filter((file) => !file.endsWith("lib/i18n.tsx"));

  // The legacy DOM bridge is intentionally supported during migration, but it
  // must never become an excuse for silently introducing new untranslated UI.
  // Extract its controlled English source catalog and use it as a static gate
  // for literal JSX text and translatable attributes. Dynamic scientific data,
  // identifiers, expressions, and code-like values are deliberately ignored.
  const catalogKeys = new Set();
  for (const match of i18n.matchAll(/\[\s*["']((?:\\.|[^"'])+)["']\s*,/g)) {
    const value = match[1].replace(/\\(["'])/g, "$1");
    if (value.trim()) catalogKeys.add(value.trim());
  }

  const likelyUiText = (value) => {
    const text = value.replace(/\s+/g, " ").trim();
    if (!text || !/[A-Za-z]/.test(text)) return false;
    if (/^[A-Za-z0-9_./:@-]+$/.test(text)) return false;
    if (/^[A-Z0-9_ .·→←/&-]+$/.test(text) && text.length > 32) return false;
    if (/^(https?:\/\/|mailto:|tel:|data:)/i.test(text)) return false;
    if (/^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$/.test(text)) return false;
    return true;
  };

  const missingLegacyTranslations = [];
  const checkLiteral = (file, value, kind) => {
    const text = value.replace(/\s+/g, " ").trim();
    if (!likelyUiText(text)) return;
    if (catalogKeys.has(text)) return;
    if (/\{[^}]+\}/.test(text)) return;
    missingLegacyTranslations.push(
      path.relative(root, file) + ": " + kind + ' "' + text + '"'
    );
  };

  for (const file of sourceFiles.filter((candidate) => candidate.endsWith(".tsx"))) {
    const content = read(file);

    // JSX text nodes are the most common route by which a new English UI
    // sentence bypasses the typed translation API.
    for (const match of content.matchAll(/>([^<>{}\n]+)</g)) {
      checkLiteral(file, match[1], "untranslated JSX text");
    }

    // Catch user-facing placeholders, titles, and accessible labels too.
    for (const match of content.matchAll(/(?:placeholder|title|aria-label)\s*=\s*["']([^"']+)["']/g)) {
      checkLiteral(file, match[1], "untranslated UI attribute");
    }
  }

  if (missingLegacyTranslations.length) {
    failures.push(
      "New literal user-facing UI text is not present in the controlled Arabic catalog. " +
      "Use t(...) for new UI or add an intentional controlled translation before deployment.\n" +
      missingLegacyTranslations.slice(0, 40).map((item) => "  - " + item).join("\n") +
      (missingLegacyTranslations.length > 40 ? "\n  - ...and " + (missingLegacyTranslations.length - 40) + " more." : "")
    );
  }

  for (const file of sourceFiles) {
    const content = read(file);

    // A recurring production failure was calling t(...) after only destructuring
    // { language } from useLanguage(). Catch that class of error before Vercel.
    if (/useLanguage\s*\(\s*\)/.test(content) && /\bt\s*\(/.test(content)) {
      const useLanguageMatches = [...content.matchAll(/const\s*\{([^}]*)\}\s*=\s*useLanguage\s*\(\s*\)/g)];
      const hasT = useLanguageMatches.some((match) =>
        match[1].split(",").map((part) => part.trim()).some((part) => part === "t" || part.startsWith("t:"))
      );
      if (!hasT) {
        failures.push(`${path.relative(root, file)} calls t(...) but does not destructure t from useLanguage().`);
      }
    }

    // Locale direction and language attributes have one owner.
    if (file !== layoutPath && /document\.documentElement\.(lang|dir)/.test(content)) {
      failures.push(`${path.relative(root, file)} directly controls document language/direction; keep this centralized in lib/i18n.tsx.`);
    }
  }
}

if (failures.length) {
  console.error("\nSIRALOOM i18n architecture guard FAILED:\n");
  for (const failure of failures) console.error(`- ${failure}`);
  console.error("");
  process.exit(1);
}

console.log("SIRALOOM i18n architecture guard: PASS");
