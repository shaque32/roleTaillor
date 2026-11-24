import type { Metadata } from "next";
import { Suspense } from "react";
import { NewTailoring } from "./NewTailoring";

export const metadata: Metadata = { title: "New tailoring" };

export default function NewTailoringPage() {
  return (
    <Suspense>
      <NewTailoring />
    </Suspense>
  );
}
