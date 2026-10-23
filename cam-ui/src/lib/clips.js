import { join } from "node:path";

export const recordingsRoot = join(process.cwd(), "recordings");

export function clipIdOk(id) {
  return typeof id === "string" && /^[\w.-]+$/.test(id) && id !== "." && id !== "..";
}

export function frameNameOk(name) {
  return typeof name === "string" && /^\d{3}\.png$/.test(name);
}

export function clipDir(id) {
  return join(recordingsRoot, id);
}
