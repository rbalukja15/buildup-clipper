"use client";

import { useEffect } from "react";

export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(onDone, 5200);
    return () => clearTimeout(timer);
  }, [message, onDone]);

  if (!message) return null;
  return (
    <div className="toast" role="alert" onClick={onDone}>
      {message}
    </div>
  );
}
