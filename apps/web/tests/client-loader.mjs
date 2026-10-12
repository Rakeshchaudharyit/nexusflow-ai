import { readFile } from "node:fs/promises";
import ts from "typescript";

const transpile = async (name) =>
  ts.transpileModule(
    await readFile(
      new URL(`../src/lib/api/${name}.ts`, import.meta.url),
      "utf8",
    ),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ES2022,
      },
    },
  ).outputText;
const asModule = (source) =>
  `data:text/javascript,${encodeURIComponent(source)}`;
const authSource = await transpile("auth");
let instance = 0;

// Loads an isolated auth module (fresh token state) and wires `name` to it.
export async function freshClients(name) {
  const auth = asModule(`${authSource}\n// instance ${instance++}`);
  const source = (await transpile(name)).replace(
    '"./auth"',
    JSON.stringify(auth),
  );
  return { auth: await import(auth), client: await import(asModule(source)) };
}

export const json = (value, status = 200) =>
  new Response(JSON.stringify(value), { status });
export const session = (token) =>
  json({
    access_token: token,
    token_type: "bearer",
    expires_in: 900,
    user: {},
  });

// Loads a module that has no runtime imports (e.g. src/lib/actions.ts, whose imports are types).
export async function loadModule(path) {
  const source = ts.transpileModule(
    await readFile(new URL(`../src/${path}`, import.meta.url), "utf8"),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ES2022,
      },
    },
  ).outputText;
  return import(asModule(source));
}
