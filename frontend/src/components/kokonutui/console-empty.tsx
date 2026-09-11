/** Compact SecureCloud adaptation of Kokonut UI's Empty State. */
import { Boxes } from "lucide-react";
import type { ReactNode } from "react";

export function ConsoleEmpty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="kokonut-empty">
      <Boxes aria-hidden="true" size={22} />
      <div>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </div>
  );
}
