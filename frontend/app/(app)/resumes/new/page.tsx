import type { Metadata } from "next";
import { Suspense } from "react";
import { GuidedBuilder } from "./GuidedBuilder";

export const metadata: Metadata = { title: "Build a resume" };

export default function NewResumePage() {
  return (
    <Suspense>
      <GuidedBuilder />
    </Suspense>
  );
}
