import { CheckCircle2 } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

export function SuccessNotice({ message }: { message: string }) {
  const reducedMotion = useReducedMotion();
  return (
    <AnimatePresence>
      {message ? (
        <motion.p
          animate={{ opacity: 1, y: 0 }}
          className="kokonut-notice"
          initial={reducedMotion ? false : { opacity: 0, y: -4 }}
          role="status"
          transition={{ duration: 0.16 }}
        >
          <CheckCircle2 aria-hidden="true" size={17} />
          {message}
        </motion.p>
      ) : null}
    </AnimatePresence>
  );
}
