import type { ComponentProps } from "react";
import { buttonVariants } from "./ui/button";
import { cn } from "@/lib/utils";

/** Maps portal action intent to the shared shadcn/Kokonut button primitive. */
export function ActionButton({
  className = "",
  type = "submit",
  disabled,
  children,
  onClick,
  ...props
}: ComponentProps<"button">) {
  const classes = typeof className === "string" ? className.split(/\s+/) : [];
  const danger = classes.some((c) => c.startsWith("danger"));
  const variant = danger
    ? "destructive"
    : classes.includes("primary")
      ? "default"
      : "outline";
  const size = classes.includes("compact") ? "sm" : "default";

  return (
    <button
      {...props}
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={cn(buttonVariants({ variant, size }), className)}
    >
      {children}
    </button>
  );
}
