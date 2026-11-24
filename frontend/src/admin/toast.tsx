import { createContext, useContext } from "react";
import type { PromiseToaster } from "@/components/kokonutui/promise-toast";

export const ToasterContext = createContext<PromiseToaster | null>(null);

export function useToaster() {
  const toaster = useContext(ToasterContext);
  if (!toaster) throw new Error("ToasterContext missing");
  return toaster;
}

export const errorText = (reason: unknown, fallback: string) =>
  reason instanceof Error && reason.message ? reason.message : fallback;
