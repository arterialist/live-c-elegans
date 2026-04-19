import js from "@eslint/js";
import tseslint from "typescript-eslint";
import globals from "globals";

/**
 * Flat ESLint config.
 *
 * The hard rule we enforce is the fetch ban: every HTTP call must go through
 * `axios` via src/api/http.ts. The rest is standard TS + browser linting.
 */
export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: { ecmaVersion: 2024, sourceType: "module" },
    },
    rules: {
      "no-restricted-globals": [
        "error",
        {
          name: "fetch",
          message: "Use axios via src/api/http.ts instead of native fetch.",
        },
      ],
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
